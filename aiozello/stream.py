from enum import Enum, auto
import asyncio
import struct

import opuslib


# Define the Enum for Packet Types
class PacketType(Enum):
    AUDIO = auto()
    IMAGE = auto()


# Constants for the packet types
STREAM_AUDIO = 0x01
STREAM_IMAGE = 0x02

# Constants for the image types
IMAGE_THUMBNAIL = 0x02
IMAGE_FULL = 0x01


def encode_audio_packet(stream_id, packet_id, data):
    """
    Encodes the audio streaming packet.
    """
    header = struct.pack("!BLL", STREAM_AUDIO, stream_id, packet_id)
    return header + data


def encode_image_packet(image_id, image_type, data):
    """
    Encodes the image packet (either thumbnail or full image).
    """
    header = struct.pack("!BLL", STREAM_IMAGE, image_id, image_type)
    return header + data


def decode_stream_packet(packet):
    """
    Decodes the stream packet (either audio or image).
    """
    header = packet[:9]
    data = packet[9:]

    packet_type, id1, id2 = struct.unpack("!BLL", header)

    if packet_type == STREAM_AUDIO:
        return PacketType.AUDIO, id1, id2, data
    elif packet_type == STREAM_IMAGE:
        return PacketType.IMAGE, id1, id2, data
    else:
        raise ValueError("Invalid packet type")


class IncomingAudioStream:
    """
    Represents an incoming audio stream.

    """

    def __init__(self, sample_rate_hz, frames_per_packet, frame_size_ms):
        self.sample_rate_hz = sample_rate_hz
        self.frames_per_packet = frames_per_packet
        self.frame_size_ms = frame_size_ms
        self.incoming = asyncio.Queue()

    async def decode(self):
        decoder = opuslib.Decoder(self.sample_rate_hz, 1)
        frame_size = (
            self.sample_rate_hz // 1000 * self.frame_size_ms
        ) * self.frames_per_packet
        while True:
            packet = await self.incoming.get()
            if packet is None:
                break
            yield decoder.decode(packet, frame_size)

    async def drain(self):
        while True:
            if (await self.incoming.get()) is None:
                return
