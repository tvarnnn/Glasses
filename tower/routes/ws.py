import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from tower.frames import FrameError, parse_and_decode_frame
from tower.metrics import SessionMetrics
from tower.modules.base import FrameSkippedError, ModuleUnavailableError

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
        if metrics is not None:
            metrics.record_frame_rejected()
        # seq may legitimately be absent -- a frame message can fail
        # validation before seq is known. Report null rather than
        # inventing one (Rule 3: unknown stays unknown).
        await _send_frame_error(
            websocket, message.get("seq"), "invalid_frame", str(exc)
        )
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

    _record_capture(websocket, frame)

    module_container = websocket.app.state.module_container
    try:
        result = module_container.process(frame.raw_bytes)
    except FrameSkippedError as exc:
        logger.warning(
            "[Tower][Frame] #%s: frame-level failure, module still active: %s",
            frame.seq,
            exc,
        )
        if metrics is not None:
            metrics.record_frame_processing_error()
            metrics.record_frame_rejected()
        await _send_frame_error(websocket, frame.seq, "frame_skipped", str(exc))
        return
    except ModuleUnavailableError as exc:
        logger.warning(
            "[Tower][Frame] #%s: module unavailable, frame dropped: %s",
            frame.seq,
            exc,
        )
        if metrics is not None:
            metrics.record_frame_rejected()
        await _send_frame_error(websocket, frame.seq, "module_unavailable", str(exc))
        return

    logger.info(
        "[Tower][Frame] #%s processed: %s=%.4f",
        frame.seq,
        result.result_label,
        result.result_value,
    )

    receive_to_result_ms = (time.perf_counter() - receive_start) * 1000
    if metrics is not None:
        metrics.record_frame(
            seq=frame.seq,
            byte_count=frame.byte_count,
            receive_to_result_ms=receive_to_result_ms,
            cv_processing_ms=result.processing_ms,
            stage_ms=result.stage_ms,
            tx_seq=frame.tx_seq,
            source_seq=frame.source_seq,
        )

    payload = {
        "type": "frame_result",
        "seq": frame.seq,
        "processing_ms": result.processing_ms,
        "result_value": result.result_value,
        "result_label": result.result_label,
        "stage_ms": result.stage_ms,
    }
    if result.mean_intensity is not None:
        payload["mean_intensity"] = result.mean_intensity

    try:
        await websocket.send_json(payload)
    except WebSocketDisconnect:
        logger.warning(
            "[Tower][Frame] #%s: could not send result, client disconnected mid-frame",
            frame.seq,
        )
        raise

    if metrics is not None and metrics.should_log_summary():
        logger.info("[Tower][Session] summary: %s", metrics.snapshot())


def _record_capture(websocket, frame) -> None:
    """Persist one raw frame if dataset recording is switched on.

    Off by default: `capture_recorder` is None unless an operator started
    a recording, so the normal frame path is byte-for-byte unchanged.

    Deliberately swallows every failure. Recording is a side errand; a
    full disk or a permission error must never cost the client its
    frame_result, and must never take down a session. It is logged and
    the pipeline continues.
    """
    recorder = getattr(websocket.app.state, "capture_recorder", None)
    if recorder is None or not recorder.is_recording:
        return
    try:
        recorder.write_frame(
            frame.raw_bytes,
            source_seq=frame.source_seq,
            wire_seq=frame.seq,
            tx_seq=frame.tx_seq,
            width=frame.decoded_width,
            height=frame.decoded_height,
        )
    except Exception:
        logger.exception(
            "[Tower][Capture] frame #%s not recorded; continuing", frame.seq
        )


async def _send_frame_error(
    websocket: WebSocket, seq: int | None, reason: str, message: str
) -> None:
    try:
        await websocket.send_json(
            {
                "type": "frame_error",
                "seq": seq,
                "reason": reason,
                "message": message,
            }
        )
    except WebSocketDisconnect:
        logger.warning(
            "[Tower][Frame] #%s: could not send frame_error, client disconnected mid-frame",
            seq,
        )
        raise


def _finalize_stream_measurement(metrics: SessionMetrics, end_reason: str) -> None:
    try:
        snapshot = metrics.snapshot()
    except Exception:
        # Deliberately broad, unlike the receive loop's narrow handler:
        # this is a one-shot diagnostics call, and one of its call sites
        # is the endpoint's `finally` block, immediately before
        # session.client_disconnected(). Letting it propagate would skip
        # that cleanup and leave the tracker asserting a client is still
        # connected forever -- a measurement failure must never corrupt
        # connection state (Rule 3) or leak lifecycle (Rule 15). Logged
        # with a traceback rather than swallowed.
        logger.exception(
            "[Tower][Session] could not finalize measurement "
            "(end_reason=%s); connection cleanup continues",
            end_reason,
        )
        return
    logger.info(
        "[Tower][Session] final summary: %s",
        {**snapshot, "end_reason": end_reason},
    )


def _start_capture(websocket) -> None:
    """Bound a dataset recording to the existing stream window.

    Reuses stream_start/stream_stop rather than adding a message type:
    the session boundary already exists on the wire, and V1 deliberately
    makes no protocol change.
    """
    recorder = getattr(websocket.app.state, "capture_recorder", None)
    if recorder is None or recorder.is_recording:
        return
    try:
        capture_id = recorder.start()
        logger.info("[Tower][Capture] recording started: %s", capture_id)
    except Exception:
        logger.exception("[Tower][Capture] could not start recording")


def _stop_capture(websocket) -> None:
    recorder = getattr(websocket.app.state, "capture_recorder", None)
    if recorder is None or not recorder.is_recording:
        return
    try:
        status = recorder.stop()
        logger.info(
            "[Tower][Capture] recording stopped: %s frames, %s bytes",
            status.frames_written,
            status.bytes_written,
        )
    except Exception:
        logger.exception("[Tower][Capture] could not stop recording cleanly")


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    session = websocket.app.state.session
    active_measurement: SessionMetrics | None = None
    await websocket.accept()
    session.client_connected()
    logger.info("client connected")

    try:
        while True:
            try:
                message = await websocket.receive_json()
            except WebSocketDisconnect:
                raise
            except (ValueError, KeyError, UnicodeDecodeError) as exc:
                # Payload-level failures only: JSONDecodeError subclasses
                # ValueError, and a binary frame makes Starlette's
                # message["text"] raise KeyError. Deliberately NOT a bare
                # `except Exception` -- Starlette raises RuntimeError for
                # invalid *state* (socket not connected / already
                # disconnected) from a synchronous check with no await
                # point, so swallowing it and continuing would spin this
                # loop at full CPU with nothing able to cancel it
                # (Rule 15: no tight retry loops). State errors must
                # propagate and end the connection.
                logger.warning("received malformed WS message, ignoring: %s", exc)
                continue

            if not isinstance(message, dict):
                logger.warning(
                    "received malformed WS message, ignoring: not a JSON object: %.200r",
                    message,
                )
                continue

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
                _start_capture(websocket)
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
                _stop_capture(websocket)
            else:
                logger.warning("received unknown message type: %s", message_type)
    except WebSocketDisconnect:
        logger.info("client disconnected")
    finally:
        if active_measurement is not None:
            _finalize_stream_measurement(active_measurement, end_reason="disconnect")
        session.client_disconnected()
