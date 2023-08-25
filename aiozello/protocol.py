from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ChannelStatus:
    """
    Represents a change in channel status, which may include channel being
    connected/disconnected, number of online users changed, or supported
    features changed.

    """

    channel: str
    status: str
    users_online: int
    images_supported: bool
    texting_supported: bool
    locations_supported: bool
    error: Optional[str] = field(default=None)
    error_type: Optional[str] = field(default=None)


@dataclass(frozen=True)
class StreamStart:
    type: str
    codec: str
    packet_duration: int
    stream_id: int
    channel: str
    from_: str
    key: str
    codec_header: str


@dataclass(frozen=True)
class StreamStop:
    stream_id: int


@dataclass(frozen=True)
class Image:
    channel: str
    from_: str
    message_id: str
    source: str
    type: str


@dataclass(frozen=True)
class Location:
    channel: str
    from_: str
    message_id: int
    latitude: float
    longitude: float
    accuracy: float
    formatted_address: str


@dataclass(frozen=True)
class TextMessage:
    channel: str
    from_: str
    message_id: int
    text: str
