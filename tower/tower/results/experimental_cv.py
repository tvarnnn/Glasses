"""The CV Lab's status, as a result-channel `Snapshot`.

Thin on purpose. `CVLab.status()` already builds the one document every
CV Lab surface serves -- `GET /cv-lab`, the socket's `cv_lab_status`
reply, and this -- and a producer that reshaped it here would create a
third version of the truth that only the result channel ever sees.

**This is the first producer in this package that reads LIVE state rather
than files.** The package header says the channel is "a read-only
reporting surface over state other processes have already persisted", and
that sentence is now half right: it is still read-only, still writes
nothing, still runs no cartridge and still touches no frame. What changed
is where the state lives. World Builder's producer reads a directory
another process wrote; this one reads an object in this process that the
frame path mutates. The distinction that matters is not disk-versus-
memory, it is that neither producer can alter what it reports --
`test_the_result_channel_never_writes` and
`test_the_module_container_is_untouched_by_a_subscription` are the two
gates on that, and both still hold.

The concurrency this introduces is real and is handled where the state
is, not here: `ResultHub.poll_once` computes snapshots with
`asyncio.to_thread`, so `status()` runs on a worker thread while the
event loop is mutating the Lab. `CVLab` takes a lock around every state
transition and around building the document. This module inherits that
and adds nothing of its own.

`revision` is derived from the payload rather than counted, so it cannot
drift from the content. There are no volatile paths to exclude: unlike a
World Builder status, where elapsed mapping seconds advance with nothing
having happened, every figure that moves here moves because a frame was
processed. A CV Lab whose revision changes twice a second is a CV Lab
that measured something twice a second.
"""

from tower.results.envelope import Snapshot, compute_revision


class ExperimentalCVStatusProducer:
    """Turns the Lab's own document into a channel snapshot.

    Holds the Lab, not a copy of anything it says. A cached payload would
    be a second answer to "what is the Lab doing", and the first thing
    that goes wrong with two answers is that one of them is older.
    """

    def __init__(self, lab) -> None:
        self._lab = lab

    def snapshot(self) -> Snapshot:
        payload = self._lab.status()
        return Snapshot(payload=payload, revision=compute_revision(payload))


def unavailable_payload(reason: str) -> dict:
    """What the channel says when this Tower has no Lab at all.

    Shaped like a status document with everything hollow rather than as a
    bare error, so a client decodes one thing whichever it gets. The
    lifecycle state is `unavailable`, which iOS renders as "the Tower
    cannot do this" rather than as "wait a moment" -- a different
    instruction to a person, and the right one.
    """
    return {
        "contract": None,
        "control_contract": None,
        "frame_result_contract": None,
        "tower_instance_id": None,
        "time_basis": None,
        "lifecycle": {
            "state": "unavailable",
            "reason": reason,
            "since": None,
            "run_id": None,
        },
        "available": [],
        "selected": None,
        "default_experiment": None,
        "device_requested": None,
        "run": None,
        "source": {
            "clients_connected": None,
            "receiving_frames": False,
            "last_frame_at": None,
            "frames_offered_total": 0,
            "idle_after_s": None,
        },
    }
