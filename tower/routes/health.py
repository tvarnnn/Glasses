import logging

from fastapi import APIRouter, Request

SERVICE_NAME = "glasses-tower"
API_VERSION = "0.1.0"

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict:
    container = request.app.state.module_container
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": API_VERSION,
        "module_state": container.state.value,
        "module_id": container.descriptor.id,
        "capture": _capture_state(request.app),
    }


def _capture_state(app) -> dict | None:
    """Whether raw imagery is being written, and how much of it.

    06-PRIVACY-DATA.md requires an Explicit Dataset-Recording Session to
    indicate that it is recording. Until this existed that indication was
    a server-side log line, which nobody operating the Tower from another
    machine -- the normal case, over Tailscale -- can see.

    `null` means no recorder is registered at all, which is different from
    a registered recorder that is idle. Collapsing the two would make "we
    are definitely not recording" indistinguishable from "we are armed and
    one stream_start away".

    Never raises. /health is how an operator learns the Tower is unwell;
    it must not itself fail because a subsystem is broken.
    """
    observers = getattr(app.state, "frame_observers", None) or []
    if not observers:
        return None

    try:
        recording = any(observer.is_recording for observer in observers)
        statuses = [
            observer.status
            for observer in observers
            if getattr(observer, "status", None) is not None
        ]
        latest = statuses[-1] if statuses else None
        return {
            "armed": True,
            "recording": recording,
            "capture_id": None if latest is None else latest.capture_id,
            "frames_written": 0 if latest is None else latest.frames_written,
            "bytes_written": 0 if latest is None else latest.bytes_written,
        }
    except Exception:
        logger.exception("[Tower][Health] could not read capture state")
        return {"armed": True, "error": "unavailable"}
