"""More than one worker per capture, and one of them able to leave early.

The supervisor shipped able to run exactly one worker spec, because
exactly one thing wanted to follow a capture. A second cartridge wanting
the same frames is not a hypothetical any more -- Object Memory's whole
productisation gap was that its producer had to be started by hand in a
second terminal against a capture id a human copied out of a directory
listing -- and the single-spec supervisor could not have attached it
without displacing the world builder.

Three properties are new here and none of them existed before:

  * SEVERAL specs attach to one capture, and each keeps its own lineage
    bookkeeping. A dead world builder must not make the Tower think
    Object Memory is dead too.
  * A spec may be GATED. The gate is a plain predicate supplied by the
    wiring point, so the supervisor still knows nothing about what any
    argv computes -- it asks "should this one run right now" and does as
    it is told.
  * A spec may be attached LATE, to a capture that is already open, and
    detached again without touching the others. That is what a wearer
    pressing Start and Pause on one cartridge actually means.

The original single-spec tests stay exactly as they were and stay green:
`CaptureWorkerSupervisor(spec)` is still a legal call.
"""

import subprocess

import pytest

from tower.capture_workers import (
    ATTACH_MODE_FROM_NOW,
    ATTACH_MODE_FROM_START,
    CaptureWorkerSupervisor,
    WorkerSpec,
)


class FakeProcess:
    """A Popen stand-in whose lifetime the test controls."""

    _pids = iter(range(2000, 200000))

    def __init__(self, argv, **kwargs):
        self.args = list(argv)
        self.kwargs = kwargs
        self.pid = next(FakeProcess._pids)
        self._returncode = None
        self.terminated = False

    def poll(self):
        return self._returncode

    def wait(self, timeout=None):
        if self._returncode is None:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self._returncode

    def terminate(self):
        self.terminated = True
        self._returncode = -15

    def exit_with(self, code):
        self._returncode = code


@pytest.fixture
def spawned():
    return []


@pytest.fixture
def spawn(spawned):
    def _spawn(argv, **kwargs):
        process = FakeProcess(argv, **kwargs)
        spawned.append(process)
        return process

    return _spawn


def _spec(name, *, gate=None):
    return WorkerSpec(
        argv=("python", f"{name}.py", "--follow-capture", "{capture_dir}"),
        name=name,
        gate=gate,
    )


def _open(supervisor, tmp_path, capture_id, continues=None):
    directory = tmp_path / "captures" / capture_id
    directory.mkdir(parents=True, exist_ok=True)
    supervisor.capture_opened(capture_id, directory, continues=continues)
    return directory


def _names(spawned):
    return sorted(process.args[1] for process in spawned)


# -- several specs on one capture --------------------------------------


def test_every_spec_attaches_to_the_same_capture(spawn, spawned, tmp_path):
    supervisor = CaptureWorkerSupervisor(
        [_spec("builder"), _spec("memory")], spawn=spawn
    )

    _open(supervisor, tmp_path, "a")

    assert _names(spawned) == ["builder.py", "memory.py"]


def test_a_single_spec_is_still_a_legal_argument(spawn, spawned, tmp_path):
    """The call `main.py` has always made must keep working."""
    supervisor = CaptureWorkerSupervisor(_spec("builder"), spawn=spawn)

    _open(supervisor, tmp_path, "a")

    assert _names(spawned) == ["builder.py"]


def test_each_spec_keeps_its_own_lineage(spawn, spawned, tmp_path):
    """A successor restarts only the specs whose worker actually died.

    One follower chaining into a successor is the whole reason the
    supervisor tracks lineages. With two specs there are two answers to
    "is this lineage still being followed", and one of them being no must
    not restart the other.
    """
    supervisor = CaptureWorkerSupervisor(
        [_spec("builder"), _spec("memory")], spawn=spawn
    )
    _open(supervisor, tmp_path, "a")
    builder, memory = spawned[0], spawned[1]
    assert builder.args[1] == "builder.py"
    memory.exit_with(1)

    _open(supervisor, tmp_path, "b", continues="a")

    # The builder chained into `b` by itself and was not restarted; the
    # memory worker died, so nothing was following `b` for it.
    assert _names(spawned) == ["builder.py", "memory.py", "memory.py"]
    assert builder.poll() is None


def test_status_names_the_spec_each_worker_belongs_to(spawn, tmp_path):
    supervisor = CaptureWorkerSupervisor(
        [_spec("builder"), _spec("memory")], spawn=spawn
    )
    _open(supervisor, tmp_path, "a")

    rows = supervisor.status()

    assert sorted(row["worker"] for row in rows) == ["builder", "memory"]
    assert {row["capture_id"] for row in rows} == {"a"}


# -- gating ------------------------------------------------------------


def test_a_closed_gate_keeps_a_spec_off_the_capture(spawn, spawned, tmp_path):
    supervisor = CaptureWorkerSupervisor(
        [_spec("builder"), _spec("memory", gate=lambda: False)], spawn=spawn
    )

    _open(supervisor, tmp_path, "a")

    assert _names(spawned) == ["builder.py"]


def test_the_gate_is_asked_again_for_every_capture(spawn, spawned, tmp_path):
    """A gate is a live question, not a construction-time setting.

    A wearer who starts the cartridge between two captures must get a
    worker on the second one without the Tower being restarted.
    """
    open_gate = False
    supervisor = CaptureWorkerSupervisor(
        [_spec("memory", gate=lambda: open_gate)], spawn=spawn
    )

    _open(supervisor, tmp_path, "a")
    assert spawned == []

    open_gate = True
    _open(supervisor, tmp_path, "b")

    assert _names(spawned) == ["memory.py"]


def test_a_raising_gate_is_treated_as_closed(spawn, spawned, tmp_path):
    """A broken predicate must not start a worker, and must not end the stream.

    `capture_opened` runs on the connection that just received
    `stream_start`. An exception escaping it is a dropped recording, so
    the failure is contained here -- and contained CLOSED, because
    starting a producer whose enablement could not be established is the
    direction that writes data nobody asked for.
    """

    def broken():
        raise RuntimeError("no")

    supervisor = CaptureWorkerSupervisor(
        [_spec("builder"), _spec("memory", gate=broken)], spawn=spawn
    )

    _open(supervisor, tmp_path, "a")

    assert _names(spawned) == ["builder.py"]


# -- attaching late, and leaving early ---------------------------------


def test_attach_starts_one_named_spec_on_an_open_capture(spawn, spawned, tmp_path):
    supervisor = CaptureWorkerSupervisor(
        [_spec("builder"), _spec("memory", gate=lambda: False)], spawn=spawn
    )
    directory = _open(supervisor, tmp_path, "a")

    started = supervisor.attach("memory", "a", directory)

    assert started is True
    assert _names(spawned) == ["builder.py", "memory.py"]


def test_attach_tells_a_late_worker_that_it_arrived_late(spawn, spawned, tmp_path):
    """The distinction the whole flag exists for.

    A worker attached when the capture OPENED has seen every frame. A
    worker attached three minutes in has not, and must not decide for
    itself whether to go back and read them: a wearer who starts
    remembering at 15:03 has not asked for the 15:00 part of the walk to
    be remembered.
    """
    supervisor = CaptureWorkerSupervisor(
        [
            WorkerSpec(
                argv=("python", "memory.py", "--attach-mode", "{attach_mode}"),
                name="memory",
                gate=lambda: False,
            )
        ],
        spawn=spawn,
    )
    directory = _open(supervisor, tmp_path, "a")

    supervisor.attach("memory", "a", directory)

    assert spawned[0].args[-1] == ATTACH_MODE_FROM_NOW


def test_a_worker_attached_at_capture_open_is_told_it_saw_everything(
    spawn, spawned, tmp_path
):
    supervisor = CaptureWorkerSupervisor(
        [
            WorkerSpec(
                argv=("python", "memory.py", "--attach-mode", "{attach_mode}"),
                name="memory",
            )
        ],
        spawn=spawn,
    )

    _open(supervisor, tmp_path, "a")

    assert spawned[0].args[-1] == ATTACH_MODE_FROM_START


def test_attach_is_idempotent(spawn, spawned, tmp_path):
    """Double-tapping Start must not put two producers on one store."""
    supervisor = CaptureWorkerSupervisor([_spec("memory")], spawn=spawn)
    directory = _open(supervisor, tmp_path, "a")

    started = supervisor.attach("memory", "a", directory)

    assert started is False
    assert _names(spawned) == ["memory.py"]


def test_attach_to_an_unknown_spec_starts_nothing(spawn, spawned, tmp_path):
    supervisor = CaptureWorkerSupervisor([_spec("memory")], spawn=spawn)
    directory = tmp_path / "captures" / "a"
    directory.mkdir(parents=True)

    assert supervisor.attach("nobody", "a", directory) is False
    assert spawned == []


def test_detach_stops_only_the_named_spec(spawn, spawned, tmp_path):
    supervisor = CaptureWorkerSupervisor(
        [_spec("builder"), _spec("memory")], spawn=spawn
    )
    _open(supervisor, tmp_path, "a")
    builder, memory = spawned[0], spawned[1]

    stopped = supervisor.detach("memory", grace_seconds=0.0)

    assert stopped == 1
    assert memory.terminated is True
    assert builder.terminated is False
    assert [row["worker"] for row in supervisor.status()] == ["builder"]


def test_detach_lets_a_worker_finish_on_its_own(spawn, spawned, tmp_path):
    """Terminating is the fallback, not the first move.

    A producer mid-write is the case that matters: killed at the wrong
    moment it leaves the store with a half-written line, which every
    later read then skips as corruption.
    """
    supervisor = CaptureWorkerSupervisor([_spec("memory")], spawn=spawn)
    _open(supervisor, tmp_path, "a")
    spawned[0].exit_with(0)

    stopped = supervisor.detach("memory", grace_seconds=5.0)

    assert stopped == 1
    assert spawned[0].terminated is False


def test_detach_on_a_spec_with_no_workers_is_a_no_op(spawn, tmp_path):
    supervisor = CaptureWorkerSupervisor([_spec("memory")], spawn=spawn)

    assert supervisor.detach("memory", grace_seconds=0.0) == 0


def test_a_detached_spec_reattaches_on_the_next_capture(spawn, spawned, tmp_path):
    """Detaching stops workers; it does not disable the spec.

    Pause and Stop are the gate's business. If detach also latched the
    spec off, the gate would have a second, invisible source of truth and
    the two would disagree the first time either changed.
    """
    supervisor = CaptureWorkerSupervisor([_spec("memory")], spawn=spawn)
    _open(supervisor, tmp_path, "a")
    supervisor.detach("memory", grace_seconds=0.0)

    _open(supervisor, tmp_path, "b")

    assert _names(spawned) == ["memory.py", "memory.py"]


def test_shutdown_stops_every_spec(spawn, spawned, tmp_path):
    supervisor = CaptureWorkerSupervisor(
        [_spec("builder"), _spec("memory")], spawn=spawn
    )
    _open(supervisor, tmp_path, "a")

    supervisor.shutdown(grace_seconds=0.0)

    assert all(process.terminated for process in spawned)
    assert supervisor.status() == []


def test_shutdown_waits_on_every_worker_at_once_not_one_after_another(tmp_path):
    """Teardown must cost the slowest worker, not the sum of all of them.

    `_stop_worker` opens with `process.wait(timeout=grace_seconds)`, and
    `shutdown` ran those one after another while holding `self._lock`.
    Serially that is `N * (grace + TERMINATE_TIMEOUT_SECONDS)`. MEASURED
    on the real thing with two stubborn workers: 24.00 s, with a
    concurrent `status()` -- what `/health` calls -- blocked 23.95 s.

    Asserted by OBSERVED CONCURRENCY rather than by wall time. A timing
    assertion would measure the machine, and this suite already carries
    load-sensitive flakes; counting how many waits were in flight at once
    is the same claim without the flake.

    Nothing about the grace window changes: each worker still gets its
    own full wait and the same terminate-then-confirm sequence.
    """
    import threading

    barrier_state = {"live": 0, "peak": 0}
    lock = threading.Lock()
    release = threading.Event()

    class SlowProcess:
        _pids = iter(range(50_000, 60_000))

        def __init__(self, argv, **kwargs):
            self.args = list(argv)
            self.pid = next(SlowProcess._pids)
            self._returncode = None
            self.terminated = False

        def poll(self):
            return self._returncode

        def wait(self, timeout=None):
            if self._returncode is not None:
                return self._returncode
            with lock:
                barrier_state["live"] += 1
                barrier_state["peak"] = max(
                    barrier_state["peak"], barrier_state["live"]
                )
            try:
                # Held until every wait has arrived. Serial code deadlocks
                # here and the test times out rather than passing quietly.
                release.wait(timeout=5.0)
            finally:
                with lock:
                    barrier_state["live"] -= 1
            raise subprocess.TimeoutExpired(self.args, timeout)

        def terminate(self):
            self.terminated = True
            self._returncode = -15

        def kill(self):
            self._returncode = -9

    spawned = []

    def spawn(argv, **kwargs):
        process = SlowProcess(argv, **kwargs)
        spawned.append(process)
        return process

    supervisor = CaptureWorkerSupervisor(
        [_spec("builder"), _spec("memory")], spawn=spawn
    )
    _open(supervisor, tmp_path, "a")
    assert len(spawned) == 2

    def unblock():
        # Let the waits sit together long enough to be counted, then free
        # them so the test cannot hang if the code IS serial.
        import time

        time.sleep(0.5)
        release.set()

    releaser = threading.Thread(target=unblock)
    releaser.start()
    supervisor.shutdown(grace_seconds=1.0)
    releaser.join()

    assert barrier_state["peak"] == 2, (
        f"only {barrier_state['peak']} worker wait was in flight at a time; "
        f"teardown still costs the SUM of every worker's grace window"
    )
    assert all(process.terminated for process in spawned)
    assert supervisor.status() == []


def test_enabled_is_false_only_when_nothing_is_configured(spawn):
    assert CaptureWorkerSupervisor(None).enabled is False
    assert CaptureWorkerSupervisor([]).enabled is False
    assert CaptureWorkerSupervisor([_spec("memory")], spawn=spawn).enabled is True


def test_worker_names_lists_what_could_ever_be_attached(spawn):
    supervisor = CaptureWorkerSupervisor(
        [_spec("builder"), _spec("memory")], spawn=spawn
    )

    assert supervisor.worker_names() == ("builder", "memory")


def test_two_specs_may_not_share_a_name(spawn):
    """`attach` and `detach` address a spec BY NAME.

    Two specs called the same thing make both calls ambiguous, and the
    ambiguity would only ever surface as one cartridge's Pause silently
    stopping another's producer.
    """
    with pytest.raises(ValueError):
        CaptureWorkerSupervisor([_spec("memory"), _spec("memory")], spawn=spawn)


class TestAWorkerThatWillNotDie:
    """Forgetting a worker that could not be terminated makes an orphan.

    Invisible to `status`, to `/health` and to the next `shutdown` -- and
    a reviewer measured three Stop/Start cycles leaving four producers
    alive with the supervisor aware of one.
    """

    class Immortal(FakeProcess):
        def terminate(self):
            raise PermissionError("access is denied")

    def test_it_stays_in_the_registry(self, tmp_path):
        supervisor = CaptureWorkerSupervisor(
            [_spec("memory")],
            spawn=lambda argv, **kwargs: self.Immortal(argv, **kwargs),
        )
        _open(supervisor, tmp_path, "a")

        stopped = supervisor.detach("memory", grace_seconds=0.0)

        assert stopped == 0
        assert [row["worker"] for row in supervisor.status()] == ["memory"]

    def test_and_nothing_is_attached_in_its_place(self, tmp_path):
        """A second producer on one store loses the first one's writes."""
        spawned = []

        def spawn(argv, **kwargs):
            process = self.Immortal(argv, **kwargs)
            spawned.append(process)
            return process

        supervisor = CaptureWorkerSupervisor([_spec("memory")], spawn=spawn)
        _open(supervisor, tmp_path, "a")
        supervisor.detach("memory", grace_seconds=0.0)

        supervisor.attach("memory", "a", tmp_path / "captures" / "a")

        assert len(spawned) == 1
