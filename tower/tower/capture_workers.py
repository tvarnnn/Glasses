"""Run a worker process for the lifetime of a capture, and reap it.

This is the piece whose absence made the first physical World Builder
test (2026-08-24) require a second terminal, a directory listing, and a
copied UUID. The Tower recorded ten captures that evening and a human
attached a follower to one of them by hand. The other nine were never
read by anything, so the wearer walked for five minutes with the camera
reporting LIVE and the world frozen at the figures from the first two.

**This module is deliberately cartridge-blind.** It knows how to run an
argv when a capture opens and how to stop it when the capture closes. It
does not know what the worker computes, and it names no cartridge --
which is what lets `test_shared_code_does_not_import_a_cartridge` stay
green without an exemption. The argv comes from `main.py`, the wiring
point, as plain strings.

**The web process still does not build.** It supervises a child that
builds. That separation is the reason a rebuild can take seconds without
the frame path noticing, and it is the architecture decision
`docs/agent-handoffs/WORLD-BUILDER.md` section 1 exists to protect.
"""

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# How long a worker gets to finish on its own at shutdown before it is
# terminated. A follower whose capture has closed is usually inside its
# final build, and that build is what releases the writer lock -- kill it
# and the result channel correctly, but needlessly, reports the world
# `failed` with a pid that no longer exists.
DEFAULT_GRACE_SECONDS = 10.0

PLACEHOLDER_CAPTURE_DIR = "{capture_dir}"
PLACEHOLDER_CAPTURE_ID = "{capture_id}"


@dataclass(frozen=True)
class WorkerSpec:
    """What to run, once per capture lineage.

    `argv` may contain `{capture_dir}` and `{capture_id}`, substituted
    per capture. Substitution is positional over the argv LIST, never
    over a joined string: a capture root chosen by an operator can
    contain spaces, and building a command line by concatenation is how
    that becomes a quoting bug on Windows.
    """

    argv: tuple[str, ...]
    cwd: str | None = None
    name: str = "capture-worker"


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


class CaptureWorkerSupervisor:
    """One worker per capture LINEAGE, not per capture.

    The distinction is the whole design. `CaptureFollower` already
    follows a capture across a reconnect: seeing a capture close by
    disconnect it waits out `RESUME_GRACE_SECONDS` for a successor whose
    manifest names it, and continues into that one. So a successor
    capture already has a reader. Starting a second worker for it would
    put two followers, two mapping sessions and two writer locks on one
    walk -- and the result channel, which prefers "a LIVE world if one
    exists", would then have two live worlds to choose between and would
    pick by `updated_at`.

    Lineage is decided by the WRITER and written into the manifest
    (`CaptureRecorder.resumable_capture`). This class only reads the
    `continues` value it is handed; it never guesses which capture
    continues which.
    """

    def __init__(self, spec: WorkerSpec | None, *, spawn=None, clock=time.monotonic):
        self._spec = spec
        self._spawn = spawn if spawn is not None else subprocess.Popen
        self._clock = clock
        # lineage root capture id -> worker
        self._workers: dict[str, _Worker] = {}
        # any capture id -> the lineage root that owns it
        self._roots: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        """Whether anything will be started at all.

        Reported rather than inferred: "no worker is configured" and "a
        worker is configured and failed" call for opposite responses from
        whoever is reading /health.
        """
        return self._spec is not None

    # -- lifecycle ----------------------------------------------------

    def capture_opened(self, capture_id: str, capture_dir, *, continues=None) -> None:
        """A recording has started. Attach a worker unless one already owns it."""
        if self._spec is None:
            return

        self.reap()

        if continues is not None:
            root = self._roots.get(continues)
            worker = self._workers.get(root) if root is not None else None
            if worker is not None and worker.is_alive():
                # The existing follower will walk into this capture by
                # itself. Record the mapping so the NEXT successor -- which
                # names this capture, not the one we spawned on -- is
                # recognised too.
                self._roots[capture_id] = root
                worker.lineage.append(capture_id)
                logger.info(
                    "[Tower][Worker] capture %s continues %s; worker pid %s "
                    "(following %s) will chain into it, not restarted",
                    capture_id,
                    continues,
                    worker.process.pid,
                    root,
                )
                return
            # Either this Tower never saw the predecessor (a restart
            # mid-walk), or its worker has died. Both mean nothing is
            # reading this capture, so follow it.
            logger.info(
                "[Tower][Worker] capture %s continues %s but no live worker "
                "owns that lineage; starting one",
                capture_id,
                continues,
            )

        self._start(capture_id, capture_dir)

    def capture_closed(self, capture_id: str) -> None:
        """A recording has ended.

        The worker is deliberately NOT stopped here. A capture that ended
        by disconnect may still get a successor within the resume grace
        window, and the follower is the thing that waits for it. Killing
        it on `stream_stop` would turn every WiFi hiccup back into the
        end of the walk.
        """
        if self._spec is None:
            return
        root = self._roots.get(capture_id)
        worker = self._workers.get(root) if root is not None else None
        if worker is None:
            return
        logger.info(
            "[Tower][Worker] capture %s closed; worker pid %s continues until "
            "it observes completion",
            capture_id,
            worker.process.pid,
        )
        self.reap()

    def reap(self) -> None:
        """Notice workers that have exited, and say how they went."""
        for root, worker in list(self._workers.items()):
            code = worker.process.poll()
            if code is None:
                continue
            elapsed = self._clock() - worker.started_at
            if code == 0:
                logger.info(
                    "[Tower][Worker] worker pid %s for capture %s finished "
                    "after %.1fs (lineage: %s)",
                    worker.process.pid,
                    worker.capture_id,
                    elapsed,
                    ", ".join(worker.lineage),
                )
            else:
                # Loud, and named against its capture. A follower that dies
                # before acquiring the writer lock leaves the result channel
                # with nothing to read, and iOS renders that as "no world" --
                # indistinguishable from "you have not walked yet".
                logger.warning(
                    "[Tower][Worker] worker pid %s for capture %s EXITED %s "
                    "after %.1fs; nothing is building a world from this "
                    "capture. argv: %s",
                    worker.process.pid,
                    worker.capture_id,
                    code,
                    elapsed,
                    " ".join(worker.argv),
                )
            self._forget(root)

    def shutdown(self, grace_seconds: float = DEFAULT_GRACE_SECONDS) -> None:
        """Let every worker finish, then insist."""
        if self._spec is None:
            return
        for root, worker in list(self._workers.items()):
            process = worker.process
            try:
                process.wait(timeout=grace_seconds)
                logger.info(
                    "[Tower][Worker] worker pid %s for capture %s exited "
                    "during shutdown",
                    process.pid,
                    worker.capture_id,
                )
            except Exception:
                logger.warning(
                    "[Tower][Worker] worker pid %s for capture %s did not exit "
                    "within %.1fs; terminating. Its world may be left with a "
                    "stale writer lock, which the result channel reports as "
                    "`failed`.",
                    process.pid,
                    worker.capture_id,
                    grace_seconds,
                )
                try:
                    process.terminate()
                except Exception:
                    logger.exception(
                        "[Tower][Worker] could not terminate pid %s", process.pid
                    )
            self._forget(root)

    # -- reporting ----------------------------------------------------

    def status(self) -> list[dict]:
        """One row per live worker. Safe to call from /health."""
        self.reap()
        return [
            {
                "capture_id": worker.capture_id,
                "lineage": list(worker.lineage),
                "pid": worker.process.pid,
                "alive": True,
                "uptime_seconds": self._clock() - worker.started_at,
            }
            for worker in self._workers.values()
        ]

    # -- internals ----------------------------------------------------

    def _start(self, capture_id: str, capture_dir) -> None:
        argv = tuple(
            part.replace(PLACEHOLDER_CAPTURE_DIR, str(capture_dir)).replace(
                PLACEHOLDER_CAPTURE_ID, capture_id
            )
            for part in self._spec.argv
        )
        try:
            process = self._spawn(
                argv,
                cwd=self._spec.cwd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                # A worker must not die because the operator pressed
                # Ctrl-C in the Tower's console: on Windows a console
                # Ctrl-C goes to the whole process group, and a follower
                # killed mid-build leaves a stale writer lock behind.
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    if os.name == "nt"
                    else 0
                ),
            )
        except Exception:
            logger.exception(
                "[Tower][Worker] could not start a worker for capture %s; "
                "this capture will record frames but NOTHING will build a "
                "world from it. argv: %s",
                capture_id,
                " ".join(argv),
            )
            return

        self._workers[capture_id] = _Worker(
            capture_id=capture_id,
            process=process,
            argv=argv,
            started_at=self._clock(),
            lineage=[capture_id],
        )
        self._roots[capture_id] = capture_id
        logger.info(
            "[Tower][Worker] started pid %s for capture %s: %s",
            process.pid,
            capture_id,
            " ".join(argv),
        )

    def _forget(self, root: str) -> None:
        worker = self._workers.pop(root, None)
        if worker is None:
            return
        for capture_id in worker.lineage:
            if self._roots.get(capture_id) == root:
                del self._roots[capture_id]
