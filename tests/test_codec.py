from hypothesis import given
import hypothesis.strategies as st

from aiozello.codec import encode_codec_header, decode_codec_header


def test_codec_header_encode_decode_golden():
    encoded = encode_codec_header(16000, 1, 60)
    assert encoded == "gD4BPA=="

    decoded = decode_codec_header(encoded)
    assert decoded == (16000, 1, 60)


@given(
    sample_rate_hz=st.integers(min_value=0, max_value=2**16 - 1),
    frames_per_packet=st.one_of(st.just(1), st.just(2)),
    frame_size_ms=st.integers(min_value=0, max_value=2**8 - 1),
)
def test_codec_header_encode_decode_isomorphism(
    sample_rate_hz, frames_per_packet, frame_size_ms
):
    encoded = encode_codec_header(sample_rate_hz, frames_per_packet, frame_size_ms)
    decoded = decode_codec_header(encoded)
    assert decoded == (sample_rate_hz, frames_per_packet, frame_size_ms)
