from pprint import pprint
import subprocess
import json
import os
import tempfile
import wave

import aiohttp
import asyncio

from aiozello.auth import LocalTokenManager
from aiozello.error import get_exception_by_error_code
from aiozello.codec import decode_codec_header
from aiozello.stream import PacketType, decode_stream_packet, IncomingAudioStream


ZELLO_WEB_SOCKET_URL = "wss://zello.io/ws"


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

        aiohttp_session = aiohttp.ClientSession()
        data = aiohttp.FormData()
        data.add_field(
            "file", process.stdout, filename="output.mp3", content_type="audio/mpeg"
        )
        data.add_field("model", "whisper-1")

        async with aiohttp_session.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            data=data,
        ) as response:
            print(await response.text())

        process.wait()


streams = dict()


async def main(token, username, password):
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ZELLO_WEB_SOCKET_URL) as ws:
            logon_request = make_logon_request(token, username, password, ["aiozello"])
            await ws.send_str(logon_request)
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if "error" in data:
                        error = data["error"]
                        print(error)
                        raise get_exception_by_error_code(error)("Server error")
                    elif "command" in data:
                        command = data["command"]
                        if command == "on_channel_status":
                            print("on_channel_status")
                            pprint(data)
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
                            streams[stream_id] = stream
                            asyncio.create_task(save_as_wav(stream_id, stream))
                            print("on_stream_start")
                        elif command == "on_stream_stop":
                            print("on_stream_stop")
                            stream = streams.pop(data["stream_id"])
                            await stream.incoming.put(None)
                        elif command == "on_image":
                            print("on_image")
                        else:
                            print(f"Unknown command: {command}")
                            pprint(data)
                    else:
                        pprint(data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print("ws connection closed with exception %s" % ws.exception())
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    print("ws connection closed")
                    break
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    print("ws connection received binary message")
                    stream_packet, id1, id2, data = decode_stream_packet(msg.data)
                    if stream_packet is PacketType.AUDIO:
                        print("Decoding audio")
                        stream = streams[id1]
                        await stream.incoming.put(data)
                    else:
                        pprint(stream_packet)
                        pprint(id1)
                        pprint(id2)
                else:
                    print("ws connection received unknown message")


issuer = os.environ["ZELLO_ISSUER"]
private_key = os.environ["ZELLO_PRIVATE_KEY"]
username = os.environ["ZELLO_USERNAME"]
password = os.environ["ZELLO_PASSWORD"]

ltm = LocalTokenManager(issuer, private_key)
asyncio.run(main(ltm.issue(), username, password))
