import base64
import binascii
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

REQUIRED_FIELDS = ("seq", "width", "height", "format", "data")
SUPPORTED_FORMAT = "jpeg"


class FrameError(Exception):
    """Raised when a frame message fails validation or decoding."""


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

    seq = message["seq"]
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

    return DecodedFrame(
        seq=seq,
        declared_width=declared_width,
        declared_height=declared_height,
        decoded_width=decoded_width,
        decoded_height=decoded_height,
        byte_count=len(raw_bytes),
        raw_bytes=raw_bytes,
        source_seq=message.get("source_seq", seq),
        tx_seq=message.get("tx_seq"),
    )
