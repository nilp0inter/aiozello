import sys
import os
import json
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from aiozello.__main__ import Application, OutboundAudioStream, convert_to_dataclass
from aiozello.stream import IncomingAudioStream
from aiozello.protocol import ChannelStatus, StreamStart, StreamStop, TextMessage


def test_side_effect_free_import():
    # Verify that we can import Application and write_to_file does not cause side effects
    assert Application is not None


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
        app = Application()
        
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
        app = Application()
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
        app = Application(token_loader=lambda: "dummy-token", token_refresh_interval_s=0.05)
        
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
        
        async def channel_status_cb(event):
            cb_calls.append(event)
            
        app = Application(callbacks={"on_channel_status": channel_status_cb})
        
        # Mock WSMsgType.TEXT message with on_channel_status command
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
        
        # Give a tiny slice of time for the spawned callback task to run
        await asyncio.sleep(0.05)
        
        assert len(cb_calls) == 1
        event = cb_calls[0]
        assert isinstance(event, ChannelStatus)
        assert event.channel == "test-channel"
        assert event.status == "online"
        assert event.users_online == 5
        assert event.images_supported is True
        assert event.texting_supported is False
        assert event.locations_supported is True

    asyncio.run(_test())
