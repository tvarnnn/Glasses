import base64
import binascii
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

REQUIRED_FIELDS = ("seq", "width", "height", "format", "data")
SUPPORTED_FORMAT = "jpeg"


class FrameError(Exception):
    """Raised when a frame message fails validation or decoding."""


def _validate_int(field: str, value: object) -> int:
    """Reject a non-integer sequence field at the wire boundary.

    These fields feed arithmetic in SessionMetrics (gap counting and the
    upstream rate estimates), and one of those callers runs from the WS
    endpoint's `finally` block -- so a stringified integer that slips
    through here fails far away from its cause and takes session cleanup
    with it. A wrong type is a protocol error like any other and belongs
    in an `invalid_frame` reply.

    `bool` is excluded deliberately: it is an int subclass in Python, so
    `"seq": true` would otherwise be accepted as 1.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise FrameError(
            f"frame field {field!r} must be an integer, "
            f"got {type(value).__name__}: {value!r}"
        )
    return value


@dataclass(frozen=True)
class DecodedFrame:
    seq: int
    declared_width: int
    declared_height: int
    decoded_width: int
    decoded_height: int
    byte_count: int
    raw_bytes: bytes
    # Additive protocol prep (07-PLATFORM-CONSTRAINTS.md Limitation 9).
    # source_seq is the DAT/capture frame index -- what `seq` has always
    # been -- and falls back to `seq` for any sender that doesn't send it.
    # tx_seq is a dense per-transmitted-message counter; None means the
    # sender does not provide it, which is NOT the same as zero gaps.
    source_seq: int = 0
    tx_seq: int | None = None

    @property
    def dimensions_match(self) -> bool:
        return (self.declared_width, self.declared_height) == (
            self.decoded_width,
            self.decoded_height,
        )


def parse_and_decode_frame(message: dict) -> DecodedFrame:
    missing = [field for field in REQUIRED_FIELDS if field not in message]
    if missing:
        raise FrameError(f"malformed frame message, missing fields: {missing}")

    seq = _validate_int("seq", message["seq"])
    declared_width = message["width"]
    declared_height = message["height"]
    frame_format = message["format"]
    data = message["data"]

    if frame_format != SUPPORTED_FORMAT:
        raise FrameError(f"frame #{seq} unsupported format: {frame_format!r}")

    try:
        raw_bytes = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise FrameError(f"frame #{seq} invalid base64 payload: {exc}") from exc

    try:
        image = Image.open(io.BytesIO(raw_bytes))
        decoded_width, decoded_height = image.size
    except (UnidentifiedImageError, OSError) as exc:
        raise FrameError(f"frame #{seq} failed to decode JPEG: {exc}") from exc

    # An explicitly-null optional field means "this sender does not
    # provide it", which is the same as omitting it -- not a type error.
    raw_source_seq = message.get("source_seq")
    raw_tx_seq = message.get("tx_seq")

    return DecodedFrame(
        seq=seq,
        declared_width=declared_width,
        declared_height=declared_height,
        decoded_width=decoded_width,
        decoded_height=decoded_height,
        byte_count=len(raw_bytes),
        raw_bytes=raw_bytes,
        source_seq=(
            seq
            if raw_source_seq is None
            else _validate_int("source_seq", raw_source_seq)
        ),
        tx_seq=(
            None if raw_tx_seq is None else _validate_int("tx_seq", raw_tx_seq)
        ),
    )
