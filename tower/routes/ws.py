import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from tower.frame_processing import process_frame
from tower.frames import FrameError, parse_and_decode_frame
from tower.metrics import SessionMetrics

logger = logging.getLogger(__name__)

router = APIRouter()


async def _handle_frame_message(
    websocket: WebSocket, message: dict, metrics: SessionMetrics
) -> None:
    receive_start = time.perf_counter()
    try:
        frame = parse_and_decode_frame(message)
    except FrameError as exc:
        logger.warning("%s", exc)
        return

    logger.info("[Tower][Frame] #%s received: %s bytes", frame.seq, frame.byte_count)
    logger.info(
        "[Tower][Frame] #%s decoded: %sx%s",
        frame.seq,
        frame.decoded_width,
        frame.decoded_height,
    )

    if frame.dimensions_match:
        logger.info("[Tower][Frame] #%s verified", frame.seq)
    else:
        logger.warning(
            "[Tower][Frame] #%s dimension mismatch: declared %sx%s, decoded %sx%s",
            frame.seq,
            frame.declared_width,
            frame.declared_height,
            frame.decoded_width,
            frame.decoded_height,
        )

    result = process_frame(frame.raw_bytes)
    logger.info(
        "[Tower][Frame] #%s processed: mean_intensity=%.2f",
        frame.seq,
        result.mean_intensity,
    )

    receive_to_result_ms = (time.perf_counter() - receive_start) * 1000
    metrics.record_frame(
        seq=frame.seq,
        byte_count=frame.byte_count,
        receive_to_result_ms=receive_to_result_ms,
        cv_processing_ms=result.processing_ms,
    )

    await websocket.send_json(
        {
            "type": "frame_result",
            "seq": frame.seq,
            "mean_intensity": result.mean_intensity,
            "processing_ms": result.processing_ms,
        }
    )

    if metrics.should_log_summary():
        logger.info("[Tower][Session] summary: %s", metrics.snapshot())


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    session = websocket.app.state.session
    metrics = SessionMetrics()
    await websocket.accept()
    session.client_connected()
    logger.info("client connected")

    try:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")

            if message_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif message_type == "frame":
                await _handle_frame_message(websocket, message, metrics)
            else:
                logger.warning("received unknown message type: %s", message_type)
    except WebSocketDisconnect:
        logger.info("client disconnected")
    finally:
        logger.info("[Tower][Session] final summary: %s", metrics.snapshot())
        session.client_disconnected()
