"""The CV Lab itself: one slot, many experiments, one truthful document.

What this replaces
------------------
Choosing an experiment used to mean editing `TOWER_CV_EXPERIMENT`,
restarting the Tower, starting a generic recording somewhere else, and
reading an anonymous number off a debug panel. Every part of that is a
consequence of one fact: the experiment was decided at process start and
nothing on the wire could say which one it was. This module moves the
decision to runtime and puts a name on every number that leaves.

What it is NOT
--------------
It is not a module registry and it does not swap modules.
`ModuleContainer` still holds exactly one `Module`, constructed once, with
no discovery and no swap path -- `04-MODULE-SYSTEM.md` forbids dynamic
discovery before V1.0 and nothing here works around that. What changed is
what is *inside* the one Lab slot, which is what the module's own
docstring has said all along: "one Lab slot, many experiments".

Three clocks' worth of care, in one place
-----------------------------------------
1. **The frame path is synchronous and on the event loop.** `process()`
   never awaits, so no command can interleave *within* a frame. That is
   what makes `frame_provenance()` -- read by `ws.py` immediately after
   `process()`, with no await between -- describe the frame it just
   answered rather than some later one.

2. **A load is not.** A model-backed experiment's `load()` downloads
   weights and blocks; `depth` fetches 119 MB the first time. Awaiting
   that inside a connection's receive loop would stop that socket reading
   for minutes, and `handoff.md` 13.7 says iOS replaces a connection it
   cannot write to for two seconds. So `start()` validates, publishes
   `starting`, and hands the load to a background task. The command
   returns immediately; the outcome arrives as state, which is exactly
   the shape iOS's `run(_:)` already has.

3. **The status document is read from another thread.** The result
   channel's poller computes snapshots with `asyncio.to_thread`, so
   `status()` runs concurrently with the loop that mutates this object.
   Every state transition and every status build therefore happens under
   `_guard`. The FRAME PATH deliberately does not take it: it mutates
   only per-run counters, whose individual reads are atomic, and putting
   a lock on the measured path to make a diagnostic one frame fresher
   would be paying in the wrong currency.

Staleness is structural, not checked
------------------------------------
A run is the unit of provenance and a new experiment is a new run. The
old experiment is released BEFORE the new run id is published, so there
is no window in which a result produced by one experiment can carry
another's name. `run_id` travels on every `frame_result` and on the
status document, and a client that sees a result whose `run_id` is not
the one it is watching should discard it -- not because the Tower is
expected to send one, but because that is the only way a reconnect across
a restart cannot show a previous Tower's numbers.
"""

import asyncio
import importlib.util
import logging
import threading
import time
import uuid

from tower.cv_lab import catalog
from tower.cv_lab.contracts import (
    CONTROL_CONTRACT,
    ERR_EXPERIMENT_UNAVAILABLE,
    ERR_INVALID_STATE,
    ERR_LAB_BUSY,
    ERR_LAB_UNAVAILABLE,
    ERR_MALFORMED,
    ERR_STALE_RUN,
    ERR_START_FAILED,
    ERR_UNKNOWN_EXPERIMENT,
    FRAME_REFUSAL_REASONS,
    FRAME_RESULT_CONTRACT,
    ORIGIN_CLIENT_REQUEST,
    ORIGIN_STARTUP_DEFAULT,
    STATE_FAILED,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_RUNNING,
    STATE_STARTING,
    STATE_STOPPED,
    STATE_UNAVAILABLE,
    STATUS_CONTRACT,
    STREAM_IDLE_AFTER_S,
    TIME_BASIS,
)
from tower.cv_lab.run import LabRun
from tower.experiments import EXPERIMENTS, ExperimentSettings, experiment_metadata
from tower.loading import run_abandonable
from tower.modules.base import FrameProcessingError

logger = logging.getLogger(__name__)

# The bound on arming an experiment. The same number and the same reason
# as `ModuleContainer.LOAD_TIMEOUT_S`: 119 MB of MiDaS weights inside a
# 10 s bound would demand ~95 Mbit/s from the first byte, so enforcing the
# tight bound would convert "slow once, then fast forever" into "fails
# every first run". Imported rather than restated so the two cannot drift.
from tower.modules.container import LOAD_TIMEOUT_S as ARM_TIMEOUT_S


class CommandOutcome:
    """What a command did, and the full status afterwards.

    Carries the status either way. A refusal that said only "no" would
    leave a client guessing what state it is now in, and the most common
    reason for a refusal -- somebody else changed the experiment -- is
    precisely the case where the client's picture is out of date.
    """

    __slots__ = ("accepted", "reason", "message", "status", "extra")

    def __init__(
        self,
        *,
        accepted: bool,
        status: dict,
        reason: str | None = None,
        message: str | None = None,
        extra: dict | None = None,
    ) -> None:
        self.accepted = accepted
        self.reason = reason
        self.message = message
        self.status = status
        self.extra = extra or {}


def _torch_is_installed() -> bool:
    """Whether the optional [ml] extra is present, WITHOUT importing it.

    `find_spec` locates a module and does not execute it, which is the
    whole point: `test_importing_the_lab_does_not_import_torch` asserts
    that importing `tower.main` leaves torch out of `sys.modules`, and an
    availability check that imported torch to answer "is torch available"
    would be a 2 GB answer to a yes/no question.
    """
    try:
        return importlib.util.find_spec("torch") is not None
    except (ImportError, ValueError):
        return False


class CVLab:
    """The one Lab slot's contents, its lifecycle, and what it reports."""

    def __init__(
        self,
        initial_experiment_id: str,
        settings: ExperimentSettings | None = None,
        *,
        experiment=None,
        clock=time.time,
        connection_count=None,
        instance_id: str | None = None,
    ) -> None:
        self._initial_experiment_id = initial_experiment_id
        self._settings = settings or ExperimentSettings()
        self._clock = clock
        self._connection_count = connection_count
        # Minted per process. A client that reconnects to a RESTARTED
        # Tower would otherwise see `run-1` again and could read it as the
        # run it was already watching. Part of every run id for that
        # reason, rather than a field beside it that a client might not
        # compare.
        self.instance_id = instance_id or uuid.uuid4().hex[:12]

        # Injected instance wins, for tests and for a caller that has
        # already built one. Otherwise the registry factory runs in
        # `load_initial`, never at construction: building a detector here
        # would load model weights merely because someone constructed a
        # Lab.
        self._injected_experiment = experiment
        self._experiment = None

        self._guard = threading.Lock()
        self._state = STATE_IDLE
        self._state_reason: str | None = None
        self._state_since = clock()
        self._selected_id: str | None = None
        self._run: LabRun | None = None
        self._run_counter = 0
        # Checked and set with no await between, which is what makes it
        # atomic on a single-threaded event loop. An asyncio.Lock would
        # bind itself to the first loop that used it, and `create_app()`
        # drives startup through `asyncio.run` while everything after runs
        # on uvicorn's loop -- a different one.
        self._switching = False
        self._arm_task: asyncio.Task | None = None
        self._released = False

        # Lab-scoped, not run-scoped, and deliberately: "frames are
        # arriving but the Lab is idle" is the single most useful thing to
        # know when nothing is happening, and a run-scoped counter cannot
        # say it because there is no run.
        self._frames_offered_total = 0
        self._last_frame_at: float | None = None

        self._last_frame_provenance: dict | None = None

    # -- module-facing lifecycle ---------------------------------------

    async def load_initial(self) -> None:
        """Arm the startup default. Called from `Module._do_load`.

        Deliberately NOT the same path as `start()`. This one propagates:
        an unknown name or a failed load here reaches `ModuleContainer`,
        which marks the module FAILED, which is the behaviour every
        existing lifecycle and load-timeout test encodes. A typo in
        `TOWER_CV_EXPERIMENT` must still be loud.

        The interactive path is the one that recovers. See `start()`.
        """
        experiment_id = self._initial_experiment_id
        if self._injected_experiment is None:
            factory = EXPERIMENTS.get(experiment_id)
            if factory is None:
                raise ValueError(
                    f"unknown experiment {experiment_id!r}; "
                    f"available: {sorted(EXPERIMENTS)}"
                )
            experiment = factory()
        else:
            experiment = self._injected_experiment

        # Published BEFORE the load, so a status read during a slow
        # startup says `starting` and names what it is starting rather
        # than reporting an idle Lab that is in fact busy.
        self._transition(
            STATE_STARTING,
            selected=experiment_id,
            run=self._new_run(experiment_id, ORIGIN_STARTUP_DEFAULT),
        )
        # Installed BEFORE the load, unlike the interactive path in
        # `_arm`. A partially-loaded startup experiment must still be
        # reachable by `release()`: the container's load timeout ABANDONS
        # the loading thread and then marks the module FAILED, and if
        # nothing holds the instance at that moment, nothing closes
        # `LoadInvalidation`'s latch and the abandoned thread installs a
        # live model -- on CUDA, resident GPU memory -- into a module that
        # will never be released again. `process()` cannot reach it in the
        # meantime because the state is STARTING, not RUNNING.
        with self._guard:
            self._experiment = experiment

        # On a thread, not inline. `asyncio.wait_for` can cancel only at an
        # await point, and a model-backed `load()` is a torch import, a
        # weight download and a `.to(device)`, none of which yield one.
        # `run_abandonable` rather than `asyncio.to_thread` because
        # `asyncio.run` joins the default executor on close -- see
        # tower/loading.py for the measurement.
        await run_abandonable(experiment.load, self._settings)

        with self._guard:
            self._experiment = experiment
            self._set_state_locked(STATE_RUNNING)
            self._record_runtime_locked(experiment)

    def release(self, reason: str = "the Lab was released") -> None:
        """Free whatever the current experiment holds, and stop serving.

        Called from `Module._do_unload` (clean teardown) and from
        `Module._do_release` (a FAILED transition, reachable from
        anywhere, including from inside a load). Must be safe after a
        partial load and safe to call twice.

        Terminal. The module owning this Lab is gone either way, and the
        Lab reports `unavailable` rather than `idle` so that nobody reads
        a dead slot as one waiting for a request.
        """
        task, self._arm_task = self._arm_task, None
        if task is not None:
            task.cancel()
        with self._guard:
            self._released = True
            self._set_state_locked(STATE_UNAVAILABLE, reason=reason)
            experiment, self._experiment = self._experiment, None
            self._last_frame_provenance = None
        if experiment is not None:
            experiment.release()

    # -- the frame path -------------------------------------------------

    def process(self, raw_bytes: bytes):
        """Run the armed experiment over one frame, or refuse it legibly.

        Synchronous and free of awaits, which is load-bearing: it is what
        makes a switch unable to interleave inside a frame, and what makes
        `frame_provenance()` describe this frame.
        """
        now = self._clock()
        self._frames_offered_total += 1
        self._last_frame_at = now
        run = self._run
        state = self._state
        experiment = self._experiment
        if run is not None:
            run.record_offered()

        if state != STATE_RUNNING or experiment is None:
            self._last_frame_provenance = None
            if run is not None:
                run.record_refused(now)
            raise FrameProcessingError(
                self._refusal_message(state),
                reason=FRAME_REFUSAL_REASONS.get(state, "cv_lab_unavailable"),
            )

        try:
            result = experiment.run(raw_bytes)
        except BaseException:
            self._last_frame_provenance = None
            if run is not None:
                run.record_failed(now)
            raise

        result_seq = run.record_result(result, now) if run is not None else 0
        try:
            self._last_frame_provenance = self._provenance(
                run, result, result_seq, now
            )
        except Exception:
            # Attribution is a diagnostic. A result that does not look
            # like an `ExperimentResult` is a real bug and is logged as
            # one -- but raising here would leave `ModuleContainer` no
            # choice but `mark_failed()`, which is TERMINAL, so one odd
            # frame would end CV processing for the life of the process.
            self._last_frame_provenance = None
            logger.exception(
                "[Tower][CVLab] could not attribute a result from %s; the "
                "frame is answered without provenance",
                self._selected_id,
            )
        return result

    def frame_provenance(self) -> dict | None:
        """Who produced the frame result `process()` just returned.

        Read by `ws.py` immediately after `process()` and before the
        `await` that sends the reply. `None` means the frame produced no
        result, so there is nothing to attribute.

        Deliberately NOT attached to the `ExperimentResult` itself: a
        module returns what its experiment returned, and wrapping the
        result would make `Module.process()` mean something different for
        this module than for every other one.
        """
        provenance, self._last_frame_provenance = self._last_frame_provenance, None
        return provenance

    def _provenance(self, run, result, result_seq: int, now: float) -> dict:
        descriptor = run.descriptor if run is not None else {}
        return {
            "contract": FRAME_RESULT_CONTRACT,
            # Which Tower process. A reconnect to a restarted Tower cannot
            # otherwise be told from a reconnect to the same one.
            "tower_instance_id": self.instance_id,
            # Which run. THE staleness check: a client watching run X must
            # discard a result carrying run Y.
            "run_id": run.run_id if run is not None else None,
            # Dense within the run, starting at 1. The wire `seq` is the
            # phone's capture index and skips by design, so it cannot be
            # used to order results.
            "result_seq": result_seq,
            "experiment_id": descriptor.get("id"),
            "experiment_name": descriptor.get("name"),
            # Measured or inferred, on every frame, not only in the
            # aggregate. Rule 16 / Core Principle 2.
            "provenance": descriptor.get("provenance"),
            "backend": descriptor.get("backend"),
            "device": run.runtime.get("device") if run is not None else None,
            "device_requested": self._settings.device,
            "result_label": result.result_label,
            # The Tower measuring itself. Repeated here rather than only
            # at the top level so that the whole attribution block is
            # self-contained -- a consumer keeping one of these does not
            # have to keep the message around it too.
            "processing_ms": result.processing_ms,
            "tower_received_at": now,
            "time_basis": TIME_BASIS,
        }

    def _refusal_message(self, state: str) -> str:
        if state == STATE_IDLE:
            return (
                "the CV Lab is idle: no experiment is armed, so this frame "
                "produced no result. Send cv_lab_start to arm one."
            )
        if state == STATE_STARTING:
            return (
                "the CV Lab is arming an experiment; frames are refused "
                "until it is ready rather than answered by the previous one"
            )
        if state == STATE_PAUSED:
            return "the CV Lab is paused; send cv_lab_resume to continue"
        if state == STATE_STOPPED:
            return (
                "the CV Lab is stopped; the last run's figures are final. "
                "Send cv_lab_start to begin another"
            )
        if state == STATE_FAILED:
            return (
                "the CV Lab's last start failed: "
                f"{self._state_reason or 'no reason recorded'}"
            )
        return (
            "the CV Lab cannot run experiments on this Tower: "
            f"{self._state_reason or 'no reason recorded'}"
        )

    # -- commands -------------------------------------------------------

    def start(self, experiment_id, *, origin: str = ORIGIN_CLIENT_REQUEST):
        """Arm an experiment. Returns as soon as the request is decided.

        Synchronous on purpose. The load runs in a background task, so a
        `depth` start that spends two minutes downloading weights does not
        stop the connection that asked for it from sending frames -- and
        iOS's `run(_:)` already returns nothing and reports through state,
        so there is nothing here for it to wait on.
        """
        if self._released or self._state == STATE_UNAVAILABLE:
            return self._refuse(
                ERR_LAB_UNAVAILABLE,
                "this Tower cannot run experiments: "
                f"{self._state_reason or 'the Lab module is not available'}",
            )
        if not isinstance(experiment_id, str) or not experiment_id:
            return self._refuse(
                ERR_MALFORMED, "cv_lab_start requires a string 'experiment_id'"
            )
        if not catalog.is_registered(experiment_id):
            return self._refuse(
                ERR_UNKNOWN_EXPERIMENT,
                f"this Tower has no experiment {experiment_id!r}",
                extra={"available": sorted(EXPERIMENTS)},
            )
        metadata = experiment_metadata(experiment_id)
        if metadata.requires_model and not _torch_is_installed():
            return self._refuse(
                ERR_EXPERIMENT_UNAVAILABLE,
                f"{experiment_id!r} needs the optional [ml] extra (torch), "
                "which is not installed on this Tower",
                extra={"experiment_id": experiment_id},
            )
        if self._switching:
            return self._refuse(
                ERR_LAB_BUSY,
                "another start or stop is already in flight; the Lab holds "
                "one experiment and will not queue a second request behind it",
            )

        # Set with no await in between, so no second command can pass this
        # check before the flag is up.
        self._switching = True
        run = self._new_run(experiment_id, origin)
        # The old experiment goes BEFORE the new run id is published.
        # After this line nothing can produce a result, so no result can
        # be produced under the wrong name.
        self._drop_experiment()
        self._transition(STATE_STARTING, selected=experiment_id, run=run)
        self._arm_task = asyncio.get_running_loop().create_task(
            self._arm(experiment_id, run.run_id)
        )
        return CommandOutcome(accepted=True, status=self.status())

    async def _arm(self, experiment_id: str, run_id: str) -> None:
        """Load the experiment and publish the outcome. Never raises."""
        experiment = None
        try:
            experiment = EXPERIMENTS[experiment_id]()
            # Bounded, and the bound is the container's. A stalled weight
            # download must not leave the Lab in `starting` forever with
            # no state transition anyone can see -- Rule 15 wants a
            # defined failure transition, and `failed` is it.
            await asyncio.wait_for(
                run_abandonable(experiment.load, self._settings),
                timeout=ARM_TIMEOUT_S,
            )
        except asyncio.CancelledError:
            # A stop landed mid-load. Release BEFORE unwinding: the load
            # runs on a thread nobody joins, and closing the latch here is
            # what makes that thread free what it built instead of
            # installing it into an object with no owner.
            self._release_quietly(experiment)
            raise
        except BaseException as exc:
            self._release_quietly(experiment)
            self._fail_arm(
                run_id,
                f"{experiment_id} could not be armed: {type(exc).__name__}: {exc}",
            )
            logger.exception(
                "[Tower][CVLab] arming %s failed; the Lab stays available "
                "and another start may be sent",
                experiment_id,
            )
            return

        with self._guard:
            if (
                self._released
                or self._state != STATE_STARTING
                or self._run is None
                or self._run.run_id != run_id
            ):
                # Superseded while we were loading. Whatever we built must
                # not be installed -- see tower/loading.py for why release
                # running first is the whole problem.
                stale = experiment
            else:
                stale = None
                self._experiment = experiment
                self._set_state_locked(STATE_RUNNING)
                self._record_runtime_locked(experiment)
            self._switching = False
        if stale is not None:
            self._release_quietly(stale)
            logger.info(
                "[Tower][CVLab] %s finished arming after run %s was "
                "superseded; discarded",
                experiment_id,
                run_id,
            )

    async def wait_until_armed(self) -> None:
        """Await the in-flight arm, if there is one. For tests and shutdown.

        Not part of the wire surface: a client learns that arming finished
        from the status document, which is pushed. This exists so a test
        does not have to sleep, and so a shutdown does not leave a load
        running into a torn-down app.
        """
        task = self._arm_task
        if task is None:
            return
        try:
            await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling() > 0:
                raise
        except Exception:  # noqa: BLE001
            logger.debug("[Tower][CVLab] arm task ended badly", exc_info=True)

    def _fail_arm(self, run_id: str, reason: str) -> None:
        with self._guard:
            self._switching = False
            if self._run is not None and self._run.run_id == run_id:
                self._set_state_locked(STATE_FAILED, reason=reason)

    def pause(self, run_id=None):
        refusal = self._check_run_id(run_id)
        if refusal is not None:
            return refusal
        if self._state != STATE_RUNNING:
            return self._refuse(
                ERR_INVALID_STATE,
                f"cannot pause: the Lab is {self._state}, not running",
            )
        # The experiment stays loaded. That is the whole difference from
        # stop: a paused depth run resumes instantly, a stopped one pays
        # the load again.
        self._transition(STATE_PAUSED)
        return CommandOutcome(accepted=True, status=self.status())

    def resume(self, run_id=None):
        refusal = self._check_run_id(run_id)
        if refusal is not None:
            return refusal
        if self._state != STATE_PAUSED:
            return self._refuse(
                ERR_INVALID_STATE,
                f"cannot resume: the Lab is {self._state}, not paused",
            )
        if self._experiment is None:
            return self._refuse(
                ERR_INVALID_STATE,
                "cannot resume: the paused run holds no armed experiment",
            )
        self._transition(STATE_RUNNING)
        return CommandOutcome(accepted=True, status=self.status())

    def stop(self, run_id=None):
        refusal = self._check_run_id(run_id)
        if refusal is not None:
            return refusal
        if self._state not in (STATE_RUNNING, STATE_PAUSED, STATE_STARTING):
            return self._refuse(
                ERR_INVALID_STATE,
                f"cannot stop: the Lab is {self._state}, and there is no run "
                "to end",
            )
        # A stop lands during an arm too, and must win: the task checks
        # the run id it was given and discards what it built.
        self._switching = False
        task, self._arm_task = self._arm_task, None
        if task is not None:
            task.cancel()
        self._drop_experiment()
        with self._guard:
            if self._run is not None:
                self._run.ended_at = self._clock()
            self._set_state_locked(STATE_STOPPED)
        return CommandOutcome(accepted=True, status=self.status())

    def _check_run_id(self, run_id):
        if run_id is None:
            return None
        if not isinstance(run_id, str):
            return self._refuse(
                ERR_MALFORMED, "'run_id' must be a string or absent"
            )
        current = self._run.run_id if self._run is not None else None
        if run_id != current:
            return self._refuse(
                ERR_STALE_RUN,
                f"run {run_id!r} is not the current run; the Lab is now on "
                f"{current!r}",
                extra={"current_run_id": current},
            )
        return None

    def _refuse(self, reason: str, message: str, *, extra: dict | None = None):
        return CommandOutcome(
            accepted=False,
            reason=reason,
            message=message,
            status=self.status(),
            extra=extra,
        )

    # -- state ----------------------------------------------------------

    def _new_run(self, experiment_id: str, origin: str) -> LabRun:
        self._run_counter += 1
        return LabRun(
            run_id=f"{self.instance_id}-{self._run_counter}",
            experiment_id=experiment_id,
            descriptor=catalog.descriptor(experiment_id)
            if catalog.is_registered(experiment_id)
            else {"id": experiment_id, "name": experiment_id, "summary": None},
            origin=origin,
            started_at=self._clock(),
        )

    def _transition(self, state: str, *, reason=None, selected=None, run=None) -> None:
        with self._guard:
            if selected is not None:
                self._selected_id = selected
            if run is not None:
                self._run = run
            self._set_state_locked(state, reason=reason)

    def _set_state_locked(self, state: str, *, reason: str | None = None) -> None:
        self._state = state
        self._state_reason = reason
        self._state_since = self._clock()

    @staticmethod
    def _release_quietly(experiment) -> None:
        """Release an experiment nobody else holds. Never raises.

        Every call site is already handling a failure, and a release that
        raised would replace a legible one with an illegible one.
        """
        if experiment is None:
            return
        try:
            experiment.release()
        except Exception:
            logger.exception("[Tower][CVLab] releasing an experiment raised")

    def _drop_experiment(self) -> None:
        with self._guard:
            experiment, self._experiment = self._experiment, None
            self._last_frame_provenance = None
        self._release_quietly(experiment)

    def _record_runtime_locked(self, experiment) -> None:
        """Ask the experiment what it actually loaded, if it will say.

        Optional on the `Experiment` protocol. An experiment that does not
        implement `describe()` reports nothing, which is different from
        reporting a device it does not have.
        """
        if self._run is None:
            return
        describe = getattr(experiment, "describe", None)
        if describe is None:
            return
        try:
            described = describe()
        except Exception:
            logger.exception(
                "[Tower][CVLab] %s.describe() raised; runtime facts omitted",
                self._run.experiment_id,
            )
            return
        if isinstance(described, dict):
            # Bounded and stringified: this is a diagnostic block, not a
            # channel for an experiment to put arbitrary objects on the
            # wire.
            self._run.runtime = {
                str(key): (value if isinstance(value, (int, float, bool)) else str(value))
                for key, value in list(described.items())[:8]
            }

    # -- reporting ------------------------------------------------------

    def availability(self) -> tuple[bool, str | None]:
        """Whether this Tower can serve the CV Lab contract at all.

        Duck-typed by `tower/results/registry.py`, which must not import
        this module: the result channel core is cartridge-blind and stays
        that way.
        """
        with self._guard:
            if self._state == STATE_UNAVAILABLE:
                return False, (
                    self._state_reason
                    or "the Lab module is not available on this Tower"
                )
        if not EXPERIMENTS:
            return False, "this Tower has no registered experiments"
        return True, None

    def status(self) -> dict:
        """The one document. Same bytes on every surface that serves it.

        Called from the event loop (a command reply) and from a worker
        thread (the result channel's poller), which is what `_guard` is
        for.
        """
        with self._guard:
            state = self._state
            reason = self._state_reason
            since = self._state_since
            selected = self._selected_id
            run = self._run
            frames_offered_total = self._frames_offered_total
            last_frame_at = self._last_frame_at

        now = self._clock()
        return {
            "contract": STATUS_CONTRACT,
            "control_contract": CONTROL_CONTRACT,
            "frame_result_contract": FRAME_RESULT_CONTRACT,
            "tower_instance_id": self.instance_id,
            "time_basis": TIME_BASIS,
            "lifecycle": {
                "state": state,
                # Prose, for a person. Present only when the state needs
                # explaining; `null` is not "no reason", it is "the state
                # speaks for itself".
                "reason": reason,
                "since": since,
                "run_id": run.run_id if run is not None else None,
            },
            "available": self._available_experiments(),
            # The id the Lab is on, whatever it is doing with it. Distinct
            # from `lifecycle.run_id`: a stopped run still names the
            # experiment it ran.
            "selected": selected,
            # What this process would arm at boot. Reported so that a
            # person reading "running edge_detection" can see whether that
            # survives a restart.
            "default_experiment": self._initial_experiment_id,
            "device_requested": self._settings.device,
            "run": self._run_document(run, now),
            "source": {
                # Whether anything is feeding this Lab, which is the
                # question "I pressed Start and nothing happened" is
                # really asking.
                "clients_connected": self._clients_connected(),
                "receiving_frames": (
                    last_frame_at is not None
                    and (now - last_frame_at) <= STREAM_IDLE_AFTER_S
                ),
                "last_frame_at": last_frame_at,
                "frames_offered_total": frames_offered_total,
                "idle_after_s": STREAM_IDLE_AFTER_S,
            },
        }

    def _clients_connected(self) -> int | None:
        if self._connection_count is None:
            return None
        try:
            return int(self._connection_count())
        except Exception:
            logger.exception("[Tower][CVLab] could not read the connection count")
            return None

    def _available_experiments(self) -> list[dict]:
        torch_present = _torch_is_installed()
        rows = []
        for entry in catalog.catalog():
            row = dict(entry)
            if entry["requires_model"] and not torch_present:
                row["available"] = False
                row["unavailable_reason"] = (
                    "needs the optional [ml] extra (torch), which is not "
                    "installed on this Tower"
                )
            else:
                row["available"] = True
                row["unavailable_reason"] = None
            rows.append(row)
        return rows

    def _run_document(self, run: LabRun | None, now: float) -> dict | None:
        if run is None:
            return None
        metadata = (
            experiment_metadata(run.experiment_id)
            if catalog.is_registered(run.experiment_id)
            else None
        )
        if metadata is None:
            metrics, omitted = [], 0
        else:
            metrics, omitted = run.metric_rows(metadata)
        elapsed = max((run.ended_at or now) - run.started_at, 0.0)
        return {
            "run_id": run.run_id,
            "experiment": run.descriptor,
            # Who asked for this run. `startup_default` means nobody did.
            "origin": run.origin,
            "started_at": run.started_at,
            "ended_at": run.ended_at,
            "elapsed_s": round(elapsed, 3),
            # What the experiment says it actually loaded -- device,
            # weights, versions. Empty for an experiment that holds none.
            "runtime": dict(run.runtime),
            "frames_offered": run.frames_offered,
            "frames_processed": run.frames_processed,
            "frames_refused": run.frames_refused,
            "frames_failed": run.frames_failed,
            "metrics": metrics,
            "metrics_omitted": omitted,
            # An experiment emitting a metric it never classified. Empty
            # is the only correct value and a test enforces it for every
            # registered experiment; this is what the wire says if one
            # ever reaches production anyway.
            "unclassified_metrics": run.unclassified_metrics,
            "annotation": self._annotation(run, metadata),
            "timings": {
                "processing_ms": (
                    round(run.processing_ms.average, 4)
                    if run.processing_ms.count
                    else None
                ),
                "processing_ms_max": (
                    round(run.processing_ms.maximum, 4)
                    if run.processing_ms.count
                    else None
                ),
                "stage_ms": {
                    name: round(stage.average, 4)
                    for name, stage in sorted(run.stage_ms.items())
                },
                # When the Tower last produced a result for this run.
                # Tower-receipt time -- there is no capture timestamp
                # anywhere on the wire, so this is when the TOWER saw a
                # frame, never when the glasses did.
                "observed_at": run.last_result_at,
                "time_basis": TIME_BASIS,
            },
            "throughput": {
                # Frames the Lab PROCESSED per second of run wall-clock.
                # Not the capture rate and not the link rate: the current
                # sender forwards roughly one frame in thirty, so this
                # figure is bounded by what arrives, not by what the Lab
                # could do. `frames_offered` beside it is what makes the
                # difference visible.
                "processed_fps": (
                    round(run.frames_processed / elapsed, 3) if elapsed > 0 else None
                ),
                "offered_fps": (
                    round(run.frames_offered / elapsed, 3) if elapsed > 0 else None
                ),
                # The other direction: how fast the Lab could go if frames
                # never stopped arriving. Derived from measured
                # per-frame cost alone.
                "capacity_fps": (
                    round(1000.0 / run.processing_ms.average, 2)
                    if run.processing_ms.count and run.processing_ms.average > 0
                    else None
                ),
            },
        }

    def _annotation(self, run: LabRun, metadata) -> dict:
        """The annotation half of iOS's `CVAnnotationReport`.

        `count` is `null` when the experiment does not produce one and a
        NUMBER when it does, including zero. `0` is a real result meaning
        "found nothing" and must not merge with "did not say".

        `artifact` is always `null` in this contract, and the reason is
        not that it was forgotten. `IOS-to-Tower.md` 5 withholds any image
        whose treatment is unstated, and states that artifact fetching
        itself is UNKNOWN -- iOS "holds no URL, no id format, and no
        bytes, because inventing a fetch scheme would be exactly the
        fabricated contract this work refuses to produce". Serving an
        inline image here would be the Tower inventing that scheme
        unilaterally. The field exists so that a later contract adds a
        payload where a `null` is, rather than adding a field.
        """
        count = None
        if metadata is not None and metadata.annotation_metric:
            total = run.metric_total(metadata.annotation_metric)
            if total is not None:
                count = int(round(total))
        return {
            "count": count,
            "count_unavailable_reason": (
                None
                if count is not None
                else "this experiment reports no annotation count"
            ),
            "artifact": None,
            "artifact_unavailable_reason": (
                "this Tower serves no imagery for CV Lab results. Every image "
                "must arrive stating its redaction treatment, and no artifact "
                "fetch contract exists on either side yet"
            ),
        }
