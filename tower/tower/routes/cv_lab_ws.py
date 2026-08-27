"""The CV Lab control plane, on the WebSocket.

Kept out of `ws.py` for the same reason `results_ws.py` is: that module
owns the frame path -- the latency-measured, privacy-sensitive part of
this system -- and a control surface must be able to fail without
implicating it. `ws.py` gains one dispatch branch rather than two hundred
lines.

**Every handler here returns without raising.** A malformed start, an
unknown experiment, a hostile payload: all become a `cv_lab_error` on the
wire. The receive loop must never learn that a control message had a
problem, because the receive loop is what answers frames.

**Two message types out, and only two.** `cv_lab_status` is the whole
truth -- catalog, lifecycle, run and source, in one document -- and every
accepted command replies with it. `cv_lab_error` is a refusal, and it
carries the same document, unchanged, so that a client which is refused
never has to guess what state it is now in. There is no "accepted"
message with no state in it, because a client that got one would still
have to ask.

**Commands do not travel on the result channel.** `tower/results/` is a
read-only reporting surface and its own header says so; putting a
mutation on it would make the next cartridge's producer a place where
somebody looks for one. The status DOCUMENT is published there, and only
the document.
"""

import logging

from tower.cv_lab.contracts import (
    CONTROL_CONTRACT,
    ERR_LAB_UNAVAILABLE,
    ERR_MALFORMED,
    STATUS_CONTRACT,
)

logger = logging.getLogger(__name__)

# Client -> Tower
MSG_STATUS = "cv_lab_status"
MSG_START = "cv_lab_start"
MSG_PAUSE = "cv_lab_pause"
MSG_RESUME = "cv_lab_resume"
MSG_STOP = "cv_lab_stop"

CV_LAB_MESSAGE_TYPES = frozenset(
    {MSG_STATUS, MSG_START, MSG_PAUSE, MSG_RESUME, MSG_STOP}
)

# Tower -> client. `cv_lab_status` is both a request and a reply, the same
# way `cartridges` is on the result channel: one name for one document,
# whichever direction it is travelling.
MSG_ERROR = "cv_lab_error"


async def handle(message: dict, *, websocket, sender) -> None:
    """Dispatch one control message. Never raises."""
    message_type = message.get("type")
    try:
        lab = getattr(websocket.app.state, "cv_lab", None)
        if lab is None:
            # An app built without a Lab. Every test in this repository
            # that constructs one by hand is such an app, and the honest
            # answer is a refusal rather than an AttributeError that ends
            # a connection which is otherwise answering frames.
            await _error(
                sender,
                ERR_LAB_UNAVAILABLE,
                "this Tower runs no CV Lab",
                command=message_type,
                request_id=_request_id(message),
            )
            return

        if message_type == MSG_STATUS:
            await sender.send(_status_payload(lab.status(), _request_id(message)))
            return

        if message_type == MSG_START:
            outcome = lab.start(message.get("experiment_id"))
        elif message_type == MSG_PAUSE:
            outcome = lab.pause(message.get("run_id"))
        elif message_type == MSG_RESUME:
            outcome = lab.resume(message.get("run_id"))
        elif message_type == MSG_STOP:
            outcome = lab.stop(message.get("run_id"))
        else:
            return

        request_id = _request_id(message)
        if outcome.accepted:
            payload = _status_payload(outcome.status, request_id)
            # Which command produced this document. Only present on a
            # reply to a command, so a pushed status is distinguishable
            # from an answer to something this client asked for.
            payload["accepted_command"] = message_type
            await sender.send(payload)
            return

        await _error(
            sender,
            outcome.reason,
            outcome.message,
            command=message_type,
            request_id=request_id,
            status=outcome.status,
            **outcome.extra,
        )
    except Exception:
        # Deliberately broad, and deliberately swallowed after logging.
        # This handler is called from the frame-serving receive loop; an
        # escape here would end a connection that is successfully
        # answering frames because somebody sent a bad start request.
        logger.exception(
            "[Tower][CVLab] handler failed for %r; the connection continues",
            message_type,
        )


def _status_payload(status: dict, request_id) -> dict:
    payload = {
        "type": MSG_STATUS,
        # The control vocabulary's own identifier, distinct from the
        # status document's. A client may implement the read-only half and
        # never send a command -- which is exactly what a Release iOS
        # build with no camera should do -- and the two halves version
        # independently for that reason.
        "control_contract": CONTROL_CONTRACT,
        "contract": STATUS_CONTRACT,
        "status": status,
    }
    if request_id is not None:
        payload["request_id"] = request_id
    return payload


async def _error(sender, reason, message, **extra) -> None:
    payload = {
        "type": MSG_ERROR,
        "control_contract": CONTROL_CONTRACT,
        "reason": reason,
        "message": message,
    }
    for key, value in extra.items():
        if value is not None:
            payload[key] = value
    await sender.send(payload)


def _request_id(message: dict):
    """An opaque token echoed back, or nothing.

    Optional on purpose. A client that sends no `request_id` still gets a
    complete reply, because the reply is the whole status document and
    carries everything needed to act on it. A client that sends one can
    match a reply to the button that was pressed, which matters when two
    commands are in flight and one of them is refused.

    Validated as a short string and dropped otherwise: it is echoed onto
    the wire, and a remote party must not be able to put an arbitrary
    object there.
    """
    request_id = message.get("request_id")
    if isinstance(request_id, str) and 0 < len(request_id) <= 64:
        return request_id
    return None


def malformed_message(message_type: str) -> dict:
    """The refusal for a control message that is not a JSON object.

    Exposed for `ws.py`, which validates the envelope before this module
    sees it and must be able to answer with this module's vocabulary
    rather than inventing a second one.
    """
    return {
        "type": MSG_ERROR,
        "control_contract": CONTROL_CONTRACT,
        "reason": ERR_MALFORMED,
        "message": "a CV Lab message must be a JSON object",
        "command": message_type,
    }
