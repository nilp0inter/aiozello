import subprocess
import json
import os
import tempfile
import wave
import logging
from typing import Callable, Optional

import aiohttp
import asyncio

from aiozello.auth import LocalTokenManager
from aiozello.error import get_exception_by_error_code
from aiozello.codec import decode_codec_header, encode_codec_header
from aiozello.stream import PacketType, decode_stream_packet, IncomingAudioStream, encode_audio_packet
from aiozello.protocol import ChannelStatus, StreamStart, StreamStop, Image, Location, TextMessage


ZELLO_WEB_SOCKET_URL = "wss://zello.io/ws"

logger = logging.getLogger(__name__)


def make_logon_request(token, username, password, channels):
    return json.dumps(
        {
            "command": "logon",
            "seq": 1,
            "auth_token": token,
            "username": username,
            "password": password,
            "channels": channels,
        }
    )


def convert_to_dataclass(command: str, data: dict):
    payload = data.copy()
    if "from" in payload:
        payload["sender"] = payload.pop("from")

    if command == "on_channel_status":
        return ChannelStatus(
            channel=payload.get("channel", ""),
            status=payload.get("status", ""),
            users_online=payload.get("users_online", 0),
            images_supported=payload.get("images_supported", False),
            texting_supported=payload.get("texting_supported", False),
            locations_supported=payload.get("locations_supported", False),
            error=payload.get("error"),
            error_type=payload.get("error_type"),
        )
    elif command == "on_stream_start":
        return StreamStart(
            type=payload.get("type", ""),
            codec=payload.get("codec", ""),
            packet_duration=payload.get("packet_duration", 0),
            stream_id=payload.get("stream_id", 0),
            channel=payload.get("channel", ""),
            sender=payload.get("sender", ""),
            key=payload.get("key", ""),
            codec_header=payload.get("codec_header", ""),
        )
    elif command == "on_stream_stop":
        return StreamStop(
            stream_id=payload.get("stream_id", 0),
        )
    elif command == "on_text_message":
        return TextMessage(
            channel=payload.get("channel", ""),
            sender=payload.get("sender", ""),
            message_id=payload.get("message_id", 0),
            text=payload.get("text", ""),
        )
    elif command == "on_image":
        return Image(
            channel=payload.get("channel", ""),
            sender=payload.get("sender", ""),
            message_id=payload.get("message_id", ""),
            source=payload.get("source", ""),
            type=payload.get("type", ""),
        )
    elif command == "on_location":
        return Location(
            channel=payload.get("channel", ""),
            sender=payload.get("sender", ""),
            message_id=payload.get("message_id", 0),
            latitude=payload.get("latitude", 0.0),
            longitude=payload.get("longitude", 0.0),
            accuracy=payload.get("accuracy", 0.0),
            formatted_address=payload.get("formatted_address", ""),
        )
    return None


KNOWN_CALLBACKS = [
    "on_channel_status",
    "on_stream_start",
    "on_stream_stop",
    "on_text_message",
    "on_image",
    "on_location",
    "on_unknown_command",
    "on_unknown_message",
    "on_ws_error",
    "on_ws_closed",
    "on_unknown_binary",
    "on_unknown_ws_message",
]


def print_callback(name):
    async def _log_callback(*args, **kwargs):
        logger.debug(f"Callback {name} called with args: {args} and kwargs: {kwargs}")
    return _log_callback


def log_callback(name, cb):
    async def _log_callback(*args, **kwargs):
        logger.debug(f"Calling callback {name} with args: {args} and kwargs: {kwargs}")
        try:
            result = await cb(*args, **kwargs)
        except Exception as e:
            logger.exception(f"Exception in callback {name}")
            raise e
        logger.debug(f"Callback {name} returned {result}")
        return result
    return _log_callback


def fix_callbacks(callbacks):
    if callbacks is None:
        callbacks = dict()
    else:
        callbacks = callbacks.copy()
    # Check all callbacks are known
    for key in callbacks:
        if key not in KNOWN_CALLBACKS:
            raise ValueError(f"Unknown callback: {key}")
    # Add missing callbacks
    for key in KNOWN_CALLBACKS:
        if key not in callbacks:
            callbacks[key] = print_callback(key)
    # Decorate callbacks with logger
    for key in callbacks:
        callbacks[key] = log_callback(key, callbacks[key])
    return callbacks


class OutboundAudioStream:
    def __init__(self, app: "Application", codec_header: str, packet_duration_ms: int):
        self.app = app
        self.codec_header = codec_header
        self.packet_duration_ms = packet_duration_ms
        self.stream_id = None
        self.seq = 0

    async def __aenter__(self):
        self.app._active_outbound_streams += 1
        try:
            self.stream_id = await self.app._send_start(self.codec_header, self.packet_duration_ms)
            return self
        except Exception:
            self.app._active_outbound_streams -= 1
            raise

    async def send(self, opus_bytes: bytes):
        if self.stream_id is None:
            raise RuntimeError("Stream not started")
        await self.app._send_packet(self.stream_id, self.seq, opus_bytes)
        self.seq += 1

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if self.stream_id is not None:
                await self.app._send_stop(self.stream_id)
        finally:
            self.app._active_outbound_streams -= 1


class Application:
    def __init__(
        self,
        token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        channels: Optional[list[str]] = None,
        callbacks: Optional[dict] = None,
        token_loader: Optional[Callable[[], str]] = None,
        token_refresh_interval_s: float = 3000.0,
    ):
        self.username = username
        self.password = password
        if channels is None:
            channels = []
        self.channels = channels
        self.callbacks = fix_callbacks(callbacks)
        self.token_loader = token_loader
        self.token_refresh_interval_s = token_refresh_interval_s
        
        if token_loader is not None:
            self.token = None
        else:
            self.token = token

        self.sequence = 0
        self.streams = dict()
        self.requests = dict()
        self._ws = None
        self._active_outbound_streams = 0
        self._refresh_timer_task = None
        self._is_running = False

    def outbound_stream(self, codec_header: str, packet_duration_ms: int) -> OutboundAudioStream:
        return OutboundAudioStream(self, codec_header, packet_duration_ms)

    async def _send_start(self, codec_header: str, packet_duration_ms: int) -> int:
        if not self._ws or self._ws.closed:
            raise RuntimeError("WebSocket is not connected")
        
        self.sequence += 1
        seq = self.sequence
        fut = asyncio.get_event_loop().create_future()
        self.requests[seq] = fut

        payload = {
            "command": "start_stream",
            "seq": seq,
            "type": "audio",
            "codec": "opus",
            "codec_header": codec_header,
            "packet_duration": packet_duration_ms,
        }
        await self._ws.send_str(json.dumps(payload))

        try:
            response = await asyncio.wait_for(fut, timeout=5.0)
            if "error" in response:
                raise RuntimeError(f"Server error starting stream: {response['error']}")
            return response["stream_id"]
        finally:
            self.requests.pop(seq, None)

    async def _send_packet(self, stream_id: int, seq: int, opus_bytes: bytes):
        if not self._ws or self._ws.closed:
            raise RuntimeError("WebSocket is not connected")
        packet = encode_audio_packet(stream_id, seq, opus_bytes)
        await self._ws.send_bytes(packet)

    async def _send_stop(self, stream_id: int):
        if not self._ws or self._ws.closed:
            return
        
        self.sequence += 1
        seq = self.sequence
        payload = {
            "command": "stop_stream",
            "seq": seq,
            "stream_id": stream_id,
        }
        await self._ws.send_str(json.dumps(payload))

    async def _trigger_soft_reconnect(self):
        logger.info("Triggering soft reconnect for token refresh...")
        if self._ws and not self._ws.closed:
            await self._ws.close()

    async def _refresh_timer_loop(self):
        try:
            while True:
                await asyncio.sleep(self.token_refresh_interval_s)
                # Defer if outbound streams are active
                if self._active_outbound_streams > 0:
                    logger.info("Outbound stream active. Deferring soft reconnect...")
                    start_wait = asyncio.get_event_loop().time()
                    while self._active_outbound_streams > 0:
                        if asyncio.get_event_loop().time() - start_wait >= 30.0:
                            logger.warning("Ceiling hit (+30s). Forcing soft reconnect...")
                            break
                        await asyncio.sleep(0.1)
                
                await self._trigger_soft_reconnect()
        except asyncio.CancelledError:
            pass

    async def run(self):
        self._is_running = True
        
        # Load initial token
        if self.token_loader is not None:
            self.token = self.token_loader()

        # Start refresh timer task
        if self.token_refresh_interval_s > 0 and self.token_loader is not None:
            self._refresh_timer_task = asyncio.create_task(self._refresh_timer_loop())

        backoff = 0.5
        try:
            while self._is_running:
                try:
                    async with aiohttp.ClientSession() as session:
                        logger.info("Connecting to Zello WebSocket...")
                        async with session.ws_connect(ZELLO_WEB_SOCKET_URL) as ws:
                            self._ws = ws
                            backoff = 0.5  # reset backoff on success
                            
                            if self.token_loader is not None:
                                self.token = self.token_loader()

                            await ws.send_str(
                                make_logon_request(self.token, self.username, self.password, self.channels)
                            )

                            async for msg in ws:
                                await self._handle_message(msg)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.exception("Error in WebSocket session")
                    try:
                        await self.callbacks["on_ws_error"](e)
                    except Exception:
                        pass
                finally:
                    self._ws = None
                    try:
                        await self.callbacks["on_ws_closed"](None)
                    except Exception:
                        pass

                if not self._is_running:
                    break

                logger.info(f"Disconnected. Reconnecting in {backoff:.2f} seconds...")
                await asyncio.sleep(backoff)
                backoff = min(60.0, backoff * 2.0)
        finally:
            if self._refresh_timer_task:
                self._refresh_timer_task.cancel()
                self._refresh_timer_task = None

    async def disconnect(self):
        self._is_running = False
        if self._refresh_timer_task:
            self._refresh_timer_task.cancel()
            self._refresh_timer_task = None
        if self._ws and not self._ws.closed:
            await self._ws.close()

    async def _handle_message(self, msg):
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            
            # Route pending request futures
            if "seq" in data and data["seq"] in self.requests:
                fut = self.requests.pop(data["seq"])
                if not fut.done():
                    fut.set_result(data)
                return

            if "error" in data:
                error = data["error"]
                raise get_exception_by_error_code(error)("Server error")

            if "command" in data:
                command = data["command"]
                if command in ["on_channel_status", "on_stream_start", "on_stream_stop", "on_text_message", "on_image", "on_location"]:
                    # Create or clean up stream objects
                    if command == "on_stream_start":
                        codec_header = decode_codec_header(data["codec_header"])
                        sample_rate_hz, frames_per_packet, frame_size_ms = codec_header
                        stream_id = data["stream_id"]
                        stream = IncomingAudioStream(sample_rate_hz, frames_per_packet, frame_size_ms)
                        self.streams[stream_id] = stream
                    elif command == "on_stream_stop":
                        stream_id = data["stream_id"]
                        if stream_id in self.streams:
                            stream = self.streams.pop(stream_id)
                            await stream.put(None)

                    event = convert_to_dataclass(command, data)
                    asyncio.create_task(self.callbacks[command](event))
                else:
                    await self.callbacks["on_unknown_command"](**data)
            else:
                await self.callbacks["on_unknown_message"](**data)
        elif msg.type == aiohttp.WSMsgType.ERROR:
            await self.callbacks["on_ws_error"](msg)
        elif msg.type == aiohttp.WSMsgType.CLOSED:
            await self.callbacks["on_ws_closed"](msg)
        elif msg.type == aiohttp.WSMsgType.BINARY:
            stream_packet, id1, id2, data = decode_stream_packet(msg.data)
            if stream_packet is PacketType.AUDIO:
                if id1 in self.streams:
                    stream = self.streams[id1]
                    await stream.put(data)
            elif stream_packet is PacketType.IMAGE:
                await self.callbacks["on_image"](id1, data)
            else:
                await self.callbacks["on_unknown_binary"](msg.data)
        else:
            await self.callbacks["on_unknown_ws_message"](msg)


if __name__ == "__main__":
    # Standard logger configuration when executed directly
    logging.basicConfig(level=logging.DEBUG)

    async def save_as_wav(event):
        stream = app.streams.get(event.stream_id)
        if not stream:
            return
        logger.info(f"Incoming stream started: {event.stream_id} from {event.sender}")
        with tempfile.NamedTemporaryFile(suffix=".wav") as temp_file:
            with wave.open(temp_file.name, "wb") as file_out:
                file_out.setnchannels(1)
                file_out.setsampwidth(2)
                file_out.setframerate(stream.sample_rate_hz)
                async for pcm in stream.decode():
                    file_out.writeframes(pcm)
            temp_file.flush()
            
            # Use ffmpeg to convert to mp3 and read it on streaming
            process = subprocess.Popen(
                ["ffmpeg", "-i", temp_file.name, "-f", "mp3", "-"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )

            data = aiohttp.FormData()
            data.add_field(
                "file", process.stdout, filename="output.mp3", content_type="audio/mpeg"
            )
            data.add_field("model", "whisper-1")

            result = None
            async with aiohttp.ClientSession() as aiohttp_session:
                async with aiohttp_session.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                    data=data,
                ) as response:
                    result = await response.text()

            process.wait()
            logger.info(f"Transcription result: {result}")
            return result

    issuer = os.environ.get("ZELLO_ISSUER")
    private_key = os.environ.get("ZELLO_PRIVATE_KEY")
    username = os.environ.get("ZELLO_USERNAME")
    password = os.environ.get("ZELLO_PASSWORD")

    if all([issuer, private_key, username, password]):
        ltm = LocalTokenManager(issuer, private_key)
        app = Application(
            token_loader=ltm.issue,
            username=username,
            password=password,
            callbacks={"on_stream_start": save_as_wav},
        )
        asyncio.run(app.run())
    else:
        print("Please set ZELLO_ISSUER, ZELLO_PRIVATE_KEY, ZELLO_USERNAME, and ZELLO_PASSWORD to run test.")
