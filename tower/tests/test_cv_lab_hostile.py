"""Ways the Lab could be made to lie, crash, or take the frame path with it.

Not "does it work". Every test here is a defect an adversarial reviewer
went looking for, written down so that reintroducing it fails a gate:

* a status read from the poller thread racing a switch on the loop, and
  seeing half of each;
* an experiment returning something that is not an `ExperimentResult`,
  killing a module whose FAILED state is terminal;
* a `describe()` that raises during a status build;
* two connections driving one Lab;
* the result channel's poller mutating what it reports;
* a subscription outliving its socket and keeping the Lab awake.
"""

import asyncio
import json
import threading

import pytest

from tests.cv_lab_fixtures import (  # noqa: F401
    _close_cv_lab_clients,
    armed_lab,
    command,
    drain,
    frame,
    jpeg_bytes,
    make_client,
    pump,
)
from tower.cv_lab.contracts import LIFECYCLE_STATES
from tower.modules.base import FrameProcessingError


# -- the frame path survives a bad experiment ---------------------------


def test_a_result_that_is_not_an_experiment_result_does_not_kill_the_module():
    """`mark_failed()` is TERMINAL and the container is built once at
    process start. A single odd frame must not end CV processing for the
    life of the server, so attribution degrades rather than raising."""

    class _Odd:
        name = "odd"

        def load(self, settings):
            return None

        def run(self, raw_bytes):
            return "not a result"

        def release(self):
            return None

    lab = asyncio.run(armed_lab("baseline", experiment=_Odd()))
    assert lab.process(jpeg_bytes()) == "not a result"
    assert lab.frame_provenance() is None
    # Still running, still counting, still answering.
    assert lab.status()["lifecycle"]["state"] == "running"
    assert lab.status()["run"]["frames_processed"] == 1


def test_a_describe_that_raises_does_not_break_the_status_document():
    class _Rude:
        name = "rude"

        def load(self, settings):
            return None

        def run(self, raw_bytes):
            raise AssertionError("never called")

        def release(self):
            return None

        def describe(self):
            raise RuntimeError("no")

    lab = asyncio.run(armed_lab("baseline", experiment=_Rude()))
    assert lab.status()["run"]["runtime"] == {}


def test_describe_output_is_bounded_and_stringified():
    """A diagnostic block is not a channel for an experiment to put
    arbitrary objects on the wire."""

    class _Chatty:
        name = "chatty"

        def load(self, settings):
            return None

        def run(self, raw_bytes):
            raise AssertionError("never called")

        def release(self):
            return None

        def describe(self):
            return {f"k{i}": object() for i in range(40)}

    lab = asyncio.run(armed_lab("baseline", experiment=_Chatty()))
    runtime = lab.status()["run"]["runtime"]
    assert len(runtime) <= 8
    json.dumps(runtime)  # must be serialisable


def test_a_release_that_raises_does_not_stop_a_switch():
    class _Sticky:
        name = "sticky"

        def load(self, settings):
            return None

        def run(self, raw_bytes):
            raise AssertionError("never called")

        def release(self):
            raise RuntimeError("will not let go")

    async def scenario():
        lab = await armed_lab("baseline", experiment=_Sticky())
        outcome = lab.start("edge_detection")
        await lab.wait_until_armed()
        return lab, outcome

    lab, outcome = asyncio.run(scenario())
    assert outcome.accepted is True
    assert lab.status()["selected"] == "edge_detection"
    assert lab.process(jpeg_bytes()).result_label == "edge_density"


def test_a_non_finite_measurement_never_reaches_the_wire(monkeypatch):
    """`NaN` is not JSON. Python emits it bare and Swift's decoder is
    strict, so ONE of them makes the whole message unparseable -- not one
    field degraded, every result for that session lost."""
    from tower.experiments import ExperimentResult
    from tower.results.envelope import json_safe

    lab = asyncio.run(armed_lab("frame_quality"))
    lab._run.record_result(
        ExperimentResult(
            result_value=float("nan"),
            result_label="sharpness_laplacian_var",
            processing_ms=float("inf"),
            stage_ms={},
            metrics={"edge_density": float("nan")},
        ),
        now=1.0,
    )
    encoded = json.dumps(json_safe(lab.status()))
    assert "NaN" not in encoded
    assert "Infinity" not in encoded


# -- concurrency --------------------------------------------------------


def test_a_status_read_from_another_thread_never_sees_half_a_switch():
    """The poller computes snapshots with `asyncio.to_thread`, so
    `status()` runs concurrently with the loop that mutates the Lab. A
    document naming a run that does not exist, or a state with no
    experiment behind it, is the failure this guards."""

    async def scenario():
        lab = await armed_lab("baseline")
        stop = threading.Event()
        seen = []
        errors = []

        def reader():
            while not stop.is_set():
                try:
                    status = lab.status()
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
                    return
                seen.append(
                    (
                        status["lifecycle"]["state"],
                        status["lifecycle"]["run_id"],
                        None if status["run"] is None else status["run"]["run_id"],
                        status["selected"],
                    )
                )

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        try:
            for experiment_id in ("edge_detection", "baseline") * 6:
                lab.start(experiment_id)
                await lab.wait_until_armed()
        finally:
            stop.set()
            thread.join(5)
        return seen, errors

    seen, errors = asyncio.run(scenario())

    assert errors == []
    assert len(seen) > 10, "the reader never got a look in"
    for state, lifecycle_run, run_run, selected in seen:
        assert state in LIFECYCLE_STATES
        # The run named by the lifecycle IS the run in the document. Two
        # fields read a microsecond apart must not disagree.
        assert lifecycle_run == run_run
        assert selected in ("baseline", "edge_detection")


def test_frames_and_a_switch_never_produce_a_misattributed_result():
    """The one failure that makes a bench useless and looks like nothing."""

    async def scenario():
        lab = await armed_lab("baseline")
        attributions = []
        for experiment_id in ("edge_detection", "baseline", "edge_detection"):
            lab.start(experiment_id)
            for _ in range(3):
                try:
                    result = lab.process(jpeg_bytes())
                except FrameProcessingError:
                    continue
                provenance = lab.frame_provenance()
                attributions.append((provenance["experiment_id"], result.result_label))
            await lab.wait_until_armed()
            for _ in range(3):
                result = lab.process(jpeg_bytes())
                provenance = lab.frame_provenance()
                attributions.append((provenance["experiment_id"], result.result_label))
        return attributions

    from tower.experiments import experiment_metadata

    for experiment_id, label in asyncio.run(scenario()):
        assert label == experiment_metadata(experiment_id).headline_label


def test_two_connections_drive_one_lab_and_both_see_it(monkeypatch):
    """One module, one slot, one experiment. Two clients is a social
    problem, not a protocol one -- but neither may be shown a stale
    picture of what the other did."""
    client = make_client(monkeypatch, "baseline")
    with client.websocket_connect("/ws") as first:
        with client.websocket_connect("/ws") as second:
            command(second, {"type": "cv_lab_start", "experiment_id": "edge_detection"})
            seen_by_first = command(first, {"type": "cv_lab_status"})["status"]
            assert seen_by_first["selected"] == "edge_detection"
            assert seen_by_first["source"]["clients_connected"] == 2

            # And a frame from the OTHER connection runs the experiment
            # the second one chose.
            replies = [frame(first, seq) for seq in range(1, 6)]

    labels = {reply.get("result_label") or reply.get("reason") for reply in replies}
    assert labels <= {"edge_density", "cv_lab_starting"}


def test_a_run_counts_frames_from_every_connection(monkeypatch):
    client = make_client(monkeypatch, "baseline")
    with client.websocket_connect("/ws") as first:
        with client.websocket_connect("/ws") as second:
            frame(first, 1)
            frame(second, 2)
            status = command(first, {"type": "cv_lab_status"})["status"]

    assert status["run"]["frames_processed"] == 2


# -- the result channel does not touch what it reports ------------------


def test_polling_the_channel_changes_nothing_about_the_lab(monkeypatch):
    client = make_client(monkeypatch, "baseline")
    lab = client.app.state.cv_lab
    with client.websocket_connect("/ws") as ws:
        frame(ws, 1)
        # Frozen AFTER the frame, so the two documents differ only if
        # polling changed something. Elapsed time and the rates derived
        # from it advance on their own, and popping them one by one would
        # be choosing which parts of the claim to check.
        lab._clock = lambda: 10_000.0
        before = json.dumps(lab.status(), sort_keys=True)
        ws.send_json(
            {
                "type": "result_subscribe",
                "cartridge": "experimental_cv",
                "result_type": "status",
            }
        )
        drain(ws, "result_subscribed")
        drain(ws, "cartridge_result")
        pump(client, times=5)
        after = json.loads(json.dumps(lab.status()))

    assert json.loads(before) == after


def test_the_module_container_is_untouched_by_a_cv_lab_subscription(monkeypatch):
    client = make_client(monkeypatch, "baseline")
    container = client.app.state.module_container
    before = (container.state.value, container.descriptor.id)

    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {
                "type": "result_subscribe",
                "cartridge": "experimental_cv",
                "result_type": "status",
            }
        )
        drain(ws, "result_subscribed")
        drain(ws, "cartridge_result")
        pump(client, times=3)

    assert (container.state.value, container.descriptor.id) == before


def test_a_subscription_does_not_outlive_its_socket(monkeypatch):
    """A subscription that outlived its socket would keep the shared
    reader working on behalf of a client that is gone."""
    client = make_client(monkeypatch, "baseline")
    hub = client.app.state.result_hub

    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {
                "type": "result_subscribe",
                "cartridge": "experimental_cv",
                "result_type": "status",
            }
        )
        drain(ws, "result_subscribed")
        drain(ws, "cartridge_result")
        assert hub._channels

    async def _settle():
        for _ in range(4):
            await asyncio.sleep(0)

    client.portal.call(_settle)
    assert not hub._channels


def test_the_frame_path_still_answers_when_the_channel_is_broken(monkeypatch):
    """The result channel is a side surface. It must be able to fail
    without implicating the path that answers frames."""
    client = make_client(monkeypatch, "baseline")

    def _explode(*args, **kwargs):
        raise RuntimeError("the reader is dead")

    client.app.state.result_hub._snapshot_for = _explode

    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {
                "type": "result_subscribe",
                "cartridge": "experimental_cv",
                "result_type": "status",
            }
        )
        error = drain(ws, "result_error")
        assert error["reason"] == "snapshot_failed"
        assert frame(ws, 1)["type"] == "frame_result"


# -- hostile control input ----------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        {"type": "cv_lab_start", "experiment_id": {"a": 1}},
        {"type": "cv_lab_start", "experiment_id": "../../etc/passwd"},
        {"type": "cv_lab_start", "experiment_id": "x" * 5000},
        {"type": "cv_lab_pause", "run_id": ["a"]},
        {"type": "cv_lab_stop", "run_id": 3.5},
        {"type": "cv_lab_resume", "run_id": ""},
    ],
)
def test_hostile_control_input_is_refused_and_the_socket_survives(
    monkeypatch, message
):
    client = make_client(monkeypatch, "baseline")
    with client.websocket_connect("/ws") as ws:
        ws.send_json(message)
        error = drain(ws, "cv_lab_error")
        assert error["reason"] in (
            "malformed_request",
            "unknown_experiment",
            "invalid_state",
            "stale_run",
        )
        assert frame(ws, 1)["type"] == "frame_result"


def test_an_experiment_id_that_is_not_registered_never_reaches_a_factory(
    monkeypatch,
):
    """The registry is the only gate. A path-shaped id must be refused as
    a name, not resolved as one."""
    lab = asyncio.run(armed_lab("baseline"))
    outcome = lab.start("../../tower/experiments/depth")
    assert outcome.reason == "unknown_experiment"
    assert lab.process(jpeg_bytes()).result_label == "mean_intensity"
