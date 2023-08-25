import base64
import struct


def encode_codec_header(sample_rate_hz, frames_per_packet, frame_size_ms):
    """
    Encodes the codec header attributes into a base64 string.

    Args:
    - sample_rate_hz (int): Audio sample rate in Hz.
    - frames_per_packet (int): Number of frames per packet (1 or 2).
    - frame_size_ms (int): Audio frame size in milliseconds.

    Returns:
    - str: Base64 encoded string of codec header.
    """
    # Use struct to pack the attributes into a binary format
    packed_data = struct.pack("<HBB", sample_rate_hz, frames_per_packet, frame_size_ms)

    # Convert the binary data into a base64 encoded string
    return base64.b64encode(packed_data).decode()


def decode_codec_header(base64_str):
    """
    Decodes the codec header attributes from a base64 string.

    Args:
    - base64_str (str): Base64 encoded string of codec header.

    Returns:
    - tuple: (sample_rate_hz, frames_per_packet, frame_size_ms).
    """
    # Decode the base64 string into binary data
    packed_data = base64.b64decode(base64_str)

    # Use struct to unpack the binary data into attributes
    sample_rate_hz, frames_per_packet, frame_size_ms = struct.unpack(
        "<HBB", packed_data
    )

    return sample_rate_hz, frames_per_packet, frame_size_ms
