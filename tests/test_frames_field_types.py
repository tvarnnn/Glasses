"""Sequence fields must be validated as integers at the wire boundary.

`parse_and_decode_frame` historically validated field *presence* only, so
a sender emitting `"seq": "31"` (JSON encoders do sometimes stringify
integers) produced a DecodedFrame carrying a string. That stayed harmless
only while nothing did arithmetic on it. Once SessionMetrics began
deriving rate estimates from `source_seq`, the type error surfaced deep
inside `snapshot()` -- which runs from the endpoint's `finally` block, so
it took the session's final summary and its connection-state cleanup down
with it.

Validate at the boundary instead: a bad type is a protocol error and
belongs in a `frame_error`/`invalid_frame` reply, exactly like a bad
base64 payload.
"""
import base64
import io

import pytest
from PIL import Image

from tower.frames import FrameError, parse_and_decode_frame


def _jpeg_base64(width: int = 8, height: int = 8) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(10, 20, 30)).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _message(**overrides) -> dict:
    message = {
        "type": "frame",
        "seq": 1,
        "width": 8,
        "height": 8,
        "format": "jpeg",
        "data": _jpeg_base64(),
    }
    message.update(overrides)
    return message


@pytest.mark.parametrize("bad_value", ["31", 31.5, None, [], {}])
def test_non_integer_seq_is_rejected(bad_value):
    with pytest.raises(FrameError, match="seq"):
        parse_and_decode_frame(_message(seq=bad_value))


@pytest.mark.parametrize("bad_value", ["31", 31.5, [], {}])
def test_non_integer_source_seq_is_rejected(bad_value):
    with pytest.raises(FrameError, match="source_seq"):
        parse_and_decode_frame(_message(source_seq=bad_value))


@pytest.mark.parametrize("bad_value", ["2", 2.5, [], {}])
def test_non_integer_tx_seq_is_rejected(bad_value):
    with pytest.raises(FrameError, match="tx_seq"):
        parse_and_decode_frame(_message(tx_seq=bad_value))


def test_explicit_null_optional_fields_fall_back_to_defaults():
    """A sender that emits the keys with JSON null must be treated as a
    sender that omitted them, not as a type error -- `null` is how "I do
    not provide this" is spelled on the wire.
    """
    frame = parse_and_decode_frame(_message(seq=7, source_seq=None, tx_seq=None))

    assert frame.source_seq == 7
    assert frame.tx_seq is None


def test_valid_integer_fields_still_parse():
    frame = parse_and_decode_frame(_message(seq=30, source_seq=900, tx_seq=30))

    assert (frame.seq, frame.source_seq, frame.tx_seq) == (30, 900, 30)


def test_booleans_are_not_accepted_as_sequence_numbers():
    """bool is an int subclass in Python; `"seq": true` is still nonsense."""
    with pytest.raises(FrameError, match="seq"):
        parse_and_decode_frame(_message(seq=True))
