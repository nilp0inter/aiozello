import subprocess
import json
import os
import tempfile
import wave
import logging

import aiohttp
import asyncio

from aiozello.auth import LocalTokenManager
from aiozello.error import get_exception_by_error_code
from aiozello.codec import decode_codec_header
from aiozello.stream import PacketType, decode_stream_packet, IncomingAudioStream


ZELLO_WEB_SOCKET_URL = "wss://zello.io/ws"

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(logging.StreamHandler())

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


decoder = None
file_out = None
frame_size = None
frames_packet = None


async def save_as_wav(stream_id, stream):
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
        return result


KNOWN_CALLBACKS = ["on_channel_status", "on_stream", "on_image", "on_unknown_command", "on_unknown_message", "on_ws_error", "on_ws_closed", "on_unknown_binary", "on_unknown_ws_message"]


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


class Application:
    def __init__(self, token, username, password, channels = None, callbacks=None):
        self.token = token
        self.username = username
        self.password = password
        if channels is None:
            channels = []
        self.channels = channels
        self.callbacks = fix_callbacks(callbacks)
        self.sequence = 0
        self.streams = dict()
        self.requests = dict()

    async def run(self):
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ZELLO_WEB_SOCKET_URL) as ws:
                await ws.send_str(make_logon_request(self.token, self.username, self.password, ["aiozello"]))
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if "error" in data:
                            error = data["error"]
                            # TODO: route error to the right callback
                            raise get_exception_by_error_code(error)("Server error")
                        elif "command" in data:
                            command = data["command"]
                            if command == "on_channel_status":
                                await self.callbacks["on_channel_status"](**data)
                            elif command == "on_stream_start":
                                codec_header = decode_codec_header(data["codec_header"])
                                (
                                    sample_rate_hz,
                                    frames_per_packet,
                                    frame_size_ms,
                                ) = codec_header
                                stream_id = data["stream_id"]
                                stream = IncomingAudioStream(
                                    sample_rate_hz, frames_per_packet, frame_size_ms
                                )
                                self.streams[stream_id] = stream
                                asyncio.create_task(self.callbacks["on_stream"](stream_id, stream))
                            elif command == "on_stream_stop":
                                stream = self.streams.pop(data["stream_id"])
                                await stream.incoming.put(None)
                            elif command == "on_image":
                                await self.callbacks["on_image"](**data)
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
                            stream = self.streams[id1]
                            await stream.incoming.put(data)
                        elif stream_packet is PacketType.IMAGE:
                            await self.callbacks["on_image"](id1, data)
                        else:
                            await self.callbacks["on_unknown_binary"](**data)
                    else:
                        await self.callbacks["on_unknown_ws_message"](msg)


issuer = os.environ["ZELLO_ISSUER"]
private_key = os.environ["ZELLO_PRIVATE_KEY"]
username = os.environ["ZELLO_USERNAME"]
password = os.environ["ZELLO_PASSWORD"]

ltm = LocalTokenManager(issuer, private_key)
app = Application(ltm.issue(), username, password, callbacks={"on_stream": save_as_wav})
asyncio.run(app.run())
