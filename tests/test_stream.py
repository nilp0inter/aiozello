from hypothesis import given, strategies as st

from aiozello.stream import encode_audio_packet, encode_image_packet, decode_stream_packet, PacketType


@given(stream_id=st.integers(min_value=0, max_value=2**32-1),
       packet_id=st.integers(min_value=0, max_value=2**32-1),
       data=st.binary())
def test_encode_audio_packet_decode_isomorphism(stream_id, packet_id, data):
    encoded = encode_audio_packet(stream_id, packet_id, data)
    packet_type, *decoded = decode_stream_packet(encoded)
    assert packet_type is PacketType.AUDIO
    assert decoded == [stream_id, packet_id, data]


@given(image_id=st.integers(min_value=0, max_value=2**32-1),
       image_type=st.sampled_from([0x01, 0x02]),
       data=st.binary())
def test_encode_image_packet_decode_isomorphism(image_id, image_type, data):
    encoded = encode_image_packet(image_id, image_type, data)
    packet_type, *decoded = decode_stream_packet(encoded)
    assert packet_type is PacketType.IMAGE
    assert decoded == [image_id, image_type, data]
