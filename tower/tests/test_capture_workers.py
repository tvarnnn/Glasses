"""The supervisor that attaches a worker to a capture, and reaps it.

Every one of these invariants is a defect observed on the 2026-08-24
physical walk, or a defect that walk would have produced had the
follower been started automatically.

The walk recorded TEN captures in 435 seconds:

    2e6cff  t=0.0   -> 121.9  1395 frames  disconnect  continues=None
                     ...105 s with no capture at all...
    341b0f  t=226.8 -> 256.9   259 frames  disconnect  continues=None
    b058a6  t=257.1 -> 263.5    18 frames  disconnect  continues=341b0f
    b1ab1d  t=263.6 -> 272.0    20 frames  stop        continues=b058a6
    79233e  t=272.0 -> 280.1    16 frames  disconnect  continues=None
    ...

Exactly two of those ten should start a worker: `2e6cff` and `341b0f`
(and `79233e`, which declares no predecessor because its predecessor
ended by a clean `stop`). The seven that name a predecessor must NOT,
because `CaptureFollower._await_successor` already chains the existing
worker into them. Spawning again would put two followers and two worlds
on one lineage, and the result channel -- which picks "a LIVE world if
one exists" -- would then have two to choose between.
"""

import subprocess

import pytest

from tower.capture_workers import CaptureWorkerSupervisor, WorkerSpec


class FakeProcess:
    """A Popen stand-in whose lifetime the test controls.

    Deliberately not a real subprocess: these tests are about the
    supervisor's bookkeeping, and a real process would make them slow,
    platform-dependent, and unable to express "this worker died".
    """

    def __init__(self, argv, **kwargs):
        self.args = list(argv)
        self.kwargs = kwargs
        self.pid = next(FakeProcess._pids)
        self._returncode = None
        self.terminated = False
        self.killed = False

    _pids = iter(range(1000, 100000))

    def poll(self):
        return self._returncode

    def wait(self, timeout=None):
        if self._returncode is None:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self._returncode

    def terminate(self):
        self.terminated = True
        self._returncode = -15

    def kill(self):
        self.killed = True
        self._returncode = -9

    # -- test controls --

    def exit_with(self, code):
        self._returncode = code


@pytest.fixture
def spawned():
    return []


@pytest.fixture
def supervisor(spawned, tmp_path):
    def spawn(argv, **kwargs):
        process = FakeProcess(argv, **kwargs)
        spawned.append(process)
        return process

    spec = WorkerSpec(
        argv=("python", "build.py", "--follow-capture", "{capture_dir}"),
        cwd=str(tmp_path),
    )
    return CaptureWorkerSupervisor(spec, spawn=spawn)


def _open(supervisor, tmp_path, capture_id, continues=None):
    directory = tmp_path / "captures" / capture_id
    directory.mkdir(parents=True, exist_ok=True)
    supervisor.capture_opened(capture_id, directory, continues=continues)
    return directory


# -- the core rule -----------------------------------------------------


def test_a_new_capture_starts_a_worker(supervisor, spawned, tmp_path):
    directory = _open(supervisor, tmp_path, "aaaa")

    assert len(spawned) == 1
    assert str(directory) in spawned[0].args, (
        "the worker was not told which capture to follow"
    )


def test_a_continuing_capture_does_not_start_a_second_worker(
    supervisor, spawned, tmp_path
):
    """The reconnect case, and the reason this class exists.

    `CaptureFollower` follows a capture ACROSS a reconnect by itself:
    seeing a capture close by disconnect, it waits out the 90 s grace
    window for a successor naming it and continues into that. A
    supervisor that spawned again on the successor would produce one
    lineage with two followers, two worlds, and two writer locks.
    """
    _open(supervisor, tmp_path, "aaaa")
    supervisor.capture_closed("aaaa")
    _open(supervisor, tmp_path, "bbbb", continues="aaaa")

    assert len(spawned) == 1, (
        "a reconnect spawned a second worker for one lineage"
    )


def test_lineage_is_followed_through_a_chain_of_successors(
    supervisor, spawned, tmp_path
):
    """b058a6 continues 341b0f; b1ab1d continues b058a6.

    The second successor names the FIRST successor, not the capture the
    worker was actually started on. A supervisor that only remembered
    the id it spawned with would spawn again here.
    """
    _open(supervisor, tmp_path, "341b0f")
    supervisor.capture_closed("341b0f")
    _open(supervisor, tmp_path, "b058a6", continues="341b0f")
    supervisor.capture_closed("b058a6")
    _open(supervisor, tmp_path, "b1ab1d", continues="b058a6")

    assert len(spawned) == 1, "the lineage chain was not tracked past one hop"


def test_a_capture_after_the_grace_window_starts_a_fresh_worker(
    supervisor, spawned, tmp_path
):
    """The 105-second gap on 2026-08-24.

    The recorder decides lineage, not the supervisor: past
    RESUME_GRACE_SECONDS it offers no predecessor, and `continues` is
    None. That is a NEW walk and it needs its own worker -- the previous
    one has already given up waiting and exited.
    """
    _open(supervisor, tmp_path, "2e6cff")
    supervisor.capture_closed("2e6cff")
    spawned[0].exit_with(0)

    _open(supervisor, tmp_path, "341b0f", continues=None)

    assert len(spawned) == 2, (
        "the second walk of the session got no worker, which is exactly "
        "the state that froze World Builder while the camera stayed LIVE"
    )


def test_a_successor_whose_worker_died_starts_a_fresh_worker(
    supervisor, spawned, tmp_path
):
    """A dead worker must not be mistaken for one that is still following.

    Suppression is conditional on the worker being ALIVE. If the
    follower crashed, the successor capture has nothing reading it, and
    declining to spawn would leave the rest of the walk unobserved.
    """
    _open(supervisor, tmp_path, "aaaa")
    spawned[0].exit_with(1)
    supervisor.capture_closed("aaaa")

    _open(supervisor, tmp_path, "bbbb", continues="aaaa")

    assert len(spawned) == 2


def test_an_unknown_predecessor_starts_a_worker(supervisor, spawned, tmp_path):
    """A Tower restarted mid-walk knows nothing of the previous lineage.

    `continues` names a capture this process never saw. The honest
    response is to follow the new capture rather than to assume some
    other process is handling it.
    """
    _open(supervisor, tmp_path, "bbbb", continues="never-seen")

    assert len(spawned) == 1


# -- placeholders, argv, and the disabled case -------------------------


def test_the_argv_template_is_filled(spawned, tmp_path):
    def spawn(argv, **kwargs):
        process = FakeProcess(argv, **kwargs)
        spawned.append(process)
        return process

    spec = WorkerSpec(
        argv=("py", "b.py", "--dir", "{capture_dir}", "--id", "{capture_id}"),
    )
    supervisor = CaptureWorkerSupervisor(spec, spawn=spawn)
    directory = tmp_path / "aaaa"
    directory.mkdir()
    supervisor.capture_opened("aaaa", directory, continues=None)

    assert spawned[0].args == [
        "py", "b.py", "--dir", str(directory), "--id", "aaaa"
    ]


def test_no_spec_means_no_worker_and_no_error(tmp_path):
    """A Tower with no world root configured supervises nothing.

    It must not raise, and it must not pretend to be running one:
    `enabled` is the honest answer to "will anything build a world?"
    """
    supervisor = CaptureWorkerSupervisor(None)

    assert not supervisor.enabled
    supervisor.capture_opened("aaaa", tmp_path, continues=None)
    supervisor.capture_closed("aaaa")
    supervisor.shutdown()
    assert supervisor.status() == []


# -- failure is reported, never swallowed ------------------------------


def test_a_worker_that_fails_to_spawn_does_not_break_the_stream(
    tmp_path, caplog
):
    """A capture must still record if nothing can build a world from it.

    The frame path is the product; world building is a side errand. But
    the failure has to be LOUD, because a follower that never started
    leaves the result channel with nothing to read, and iOS renders that
    as "no world" -- indistinguishable from "you have not walked yet".
    """
    def spawn(argv, **kwargs):
        raise OSError("the interpreter is not where you left it")

    supervisor = CaptureWorkerSupervisor(
        WorkerSpec(argv=("python", "b.py")), spawn=spawn
    )
    with caplog.at_level("ERROR"):
        supervisor.capture_opened("aaaa", tmp_path, continues=None)

    assert supervisor.status() == []
    assert any("aaaa" in record.getMessage() for record in caplog.records), (
        "a worker that could not start was not reported against its capture"
    )


def test_a_worker_exiting_nonzero_is_reported(supervisor, spawned, tmp_path, caplog):
    _open(supervisor, tmp_path, "aaaa")
    spawned[0].exit_with(2)

    with caplog.at_level("WARNING"):
        supervisor.reap()

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "aaaa" in messages and "2" in messages


def test_a_worker_exiting_cleanly_is_logged_but_not_as_a_failure(
    supervisor, spawned, tmp_path, caplog
):
    _open(supervisor, tmp_path, "aaaa")
    spawned[0].exit_with(0)

    with caplog.at_level("INFO"):
        supervisor.reap()

    assert not [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")]


# -- status, for /health and for the operator --------------------------


def test_status_names_the_capture_each_worker_follows(
    supervisor, spawned, tmp_path
):
    """"What capture is this world following?" answered without spelunking.

    Answering it on 2026-08-24 required listing capture directories by
    mtime and guessing.
    """
    _open(supervisor, tmp_path, "aaaa")

    (row,) = supervisor.status()
    assert row["capture_id"] == "aaaa"
    assert row["pid"] == spawned[0].pid
    assert row["alive"] is True


def test_status_drops_a_worker_once_it_has_exited(
    supervisor, spawned, tmp_path
):
    _open(supervisor, tmp_path, "aaaa")
    spawned[0].exit_with(0)
    supervisor.reap()

    assert supervisor.status() == []


# -- shutdown ----------------------------------------------------------


def test_shutdown_waits_before_terminating(supervisor, spawned, tmp_path):
    """A follower mid-build gets a chance to finish and release its lock.

    Terminating it outright leaves the writer lock behind, and the
    result channel then reports the world `failed` with a pid that is no
    longer running. That is an honest report of a state we caused
    unnecessarily.
    """
    _open(supervisor, tmp_path, "aaaa")
    spawned[0].exit_with(0)

    supervisor.shutdown(grace_seconds=0.01)

    assert not spawned[0].terminated


def test_shutdown_terminates_a_worker_that_will_not_exit(
    supervisor, spawned, tmp_path
):
    _open(supervisor, tmp_path, "aaaa")

    supervisor.shutdown(grace_seconds=0.01)

    assert spawned[0].terminated
    assert supervisor.status() == []
