"""Run worker processes for the lifetime of a capture, and reap them.

This is the piece whose absence made the first physical World Builder
test (2026-08-24) require a second terminal, a directory listing, and a
copied UUID. The Tower recorded ten captures that evening and a human
attached a follower to one of them by hand. The other nine were never
read by anything, so the wearer walked for five minutes with the camera
reporting LIVE and the world frozen at the figures from the first two.

It happened a second time, to a different cartridge, on 2026-08-26: a
real Ray-Ban walk produced 2,203 frames and 64 remembered observations,
and every one of them existed because a human found the capture
directory and started a producer against it in another terminal. The
supervisor could not have done it, because it ran exactly ONE spec and
that slot was taken.

**One spec was never the design; it was the number of specs that
existed.** A supervisor is now given a LIST, each entry named, each
optionally GATED by a predicate the wiring point supplies. The list is
still argv and strings.

**This module is deliberately cartridge-blind.** It knows how to run an
argv when a capture opens, how to stop one on request, and how to reap.
It does not know what any worker computes, and it names no cartridge --
which is what lets `test_the_capture_worker_supervisor_is_cartridge_blind`
stay green without an exemption. The argv and the gate both come from
`main.py`, the wiring point, as plain strings and a plain callable.

**The web process still does not build, and does not remember.** It
supervises children that do. That separation is the reason a rebuild can
take seconds without the frame path noticing, and it is the architecture
decision `docs/agent-handoffs/WORLD-BUILDER.md` section 1 exists to
protect.
"""

import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# How long a worker gets to finish on its own at shutdown before it is
# terminated. A follower whose capture has closed is usually inside its
# final build, and that build is what releases the writer lock -- kill it
# and the result channel correctly, but needlessly, reports the world
# `failed` with a pid that no longer exists.
DEFAULT_GRACE_SECONDS = 10.0

# How long a TERMINATED worker gets to actually die before it is treated
# as un-killable. Distinct from the grace above, which is how long a
# worker gets to finish on its own BEFORE being terminated: this one is
# waiting on a process that has already been shot, and on Windows that
# wait is real -- `TerminateProcess` is asynchronous and a `poll()`
# straight afterwards routinely still returns None.
TERMINATE_TIMEOUT_SECONDS = 2.0

PLACEHOLDER_CAPTURE_DIR = "{capture_dir}"
PLACEHOLDER_CAPTURE_ID = "{capture_id}"
# Substituted with one of the two values below. A worker whose argv does
# not mention it is unaffected; a worker whose argv does gets told
# something it cannot work out for itself.
PLACEHOLDER_ATTACH_MODE = "{attach_mode}"

# A worker started at the moment the capture opened. Every frame the
# capture will ever hold is still ahead of it.
ATTACH_MODE_FROM_START = "from-start"
# A worker started against a capture that was ALREADY RUNNING. Whatever
# is already in the journal happened before this worker was asked for,
# and a worker that decides on its own to go back and read it is making a
# consent decision it has no standing to make.
ATTACH_MODE_FROM_NOW = "from-now"


@dataclass(frozen=True)
class WorkerSpec:
    """What to run, once per capture lineage.

    `argv` may contain `{capture_dir}`, `{capture_id}` and
    `{attach_mode}`, substituted per capture. Substitution is positional
    over the argv LIST, never over a joined string: a capture root chosen
    by an operator can contain spaces, and building a command line by
    concatenation is how that becomes a quoting bug on Windows.
    """

    argv: tuple[str, ...]
    cwd: str | None = None
    name: str = "capture-worker"
    # Whether the child writes into this process's stdout and stderr.
    #
    # True by default, and that default is the point. A worker sent to
    # DEVNULL is a worker whose failure is invisible: the operator sees a
    # world that is not growing and has nothing to read. Interleaving is
    # the lesser problem, and small in practice -- the world builder logs
    # once at session start, once per rebuild, and once at the end.
    inherit_output: bool = True
    # Asked at every capture open: may this spec run right now?
    #
    # None means "always", which is what every spec meant before gates
    # existed. A predicate rather than a flag because the answer CHANGES
    # while the Tower is up -- a wearer starting or pausing a cartridge
    # between two captures must not need a restart to be obeyed -- and a
    # predicate rather than a state machine in here because whose
    # question it is belongs at the wiring point, not in the supervisor.
    gate: object = None


@dataclass
class _Worker:
    capture_id: str
    process: object
    argv: tuple[str, ...]
    started_at: float
    # Every capture id this worker is following, in order. The follower
    # chains into successors on its own, so one worker legitimately owns
    # a whole lineage.
    lineage: list[str] = field(default_factory=list)

    def is_alive(self) -> bool:
        return self.process.poll() is None


class _SpecRegistry:
    """One spec's workers, and which lineage each of them owns.

    Per spec, not shared, and that separation is the whole reason two
    cartridges can follow one capture safely. A shared table keyed by
    lineage alone would let the first spec's worker answer "yes, this
    lineage is followed" on behalf of a second spec whose worker had
    died -- and the second cartridge would then silently record nothing
    for the rest of the walk, which is the exact failure the supervisor
    exists to prevent.
    """

    __slots__ = ("spec", "workers", "roots")

    def __init__(self, spec: WorkerSpec) -> None:
        self.spec = spec
        # lineage root capture id -> worker
        self.workers: dict[str, _Worker] = {}
        # any capture id -> the lineage root that owns it
        self.roots: dict[str, str] = {}

    def owner_of(self, capture_id: str) -> _Worker | None:
        root = self.roots.get(capture_id)
        return self.workers.get(root) if root is not None else None

    def forget(self, root: str) -> None:
        worker = self.workers.pop(root, None)
        if worker is None:
            return
        for capture_id in worker.lineage:
            if self.roots.get(capture_id) == root:
                del self.roots[capture_id]


class CaptureWorkerSupervisor:
    """One worker per capture LINEAGE, per spec.

    The lineage distinction is the older half of the design.
    `CaptureFollower` already follows a capture across a reconnect:
    seeing a capture close by disconnect it waits out
    `RESUME_GRACE_SECONDS` for a successor whose manifest names it, and
    continues into that one. So a successor capture already has a reader.
    Starting a second worker for it would put two followers, two mapping
    sessions and two writer locks on one walk -- and the result channel,
    which prefers "a LIVE world if one exists", would then have two live
    worlds to choose between and would pick by `updated_at`.

    Lineage is decided by the WRITER and written into the manifest
    (`CaptureRecorder.resumable_capture`). This class only reads the
    `continues` value it is handed; it never guesses which capture
    continues which.

    The per-spec half is newer. Specs are addressed BY NAME -- `attach`
    and `detach` take one -- so names must be unique, and the constructor
    refuses a duplicate rather than letting one cartridge's Pause stop
    another cartridge's producer.

    SERIALISED. `capture_opened` runs on the event loop, from the
    connection that just received `stream_start`; `attach` and `detach`
    run in FastAPI's threadpool, from a session control request. Those
    are genuinely concurrent, and unserialised they raced: a Start
    pressed as a capture opened ran the "is anything already following
    this lineage" check twice, both times seeing nothing, and spawned two
    producers on one capture. The second overwrote the first in the
    registry, so the orphan was invisible to `reap`, `detach`,
    `shutdown` and `/health` -- and two producers appending to one JSONL
    store lose each other's writes, because `update_sighting` rewrites
    the whole file. A reviewer reproduced both the lost write and a
    duplicate record with a colliding `observation_id`.

    Re-entrant, because `capture_opened` and `attach` both call `reap`.
    """

    def __init__(self, specs=None, *, spawn=None, clock=time.monotonic):
        # A bare spec is still a legal argument. Every call site that
        # existed before this class grew a list passes one, and the
        # single-spec Tower is not a legacy shape to be migrated away
        # from -- it is what a Tower running one cartridge looks like.
        if specs is None:
            specs = ()
        elif isinstance(specs, WorkerSpec):
            specs = (specs,)
        else:
            specs = tuple(specs)

        names = [spec.name for spec in specs]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(
                "worker spec names must be unique; `attach` and `detach` "
                f"address a spec by name. Duplicated: {duplicates}"
            )

        self._spawn = spawn if spawn is not None else subprocess.Popen
        self._clock = clock
        # Re-entrant: `capture_opened` and `attach` both call `reap`, and
        # `shutdown` and `detach` both call `_stop_worker`.
        self._lock = threading.RLock()
        self._registries: dict[str, _SpecRegistry] = {
            spec.name: _SpecRegistry(spec) for spec in specs
        }

    @property
    def enabled(self) -> bool:
        """Whether anything will be started at all.

        Reported rather than inferred: "no worker is configured" and "a
        worker is configured and failed" call for opposite responses from
        whoever is reading /health.
        """
        return bool(self._registries)

    def spec_for(self, name: str) -> WorkerSpec | None:
        """The spec registered under a name, or None.

        Public because a wiring test has to be able to assert what the
        Tower will actually run -- which flags, which root, which
        cadence -- and the alternative it used before this existed was
        reaching into a private attribute. That worked while there was
        exactly one spec and stopped compiling the moment there were two,
        which is the usual way a private attribute charges for its use.
        """
        registry = self._registries.get(name)
        return registry.spec if registry is not None else None

    def worker_names(self) -> tuple[str, ...]:
        """Every spec this supervisor could ever start, gated or not.

        The gate decides whether a worker runs; this says whether the
        Tower knows how to run one at all. `/health` needs both, and a
        reader that only had the running list could not tell "configured
        and paused" from "not configured".
        """
        return tuple(self._registries)

    # -- lifecycle ----------------------------------------------------

    def capture_opened(self, capture_id: str, capture_dir, *, continues=None) -> None:
        """A recording has started. Attach every gated-open spec to it."""
        if not self._registries:
            return

        with self._lock:
            self.reap()

            for registry in self._registries.values():
                if not self._gate_open(registry.spec):
                    continue
                self._attach_to_registry(
                    registry,
                    capture_id,
                    capture_dir,
                    continues=continues,
                    attach_mode=ATTACH_MODE_FROM_START,
                )

    def attach(self, name: str, capture_id: str, capture_dir) -> bool:
        """Start ONE named spec against a capture that is already open.

        The gate is deliberately not consulted. `capture_opened` asks
        "should this be running", which is a standing question about
        configuration; this is a direct instruction from whoever owns the
        gate, arriving at the moment they changed their mind. Asking the
        gate here would make the instruction depend on the caller having
        already published its own new state, which is a race with no
        upside.

        Returns whether a process was started. False covers both "no such
        spec" and "one is already following this lineage" -- neither is
        an error, and an instruction repeated twice must not put two
        producers on one store.
        """
        with self._lock:
            registry = self._registries.get(name)
            if registry is None:
                logger.warning(
                    "[Tower][Worker] asked to attach unknown worker %r; "
                    "nothing will follow capture %s for it",
                    name,
                    capture_id,
                )
                return False
            self.reap()
            return self._attach_to_registry(
                registry,
                capture_id,
                capture_dir,
                continues=None,
                attach_mode=ATTACH_MODE_FROM_NOW,
            )

    def detach(self, name: str, grace_seconds: float = DEFAULT_GRACE_SECONDS) -> int:
        """Stop every worker belonging to ONE spec. Returns how many.

        `grace_seconds` is how long a worker gets to exit on its own
        first. The caller chooses it and the caller should usually choose
        ZERO: nothing here SIGNALS a worker, and a follower tailing a
        journal that is still being written has no reason to stop. Waiting
        on one measures the full grace every time and then terminates it
        anyway. `shutdown` is the case where waiting is right, because
        there the capture has closed and the follower really will finish.

        Detaching does NOT disable the spec. The gate is the one source
        of truth for whether a spec should be running; a latch in here
        would be a second one, and the two would disagree the first time
        either changed.
        """
        with self._lock:
            registry = self._registries.get(name)
            if registry is None:
                return 0
            stopped = 0
            for root, worker in list(registry.workers.items()):
                if not self._stop_worker(worker, grace_seconds):
                    # Still alive. KEEPING it in the registry is the
                    # point: forgetting a worker that could not be
                    # terminated makes it an orphan nothing can see --
                    # not `status`, not `/health`, not the next
                    # `shutdown` -- and three Stop/Start cycles then
                    # leave four producers running with the supervisor
                    # aware of one.
                    continue
                registry.forget(root)
                stopped += 1
            return stopped

    def capture_closed(self, capture_id: str) -> None:
        """A recording has ended.

        Workers are deliberately NOT stopped here. A capture that ended
        by disconnect may still get a successor within the resume grace
        window, and the follower is the thing that waits for it. Killing
        it on `stream_stop` would turn every WiFi hiccup back into the
        end of the walk.
        """
        if not self._registries:
            return
        for registry in self._registries.values():
            worker = registry.owner_of(capture_id)
            if worker is None:
                continue
            logger.info(
                "[Tower][Worker] capture %s closed; %s worker pid %s continues "
                "until it observes completion",
                capture_id,
                registry.spec.name,
                worker.process.pid,
            )
        self.reap()

    def reap(self) -> None:
        """Notice workers that have exited, and say how they went."""
        with self._lock:
            self._reap_locked()

    def _reap_locked(self) -> None:
        for registry in self._registries.values():
            for root, worker in list(registry.workers.items()):
                code = worker.process.poll()
                if code is None:
                    continue
                elapsed = self._clock() - worker.started_at
                if code == 0:
                    logger.info(
                        "[Tower][Worker] %s worker pid %s for capture %s "
                        "finished after %.1fs (lineage: %s)",
                        registry.spec.name,
                        worker.process.pid,
                        worker.capture_id,
                        elapsed,
                        ", ".join(worker.lineage),
                    )
                else:
                    # Loud, and named against its capture. A follower that
                    # dies before acquiring the writer lock leaves the
                    # result channel with nothing to read, and iOS renders
                    # that as "no world" -- indistinguishable from "you
                    # have not walked yet".
                    logger.warning(
                        "[Tower][Worker] %s worker pid %s for capture %s "
                        "EXITED %s after %.1fs; nothing is following this "
                        "capture for it. argv: %s",
                        registry.spec.name,
                        worker.process.pid,
                        worker.capture_id,
                        code,
                        elapsed,
                        " ".join(worker.argv),
                    )
                registry.forget(root)

    def shutdown(self, grace_seconds: float = DEFAULT_GRACE_SECONDS) -> None:
        """Let every worker finish, then insist."""
        with self._lock:
            for registry in self._registries.values():
                for root, worker in list(registry.workers.items()):
                    if self._stop_worker(worker, grace_seconds):
                        registry.forget(root)

    # -- reporting ----------------------------------------------------

    def status(self) -> list[dict]:
        """One row per live worker. Safe to call from /health."""
        with self._lock:
            self._reap_locked()
            return self._status_locked()

    def _status_locked(self) -> list[dict]:
        return [
            {
                # Which spec this row belongs to. Without it two rows for
                # one capture id are indistinguishable, and "a worker is
                # alive on this capture" stops being an answer to any
                # particular cartridge's question.
                "worker": registry.spec.name,
                "capture_id": worker.capture_id,
                "lineage": list(worker.lineage),
                "pid": worker.process.pid,
                "alive": True,
                "uptime_seconds": self._clock() - worker.started_at,
            }
            for registry in self._registries.values()
            for worker in registry.workers.values()
        ]

    def following(self, name: str) -> list[str]:
        """The capture ids one named spec currently has a live worker on."""
        with self._lock:
            registry = self._registries.get(name)
            if registry is None:
                return []
            self._reap_locked()
            return [worker.capture_id for worker in registry.workers.values()]

    # -- internals ----------------------------------------------------

    @staticmethod
    def _gate_open(spec: WorkerSpec) -> bool:
        """Whether this spec may run right now. A broken gate means no.

        Contained, and contained CLOSED. `capture_opened` runs on the
        connection that just received `stream_start`, so an exception
        escaping a gate would drop a recording -- and defaulting the
        other way would start a producer whose enablement could not be
        established, which is the direction that writes data nobody
        asked for.
        """
        gate = spec.gate
        if gate is None:
            return True
        try:
            return bool(gate())
        except Exception:
            logger.exception(
                "[Tower][Worker] the gate for worker %r raised; treating it "
                "as closed and starting nothing",
                spec.name,
            )
            return False

    def _attach_to_registry(
        self,
        registry: _SpecRegistry,
        capture_id: str,
        capture_dir,
        *,
        continues,
        attach_mode: str,
    ) -> bool:
        if continues is not None:
            root = registry.roots.get(continues)
            worker = registry.workers.get(root) if root is not None else None
            if worker is not None and worker.is_alive():
                # The existing follower will walk into this capture by
                # itself. Record the mapping so the NEXT successor --
                # which names this capture, not the one we spawned on --
                # is recognised too.
                registry.roots[capture_id] = root
                worker.lineage.append(capture_id)
                logger.info(
                    "[Tower][Worker] capture %s continues %s; %s worker pid %s "
                    "(following %s) will chain into it, not restarted",
                    capture_id,
                    continues,
                    registry.spec.name,
                    worker.process.pid,
                    root,
                )
                return False
            # Either this Tower never saw the predecessor (a restart
            # mid-walk), or this spec's worker has died. Both mean
            # nothing is reading this capture FOR THIS SPEC, so follow it.
            logger.info(
                "[Tower][Worker] capture %s continues %s but no live %s worker "
                "owns that lineage; starting one",
                capture_id,
                continues,
                registry.spec.name,
            )
        elif registry.owner_of(capture_id) is not None:
            # Already followed by this spec. Attaching again would put two
            # producers on one store.
            return False

        return self._start(registry, capture_id, capture_dir, attach_mode)

    def _start(
        self,
        registry: _SpecRegistry,
        capture_id: str,
        capture_dir,
        attach_mode: str,
    ) -> bool:
        spec = registry.spec
        argv = tuple(
            part.replace(PLACEHOLDER_CAPTURE_DIR, str(capture_dir))
            .replace(PLACEHOLDER_CAPTURE_ID, capture_id)
            .replace(PLACEHOLDER_ATTACH_MODE, attach_mode)
            for part in spec.argv
        )
        try:
            process = self._spawn(
                argv,
                cwd=spec.cwd,
                stdout=None if spec.inherit_output else subprocess.DEVNULL,
                stderr=None if spec.inherit_output else subprocess.DEVNULL,
                # A worker must not die because the operator pressed
                # Ctrl-C in the Tower's console: on Windows a console
                # Ctrl-C goes to the whole process group, and a follower
                # killed mid-build leaves a stale writer lock behind.
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                ),
            )
        except Exception:
            logger.exception(
                "[Tower][Worker] could not start the %s worker for capture %s; "
                "this capture will record frames but NOTHING will follow it "
                "for that worker. argv: %s",
                spec.name,
                capture_id,
                " ".join(argv),
            )
            return False

        registry.workers[capture_id] = _Worker(
            capture_id=capture_id,
            process=process,
            argv=argv,
            started_at=self._clock(),
            lineage=[capture_id],
        )
        registry.roots[capture_id] = capture_id
        logger.info(
            "[Tower][Worker] started %s pid %s for capture %s: %s",
            spec.name,
            process.pid,
            capture_id,
            " ".join(argv),
        )
        return True

    def _stop_worker(self, worker: _Worker, grace_seconds: float) -> bool:
        """Stop one worker. Returns whether it is actually gone.

        The return value is what stops an orphan. A `terminate()` that
        raises used to be logged and then forgotten anyway, which removed
        the worker from the registry while leaving the process running --
        invisible to `status`, to `/health` and to the next `shutdown`.
        Three Stop/Start cycles left four producers alive with the
        supervisor aware of one.
        """
        process = worker.process
        try:
            process.wait(timeout=grace_seconds)
            logger.info(
                "[Tower][Worker] worker pid %s for capture %s exited within "
                "its grace window",
                process.pid,
                worker.capture_id,
            )
            return True
        except Exception:
            if grace_seconds:
                logger.warning(
                    "[Tower][Worker] worker pid %s for capture %s did not "
                    "exit within %.1fs; terminating.",
                    process.pid,
                    worker.capture_id,
                    grace_seconds,
                )
        try:
            process.terminate()
        except Exception:
            logger.exception(
                "[Tower][Worker] could NOT terminate pid %s; it stays in the "
                "registry so it is still visible to /health and to the next "
                "shutdown, and nothing else will be attached in its place",
                process.pid,
            )
            return False

        # `terminate()` is asynchronous. On Windows it is
        # `TerminateProcess`, and a `poll()` immediately afterwards
        # routinely still returns None -- so a worker that WAS killed
        # would be reported as un-killable, stay in the registry, and
        # make a Pause report itself as still following a capture.
        #
        # This wait is not the grace window that was removed. That one
        # waited on a process nobody had asked to stop; this one waits on
        # a process that has just been shot, and it is measured in
        # milliseconds.
        try:
            process.wait(timeout=TERMINATE_TIMEOUT_SECONDS)
            return True
        except Exception:
            logger.warning(
                "[Tower][Worker] pid %s did not exit within %.1fs of being "
                "terminated; it stays in the registry so it is still "
                "visible, and nothing else will be attached in its place",
                process.pid,
                TERMINATE_TIMEOUT_SECONDS,
            )
            return False
