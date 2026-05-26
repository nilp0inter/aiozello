import sys
import os
import json
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from aiozello.__main__ import Application, OutboundAudioStream, convert_to_dataclass
from aiozello.stream import IncomingAudioStream, PacketType
from aiozello.protocol import ChannelStatus, StreamStart, StreamStop, TextMessage, Image


def test_side_effect_free_import():
    # Verify that we can import Application cleanly
    assert Application is not None


def test_constructor_validation():
    with pytest.raises(ValueError):
        Application(token=None, token_loader=None)


def test_queue_backpressure_and_drop_oldest():
    async def _test():
        # 2 frames * 60ms = 120ms duration.
        # 10s of audio is 10000ms / 120ms = 83.33 -> maxsize = 83 packets.
        stream = IncomingAudioStream(sample_rate_hz=16000, frames_per_packet=2, frame_size_ms=60)
        assert stream.incoming.maxsize == 83
        assert stream.dropped_packets == 0

        # Put 83 packets -> queue should be full
        for i in range(83):
            await stream.put(f"packet-{i}".encode())
        
        assert stream.incoming.full()
        assert stream.dropped_packets == 0

        # Put one more packet -> oldest (packet-0) should be dropped
        await stream.put(b"packet-83")
        assert stream.incoming.full()
        assert stream.dropped_packets == 1

        # Verify that the next item dequeued is packet-1, NOT packet-0
        first = await stream.incoming.get()
        assert first == b"packet-1"
    
    asyncio.run(_test())


def test_outbound_stream_context_manager():
    async def _test():
        app = Application(token="dummy")
        
        # Mock _send_start, _send_packet, _send_stop
        app._send_start = AsyncMock(return_value=42)
        app._send_packet = AsyncMock()
        app._send_stop = AsyncMock()

        assert app._active_outbound_streams == 0

        async with app.outbound_stream(codec_header="abc", packet_duration_ms=120) as stream:
            assert app._active_outbound_streams == 1
            assert stream.stream_id == 42
            
            await stream.send(b"opus-1")
            await stream.send(b"opus-2")

        assert app._active_outbound_streams == 0
        
        # Verify calls
        app._send_start.assert_called_once_with("abc", 120)
        assert app._send_packet.call_count == 2
        app._send_packet.assert_any_call(42, 0, b"opus-1")
        app._send_packet.assert_any_call(42, 1, b"opus-2")
        app._send_stop.assert_called_once_with(42)

    asyncio.run(_test())


def test_outbound_stream_exception_cleanup():
    async def _test():
        app = Application(token="dummy")
        app._send_start = AsyncMock(return_value=100)
        app._send_packet = MagicMock()
        app._send_stop = AsyncMock()

        with pytest.raises(ValueError):
            async with app.outbound_stream(codec_header="abc", packet_duration_ms=120) as stream:
                assert app._active_outbound_streams == 1
                raise ValueError("Something went wrong")

        assert app._active_outbound_streams == 0
        app._send_stop.assert_called_once_with(100)

    asyncio.run(_test())


def test_soft_reconnect_deferral():
    async def _test():
        app = Application(token="dummy", token_refresh_interval_s=0.05, token_loader=lambda: "dummy")
        
        app._trigger_soft_reconnect = AsyncMock()
        
        # Start timer loop with 1 active outbound stream
        app._active_outbound_streams = 1
        task = asyncio.create_task(app._refresh_timer_loop())
        
        # Wait for the timer to fire
        await asyncio.sleep(0.1)
        
        # Soft reconnect should be deferred
        app._trigger_soft_reconnect.assert_not_called()
        
        # Decrease active streams to 0
        app._active_outbound_streams = 0
        
        # Wait for loop to detect and call trigger
        await asyncio.sleep(0.3)
        app._trigger_soft_reconnect.assert_called()
        
        task.cancel()

    asyncio.run(_test())


def test_callback_dataclass_dispatch():
    async def _test():
        cb_calls = []
        image_metadata_calls = []
        image_data_calls = []
        
        async def channel_status_cb(event):
            cb_calls.append(event)

        async def image_metadata_cb(event):
            image_metadata_calls.append(event)

        async def image_data_cb(image_id, data):
            image_data_calls.append((image_id, data))
            
        app = Application(
            token="dummy",
            callbacks={
                "on_channel_status": channel_status_cb,
                "on_image_metadata": image_metadata_cb,
                "on_image_data": image_data_cb,
            }
        )
        
        # 1. Text Message event
        msg_mock = MagicMock()
        msg_mock.type = aiohttp.WSMsgType.TEXT
        msg_mock.data = json.dumps({
            "command": "on_channel_status",
            "channel": "test-channel",
            "status": "online",
            "users_online": 5,
            "images_supported": True,
            "texting_supported": False,
            "locations_supported": True
        })
        await app._handle_message(msg_mock)
        
        # 2. JSON Image metadata event
        img_metadata_msg = MagicMock()
        img_metadata_msg.type = aiohttp.WSMsgType.TEXT
        img_metadata_msg.data = json.dumps({
            "command": "on_image",
            "channel": "test-channel",
            "from": "user123",
            "message_id": "msg999",
            "source": "src-url",
            "type": "jpg"
        })
        await app._handle_message(img_metadata_msg)

        # 3. Binary Image packet
        binary_packet = bytes([0x02]) + int(888).to_bytes(4, "big") + int(1).to_bytes(4, "big") + b"fake-jpeg-bytes"
        binary_msg = MagicMock()
        binary_msg.type = aiohttp.WSMsgType.BINARY
        binary_msg.data = binary_packet
        await app._handle_message(binary_msg)
        
        await asyncio.sleep(0.05)
        
        # Verify channel status
        assert len(cb_calls) == 1
        assert cb_calls[0].channel == "test-channel"
        
        # Verify split image metadata callback
        assert len(image_metadata_calls) == 1
        assert isinstance(image_metadata_calls[0], Image)
        assert image_metadata_calls[0].sender == "user123"
        assert image_metadata_calls[0].message_id == "msg999"

        # Verify split image binary callback
        assert len(image_data_calls) == 1
        assert image_data_calls[0] == (888, b"fake-jpeg-bytes")

    asyncio.run(_test())


def test_reconnect_fires_channel_status():
    async def _test():
        cb_calls = []
        
        async def channel_status_cb(event):
            cb_calls.append(event)
            
        app = Application(
            token="dummy",
            username="bot",
            password="pwd",
            channels=["chan"],
            callbacks={"on_channel_status": channel_status_cb}
        )
        
        ws_mock = MagicMock()
        ws_mock.closed = False
        ws_mock.close = AsyncMock()
        ws_mock.send_str = AsyncMock()
        
        msg_channel_status = MagicMock()
        msg_channel_status.type = aiohttp.WSMsgType.TEXT
        msg_channel_status.data = json.dumps({
            "command": "on_channel_status",
            "channel": "chan",
            "status": "online",
            "users_online": 2
        })
        
        class MockWSResponse:
            def __init__(self):
                self.sent_status = False
                
            def __aiter__(self):
                return self
                
            async def __anext__(self):
                if not self.sent_status:
                    self.sent_status = True
                    return msg_channel_status
                else:
                    raise ConnectionResetError("Disconnected")
        
        class AsyncContextManagerMock:
            async def __aenter__(self):
                return ws_mock
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
                
        ws_connect_mock = AsyncContextManagerMock()
        
        class AsyncSessionMock:
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
            def ws_connect(self, url):
                return ws_connect_mock
                
        session_mock = AsyncSessionMock()
        
        connections = []
        
        def get_iter(*args, **kwargs):
            resp = MockWSResponse()
            connections.append(resp)
            return resp
            
        ws_mock.__aiter__ = get_iter
        
        original_sleep = asyncio.sleep
        
        async def mock_sleep(delay):
            if len(connections) >= 2:
                app._is_running = False
            await original_sleep(0.01)
            
        with patch("aiohttp.ClientSession", return_value=session_mock):
            with patch("asyncio.sleep", side_effect=mock_sleep):
                try:
                    await asyncio.wait_for(app.run(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
                    
        assert len(connections) >= 2
        assert len(cb_calls) == len(connections)
        for event in cb_calls:
            assert isinstance(event, ChannelStatus)
            assert event.channel == "chan"
            assert event.status == "online"
            
    asyncio.run(_test())
