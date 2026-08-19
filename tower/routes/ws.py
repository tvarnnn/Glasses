import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from tower.frames import FrameError, parse_and_decode_frame
from tower.metrics import SessionMetrics
from tower.modules.base import ModuleUnavailableError

logger = logging.getLogger(__name__)

router = APIRouter()


async def _handle_frame_message(
    websocket: WebSocket, message: dict, metrics: SessionMetrics | None
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

    module_container = websocket.app.state.module_container
    try:
        result = module_container.process(frame.raw_bytes)
    except ModuleUnavailableError as exc:
        logger.warning(
            "[Tower][Frame] #%s: module unavailable, frame dropped: %s",
            frame.seq,
            exc,
        )
        return

    logger.info(
        "[Tower][Frame] #%s processed: mean_intensity=%.2f",
        frame.seq,
        result.mean_intensity,
    )

    receive_to_result_ms = (time.perf_counter() - receive_start) * 1000
    if metrics is not None:
        metrics.record_frame(
            seq=frame.seq,
            byte_count=frame.byte_count,
            receive_to_result_ms=receive_to_result_ms,
            cv_processing_ms=result.processing_ms,
        )

    try:
        await websocket.send_json(
            {
                "type": "frame_result",
                "seq": frame.seq,
                "mean_intensity": result.mean_intensity,
                "processing_ms": result.processing_ms,
            }
        )
    except WebSocketDisconnect:
        logger.warning(
            "[Tower][Frame] #%s: could not send result, client disconnected mid-frame",
            frame.seq,
        )
        raise

    if metrics is not None and metrics.should_log_summary():
        logger.info("[Tower][Session] summary: %s", metrics.snapshot())


def _finalize_stream_measurement(metrics: SessionMetrics, end_reason: str) -> None:
    logger.info(
        "[Tower][Session] final summary: %s",
        {**metrics.snapshot(), "end_reason": end_reason},
    )


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    session = websocket.app.state.session
    active_measurement: SessionMetrics | None = None
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
                await _handle_frame_message(websocket, message, active_measurement)
            elif message_type == "stream_start":
                if active_measurement is not None:
                    _finalize_stream_measurement(
                        active_measurement, end_reason="superseded_by_stream_start"
                    )
                active_measurement = SessionMetrics()
                logger.info(
                    "[Tower][Session] stream_start: measurement window opened"
                )
            elif message_type == "stream_stop":
                if active_measurement is not None:
                    _finalize_stream_measurement(
                        active_measurement, end_reason="stream_stop"
                    )
                    active_measurement = None
                else:
                    logger.warning(
                        "[Tower][Session] stream_stop received with no active "
                        "measurement window"
                    )
            else:
                logger.warning("received unknown message type: %s", message_type)
    except WebSocketDisconnect:
        logger.info("client disconnected")
    finally:
        if active_measurement is not None:
            _finalize_stream_measurement(active_measurement, end_reason="disconnect")
        session.client_disconnected()
