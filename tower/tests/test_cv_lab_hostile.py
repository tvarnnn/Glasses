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
    jpeg_message,
    make_client,
    pump,
)
from tower.cv_lab.contracts import LIFECYCLE_STATES
from tower.modules.base import FrameProcessingError


def _run(experiment_id="baseline"):
    from tower.cv_lab.run import LabRun

    return LabRun(
        run_id="r1",
        experiment_id=experiment_id,
        descriptor={"id": experiment_id},
        origin="client_request",
        started_at=0.0,
    )


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


# -- findings from the 2026-08-27 adversarial review --------------------
#
# Every test below pins a defect two independent reviewers found in the
# first cut of this contract. They are grouped here rather than scattered
# because the common thread is the same one: the Tower said something it
# could not back.


def test_a_non_finite_measurement_never_reaches_ANY_surface(monkeypatch):
    """The first version sanitised one of the three surfaces.

    `json_safe` lived at the result channel's envelope boundary, which is
    the right place when the envelope is the only way out. It is not:
    `GET /cv-lab` goes through Starlette with `allow_nan=False` and
    answered **500**, and `cv_lab_status` goes through `send_json`, whose
    `allow_nan` defaults True and put a bare `NaN` on the wire for a
    strict decoder to reject the entire message over. Three different
    failures from one non-finite float, and a poisoned RATE accumulator
    never recovers, so the message stays undecodable for the rest of the
    session. Sanitising where the document is BUILT covers all three.
    """
    from tower.experiments import ExperimentResult

    client = make_client(monkeypatch, "frame_quality")
    lab = client.app.state.cv_lab
    lab._run.record_result(
        ExperimentResult(
            result_value=float("nan"),
            result_label="sharpness_laplacian_var",
            processing_ms=float("inf"),
            stage_ms={"decode": float("nan")},
            metrics={"edge_density": float("nan")},
        ),
        now=1.0,
    )

    # 1. the Lab own document
    assert "NaN" not in json.dumps(lab.status())

    # 2. HTTP -- would have been a 500
    response = client.get("/cv-lab")
    assert response.status_code == 200
    assert "NaN" not in response.text

    # 3. the socket, and 4. the result channel
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "cv_lab_status"})
        assert "NaN" not in json.dumps(drain(ws, "cv_lab_status"))
        ws.send_json(
            {
                "type": "result_subscribe",
                "cartridge": "experimental_cv",
                "result_type": "status",
            }
        )
        drain(ws, "result_subscribed")
        assert "NaN" not in json.dumps(drain(ws, "cartridge_result"))


def test_the_revision_does_not_change_when_nothing_happened(monkeypatch):
    """`revision_changed` is defined as news, not a heartbeat.

    `elapsed_s` and the two throughput rates derived from it advance with
    wall clock, so hashing the whole payload produced a new revision on
    every poll -- twice a second on a Lab that had seen no frame at all,
    and a client that redraws on `revision_changed` redrew continuously.
    """
    from tower.results.experimental_cv import (
        VOLATILE_PATHS,
        ExperimentalCVStatusProducer,
    )

    clock = [1000.0]
    client = make_client(monkeypatch, "baseline")
    lab = client.app.state.cv_lab
    lab._clock = lambda: clock[0]
    lab.process(jpeg_bytes())

    producer = ExperimentalCVStatusProducer(lab)
    first = producer.snapshot()
    # Inside the stream-idle window, so nothing has become true that was
    # not true before -- only the clock moved.
    clock[0] += 1.0
    assert producer.snapshot().revision == first.revision, "time alone is not news"

    # A frame IS news.
    lab.process(jpeg_bytes(textured=True))
    after_frame = producer.snapshot()
    assert after_frame.revision != first.revision

    # And so is frames STOPPING. `receiving_frames` flips with no frame
    # arriving, and is deliberately NOT excluded from the hash: it flips
    # precisely because frames stopped, which is the thing a person
    # standing there wants to be told.
    clock[0] += 10.0
    stale = producer.snapshot()
    assert stale.payload["source"]["receiving_frames"] is False
    assert stale.revision != after_frame.revision

    # The excluded paths are still ON the wire -- excluded from the hash,
    # not from the payload. A client that wants a live rate still has one.
    payload = producer.snapshot().payload
    assert payload["run"]["elapsed_s"] is not None
    assert set(VOLATILE_PATHS) == {
        "run.elapsed_s",
        "run.throughput.processed_fps",
        "run.throughput.offered_fps",
    }


def test_a_refusal_on_a_tower_with_no_lab_still_carries_a_status(monkeypatch):
    """The contract says every `cv_lab_error` carries `status`, so a
    hand-written decoder is entitled to require it. This branch omitted
    it -- on exactly the Tower configuration the refusal describes."""
    client = make_client(monkeypatch)
    client.app.state.cv_lab = None
    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {"type": "cv_lab_start", "experiment_id": "baseline", "request_id": "r1"}
        )
        error = drain(ws, "cv_lab_error")

    assert error["reason"] == "lab_unavailable"
    assert error["request_id"] == "r1"
    status = error["status"]
    assert status["lifecycle"]["state"] == "unavailable"
    # Real identifiers, not null. They describe what this BUILD speaks,
    # which is true whether or not a Lab is loaded -- and an identifier
    # compared for equality that can never equal anything is worse than
    # no identifier at all.
    assert status["contract"] == "experimental_cv.status/2026-08-27"
    assert status["control_contract"] == "experimental_cv.control/2026-08-27"


def test_a_handler_failure_is_answered_rather_than_swallowed(monkeypatch):
    """A client that sent a `request_id` and got nothing back waits
    forever, which this module own header calls the worst outcome."""
    client = make_client(monkeypatch)

    class _Exploding:
        def status(self):
            raise RuntimeError("no")

        def start(self, *args, **kwargs):
            raise RuntimeError("no")

    client.app.state.cv_lab = _Exploding()
    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {"type": "cv_lab_start", "experiment_id": "baseline", "request_id": "r2"}
        )
        error = drain(ws, "cv_lab_error")
        assert error["request_id"] == "r2"
        assert error["command"] == "cv_lab_start"
        # And the connection is still answering frames.
        assert frame(ws, 1)["type"] == "frame_result"


def test_a_client_cannot_choose_the_size_of_a_message_we_send(monkeypatch):
    """`request_id` is capped because it is echoed onto the wire. An
    `experiment_id` embedded in a refusal message is echoed too."""
    client = make_client(monkeypatch)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "cv_lab_start", "experiment_id": "x" * 5000})
        error = drain(ws, "cv_lab_error")
        assert len(error["message"]) < 300
        ws.send_json({"type": "cv_lab_stop", "run_id": "y" * 5000})
        error = drain(ws, "cv_lab_error")
        assert len(error["message"]) < 300


def test_a_deliberate_refusal_is_not_counted_as_a_processing_error(monkeypatch):
    """A Lab paused for five minutes with a phone still streaming used to
    report hundreds of `frame_processing_errors` in its session summary --
    after this change split refusal from failure everywhere else.

    Driven through the wire so the counting rule is exercised where it is
    applied, then read back off the session metrics the same connection
    filled in.
    """
    client = make_client(monkeypatch, "baseline")
    seen = {}
    real_finalize = None

    import tower.routes.ws as ws_module

    real_finalize = ws_module._finalize_stream_measurement

    def capture(metrics, end_reason):
        seen.update(metrics.snapshot())
        return real_finalize(metrics, end_reason)

    monkeypatch.setattr(ws_module, "_finalize_stream_measurement", capture)

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "stream_start"})
        command(ws, {"type": "cv_lab_pause"})
        for seq in range(1, 6):
            assert frame(ws, seq)["reason"] == "cv_lab_paused"
        # An undecodable frame IS a processing error, and still counts.
        ws.send_json(
            {
                "type": "frame",
                "seq": 99,
                "width": 16,
                "height": 16,
                "format": "jpeg",
                "data": "////",
            }
        )
        ws.receive_json()
        command(ws, {"type": "cv_lab_resume"})
        assert frame(ws, 100)["type"] == "frame_result"
        ws.send_json({"type": "stream_stop"})
        command(ws, {"type": "cv_lab_status"})

    # Six frames never reached the numbers: five refusals and one bad
    # JPEG. Only the bad JPEG was a FAILURE.
    assert seen["frames_rejected"] == 6
    assert seen["frame_processing_errors"] <= 1
    assert seen["frames_received"] == 1


def test_garbage_frames_look_different_from_no_frames(monkeypatch):
    """The one condition the status document could not express.

    A frame the transport cannot decode never reaches the Lab, so
    `frames_offered_total` does not count it. Without a separate count, a
    phone streaming broken JPEGs reads exactly like a phone that is not
    streaming -- and those need opposite fixes. The answer used to be a
    server-side log line, which is what `GET /cv-lab` exists because
    nobody can see over Tailscale.
    """
    client = make_client(monkeypatch, "baseline")
    lab = client.app.state.cv_lab

    quiet = lab.status()["source"]
    assert quiet["frames_offered_total"] == 0
    assert quiet["frames_rejected_before_lab"] == 0
    assert quiet["receiving_frames"] is False

    with client.websocket_connect("/ws") as ws:
        for seq in range(1, 4):
            ws.send_json(
                {
                    "type": "frame",
                    "seq": seq,
                    "width": 16,
                    "height": 16,
                    "format": "jpeg",
                    "data": "////",
                }
            )
            assert ws.receive_json()["reason"] in ("invalid_frame", "frame_skipped")

    noisy = lab.status()["source"]
    assert noisy["frames_rejected_before_lab"] >= 1
    # And a malformed frame is still evidence that something is streaming.
    assert noisy["receiving_frames"] is True
    assert noisy["last_frame_at"] is not None


# -- the 2026-08-27 verification pass -----------------------------------
#
# A third reviewer checked the fixes above and found that one of them was
# the wrong shape: sanitising the DOCUMENT is not sanitising the LAB, and
# it protected neither the frame path nor the builder. These pin what
# that cost.


def test_a_non_finite_result_never_reaches_the_wire_on_frame_result(monkeypatch):
    """The highest-volume message on this socket, and it was unprotected.

    `json_safe` was applied at the result channel's envelope, then at the
    Lab's document builder -- and between them `frame_result` still
    emitted a bare `NaN` for any experiment that produced one. A strict
    decoder rejects the whole message, so it is not one field degraded,
    it is every result on that connection lost. The sanitiser now lives
    at the SOCKET, which is the only place that covers every message by
    construction, including the next one somebody adds.
    """
    from tower.experiments import ExperimentResult

    class _NonFinite:
        name = "nonfinite"

        def load(self, settings):
            return None

        def run(self, raw_bytes):
            return ExperimentResult(
                result_value=float("inf"),
                result_label="edges",
                processing_ms=float("nan"),
                stage_ms={"decode": float("nan")},
                mean_intensity=float("-inf"),
                metrics={"density": float("nan")},
            )

        def release(self):
            return None

    client = make_client(monkeypatch, "baseline")
    client.app.state.cv_lab._experiment = _NonFinite()

    with client.websocket_connect("/ws") as ws:
        ws.send_json(jpeg_message(1))
        raw = ws.receive_text()

    assert "NaN" not in raw
    assert "Infinity" not in raw
    # And it is still decodable, with the non-finite values nulled rather
    # than the message lost.
    reply = json.loads(raw)
    assert reply["type"] == "frame_result"
    assert reply["result_value"] is None
    assert reply["processing_ms"] is None
    assert reply["cv_lab"]["processing_ms"] is None


def test_a_non_finite_annotation_count_does_not_take_the_document_down(
    monkeypatch,
):
    """`int(round(nan))` RAISES, and `json_safe` cannot help.

    It wraps the FINISHED document, so it cannot protect a computation
    that happens while the document is being built. One non-finite
    detection count made `status()` raise -- 500 on the HTTP surface, an
    error on the socket, `snapshot_failed` on the channel -- permanently
    for that run, because the accumulator never resets.
    """
    from tower.experiments import ExperimentResult

    client = make_client(monkeypatch, "baseline")
    lab = client.app.state.cv_lab
    lab._run.experiment_id = "object_detection"
    lab._run.descriptor = dict(lab._run.descriptor, id="object_detection")
    lab._run.record_result(
        ExperimentResult(
            result_value=1.0,
            result_label="detections",
            processing_ms=1.0,
            stage_ms={},
            metrics={"detections": float("nan")},
        ),
        now=1.0,
    )

    status = lab.status()
    assert status["run"]["annotation"]["count"] is None
    assert client.get("/cv-lab").status_code == 200


def test_a_message_whose_type_is_not_a_string_does_not_kill_the_connection(
    monkeypatch,
):
    """`message_type in <frozenset>` raises TypeError on an unhashable
    dict, and nothing caught it: one malformed message killed a
    connection that was answering frames."""
    client = make_client(monkeypatch, "baseline")
    with client.websocket_connect("/ws") as ws:
        for hostile in ({"nested": 1}, ["a"], 7, None, 3.5):
            ws.send_json({"type": hostile})
        # Still alive, still answering.
        assert frame(ws, 1)["type"] == "frame_result"


def test_an_internal_failure_is_transient_and_carries_a_status(monkeypatch):
    """`lab_unavailable` is terminal -- iOS renders it as "this Tower
    cannot do this". A handler bug is not that, and the refusal must
    carry a document like every other one."""
    client = make_client(monkeypatch)

    class _Exploding:
        def status(self):
            raise RuntimeError("no")

        def start(self, *args, **kwargs):
            raise RuntimeError("no")

    client.app.state.cv_lab = _Exploding()
    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {"type": "cv_lab_start", "experiment_id": "baseline", "request_id": "r9"}
        )
        error = drain(ws, "cv_lab_error")

    assert error["reason"] == "internal_error"
    assert error["request_id"] == "r9"
    # A status, even though the thing that failed was `status()` itself.
    assert error["status"]["lifecycle"]["state"] == "unavailable"
    assert error["status"]["contract"] == "experimental_cv.status/2026-08-27"


def test_stage_names_are_bounded(monkeypatch):
    """`_metrics` is bounded by the experiment's declaration; a STAGE name
    is whatever was passed to `StageTimer`, with nothing declaring it. An
    experiment naming a stage per frame grew this to 926,280 entries over
    15,438 frames before it was bounded."""
    from tower.cv_lab.contracts import MAX_TRACKED_STAGES
    from tower.experiments import ExperimentResult

    run = _run("baseline")
    for index in range(MAX_TRACKED_STAGES * 20):
        run.record_result(
            ExperimentResult(
                result_value=1.0,
                result_label="mean_intensity",
                processing_ms=1.0,
                stage_ms={f"stage_{index}": 1.0},
            ),
            now=1.0,
        )

    assert len(run.stage_ms) == MAX_TRACKED_STAGES
    assert run.stages_rejected > 0


def test_an_over_long_message_type_is_not_echoed_whole(monkeypatch):
    """`protocol_error` echoed the client's own `type` verbatim: a
    50,000-character type produced a 50,000-character reply."""
    client = make_client(monkeypatch, "baseline")
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "Z" * 50000})
        error = drain(ws, "protocol_error")
        assert len(error["message_type"]) <= 120
        assert frame(ws, 1)["type"] == "frame_result"


def test_an_over_long_seq_is_not_echoed_whole(monkeypatch):
    """A `frame` can fail validation before `seq` has been checked, so
    whatever arrived is what gets echoed back."""
    client = make_client(monkeypatch, "baseline")
    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {
                "type": "frame",
                "seq": "Q" * 40000,
                "width": 16,
                "height": 16,
                "format": "jpeg",
                "data": "////",
            }
        )
        error = drain(ws, "frame_error")
        assert len(str(error["seq"])) <= 120
        assert frame(ws, 1)["type"] == "frame_result"


def test_the_four_counters_are_read_as_one_consistent_triple(monkeypatch):
    """`frames_offered` is derived from the SAME reads it publishes.

    Reading the derived property and then the three attributes separately
    was atomic only by accident of CPython's scheduling; four reads of one
    triple are atomic by construction.
    """
    import threading

    client = make_client(monkeypatch, "baseline")
    lab = client.app.state.cv_lab
    payload = jpeg_bytes()
    stop = threading.Event()
    violations = []

    def reader():
        while not stop.is_set():
            run = lab.status()["run"]
            if (
                run["frames_processed"]
                + run["frames_refused"]
                + run["frames_failed"]
                != run["frames_offered"]
            ):
                violations.append(run)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    try:
        for index in range(3000):
            try:
                lab.process(b"" if index % 7 == 0 else payload)
            except Exception:
                pass
    finally:
        stop.set()
        thread.join(5)

    assert violations == []
