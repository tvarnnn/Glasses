"""The live preview: bounded, latest-only, and unable to slow a frame down.

Four things this file is here to make true rather than to hope for.

1. **Nothing grows.** One capture and one encoding exist at a time, for
   the length of a run that `handoff.md` 9.3 says may never end. No list,
   no queue, no directory.
2. **A picture from run A never appears under run B's name.** Three
   independent guards -- run identity, an epoch, and age -- and a test
   for each, because the value of three is that no one of them is
   trusted alone.
3. **A broken picture costs a picture.** Not a run, not a module, and
   certainly not `ModuleContainer.mark_failed()`, which is terminal.
4. **A consumer that stops consuming costs nothing that accumulates.**
   The frames it missed were dropped when they were replaced, not queued
   against its return.
"""

import asyncio
import gc
import json

import cv2
import numpy as np
import pytest

from tests.cv_lab_fixtures import (  # noqa: F401
    _close_cv_lab_clients,
    armed_lab,
    jpeg_bytes,
    make_client,
    start_and_wait,
)
from tower.cv_lab.contracts import (
    PREVIEW_DISABLED,
    PREVIEW_MAX_EDGE_PX,
    PREVIEW_NONE_YET,
    PREVIEW_NOT_VISUAL,
    PREVIEW_RUN_CHANGED,
    PREVIEW_STALE,
    TREATMENT_RAW_EPHEMERAL,
)
from tower.cv_lab.preview import (
    LivePreview,
    PreviewNotModified,
    PreviewPolicy,
    PreviewRefusal,
    RenderedPreview,
)
from tower.experiments import (
    EXPERIMENTS,
    PREVIEW_KINDS,
    PREVIEW_STRUCTURE_MAX_EDGE_PX,
    experiment_metadata,
)

# Every registered experiment that declares a picture. Derived from the
# registry rather than typed out, so an experiment added with a
# `preview_kind` is covered by every test below without anybody
# remembering to add it here -- which is the same reason `catalog.py` is
# derived from `_REGISTRY`.
VISUAL_EXPERIMENTS = sorted(
    experiment_id
    for experiment_id in EXPERIMENTS
    if experiment_metadata(experiment_id).preview_kind is not None
)

# Cheap ones. `depth` and `object_detection` declare pictures too, and
# both need the optional [ml] extra plus a weight download, so the
# whole-registry sweeps below skip them and
# `test_depth_experiment_integration.py`'s opt-in gate is where a real
# model gets exercised.
CHEAP_VISUAL_EXPERIMENTS = [
    experiment_id
    for experiment_id in VISUAL_EXPERIMENTS
    if not experiment_metadata(experiment_id).requires_model
]


def textured_frame(width=640, height=360, shift=0) -> bytes:
    """A frame with real structure in it, not noise.

    `jpeg_bytes(textured=True)` is uniform random, which produces an edge
    map that is a grey rectangle and a keypoint set with no geometry. A
    room is rectangles, so this is rectangles -- and `shift` moves them,
    which is what gives `optical_flow` something to track.
    """
    rng = np.random.default_rng(11)
    image = np.zeros((height, width, 3), np.uint8)
    for _ in range(60):
        x = int(rng.integers(5, max(6, width - 40)))
        y = int(rng.integers(5, max(6, height - 40)))
        cv2.rectangle(image, (x, y), (x + 32, y + 24), (205, 205, 205), -1)
    if shift:
        image = np.roll(image, shift, axis=1)
    ok, buffer = cv2.imencode(".jpg", image)
    assert ok
    return buffer.tobytes()


def rendered(lab, **kwargs):
    """Render, and fail loudly with the refusal rather than on an attribute."""
    result = lab.render_preview(**kwargs)
    assert isinstance(result, RenderedPreview), result
    return result


# -- every visual experiment actually produces a picture -----------------


@pytest.mark.parametrize("experiment_id", CHEAP_VISUAL_EXPERIMENTS)
def test_every_visual_experiment_renders_something_a_person_could_look_at(
    experiment_id,
):
    """Decodable, non-empty, and no larger than the declared bound.

    Decoded rather than merely measured. `imencode` returning a buffer is
    not evidence that the buffer is an image -- and a preview that fails
    to decode on the phone is exactly the failure this contract cannot
    afford, because the phone's answer to an undecodable image is a blank
    panel with no reason in it.
    """
    lab = asyncio.run(armed_lab(experiment_id))
    for shift in (0, 7):
        lab.process(textured_frame(shift=shift))
        # Past the 0.05 s throttle, so the second frame is a real capture
        # rather than a skip.
        lab._preview._last_capture_at = 0.0

    preview = rendered(lab)
    assert preview.kind == experiment_metadata(experiment_id).preview_kind
    assert preview.image_bytes
    assert max(preview.width, preview.height) <= PREVIEW_MAX_EDGE_PX

    decoded = cv2.imdecode(
        np.frombuffer(preview.image_bytes, np.uint8), cv2.IMREAD_COLOR
    )
    assert decoded is not None
    assert decoded.shape[1] == preview.width
    assert decoded.shape[0] == preview.height
    # Not a blank canvas. Every kind draws SOMETHING -- lines, dots,
    # boxes, a histogram -- and an all-black image would mean the
    # renderer ran and drew nothing, which reads on a phone exactly like
    # a working viewer pointed at a wall.
    assert decoded.any()


@pytest.mark.parametrize("experiment_id", CHEAP_VISUAL_EXPERIMENTS)
def test_a_preview_is_small_enough_to_send_ten_times_a_second(experiment_id):
    """A BOUND, not a measurement.

    Real payloads on this synthetic frame are single-digit kilobytes.
    64 KB is roughly 5 Mbit/s at the 10 Hz the Tower suggests polling at,
    which a LAN carries without noticing and Tailscale carries; anything
    past it would mean a renderer started drawing per-pixel data rather
    than an overlay, which is the thing worth catching.
    """
    lab = asyncio.run(armed_lab(experiment_id))
    lab.process(textured_frame())
    assert len(rendered(lab).image_bytes) < 64 * 1024


def test_the_preview_bound_is_the_same_on_both_sides():
    """`experiments` and `cv_lab` each hold the number, and must agree.

    Copied rather than imported because `cv_lab` imports `experiments`
    and the reverse would be circular -- the same shape of duplication
    `contracts.CARTRIDGE` already has against `results.contracts`, with
    the same kind of test holding it together.
    """
    assert PREVIEW_STRUCTURE_MAX_EDGE_PX == PREVIEW_MAX_EDGE_PX


def test_baseline_is_the_one_experiment_with_no_picture():
    """The control stays the control.

    If this ever fails because somebody gave `baseline` a preview, the
    thing to fix is the preview: this experiment is the figure every
    other experiment's cost is read against, and a line drawing costs
    about as much as the whole of it.
    """
    assert experiment_metadata("baseline").preview_kind is None
    assert set(VISUAL_EXPERIMENTS) == set(EXPERIMENTS) - {"baseline"}


def test_every_declared_kind_has_a_renderer():
    """A kind nobody can draw would reach a phone as a refusal.

    The vocabulary and the renderer table are two places, and this is the
    one line that stops them drifting.
    """
    from tower.cv_lab.preview import _MEDIA_TYPES, _RENDERERS

    assert set(_RENDERERS) == set(PREVIEW_KINDS)
    assert set(_MEDIA_TYPES) == set(PREVIEW_KINDS)


# -- bounded, latest-only ------------------------------------------------


def test_one_capture_and_one_encoding_exist_however_many_frames_arrive():
    """The whole architectural claim, asserted on the object itself."""
    lab = asyncio.run(armed_lab("edge_detection"))
    for _ in range(200):
        lab.process(textured_frame())
        lab._preview._last_capture_at = 0.0

    preview = lab._preview
    # One slot. Not a list of one, not a deque with a maxlen -- one
    # attribute holding one immutable object.
    assert isinstance(preview._latest, object)
    assert not isinstance(preview._latest, (list, tuple, dict, set))
    assert preview._rendered is None  # nothing encoded until somebody asks

    rendered(lab)
    assert isinstance(preview._rendered, RenderedPreview)
    for _ in range(50):
        lab.process(textured_frame())
        lab._preview._last_capture_at = 0.0
        rendered(lab)
    assert isinstance(preview._rendered, RenderedPreview)


def test_a_consumer_that_never_fetches_costs_no_encodes_at_all():
    """Nothing is prepared for a phone that never asks.

    The single sentence that makes "the viewer cannot backpressure the
    pipeline" structural rather than a promise: the expensive half of a
    preview runs in the fetch, so a run nobody is watching pays for no
    resizes, no colour maps and no encoders.
    """
    lab = asyncio.run(armed_lab("edge_detection"))
    for _ in range(100):
        lab.process(textured_frame())
        lab._preview._last_capture_at = 0.0

    stats = lab.status()["run"]["preview"]
    assert stats["captured"] > 0
    assert stats["encoded"] == 0
    assert stats["served"] == 0


def test_a_slow_consumer_drops_frames_instead_of_accumulating_them():
    """Frame N is discarded when N+1 arrives, and the drop is counted."""
    lab = asyncio.run(armed_lab("edge_detection"))
    for _ in range(30):
        lab.process(textured_frame())
        lab._preview._last_capture_at = 0.0
    rendered(lab)

    stats = lab.status()["run"]["preview"]
    assert stats["captured"] == 30
    # Twenty-nine were replaced before anybody looked; the thirtieth is
    # the one that got served.
    assert stats["replaced_unread"] == 29
    assert stats["encoded"] == 1


def test_the_throttle_decouples_the_picture_from_the_processing_rate():
    """Visualisation runs at its own rate, and says how many it skipped."""
    lab = asyncio.run(armed_lab("edge_detection"))
    # No clock manipulation: at real speed a hundred synthetic frames go
    # through far faster than the 0.05 s floor, so the throttle does
    # almost all the work and that is the point.
    for _ in range(100):
        lab.process(textured_frame())

    stats = lab.status()["run"]["preview"]
    assert stats["frames_offered"] == 100
    assert stats["skipped_by_throttle"] > 50
    assert stats["captured"] + stats["skipped_by_throttle"] == 100


def test_previews_are_written_to_no_file_anywhere(tmp_path, monkeypatch):
    """No directory of thousands of frames, because no directory at all."""
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.rglob("*"))

    lab = asyncio.run(armed_lab("edge_detection"))
    for _ in range(40):
        lab.process(textured_frame())
        lab._preview._last_capture_at = 0.0
        rendered(lab)

    assert set(tmp_path.rglob("*")) == before


def test_repeated_run_cycles_leave_nothing_behind():
    """Start, feed, stop, twenty times over. Nothing accumulates."""

    async def main():
        lab = await armed_lab("edge_detection")
        for _ in range(20):
            await start_and_wait(lab, "edge_detection")
            for _ in range(5):
                lab.process(textured_frame())
                lab._preview._last_capture_at = 0.0
            rendered(lab)
            lab.stop()
            assert lab._preview._latest is None
            assert lab._preview._rendered is None
        return lab

    lab = asyncio.run(main())
    gc.collect()
    # The counters are the only thing that grew, and they are ints.
    stats = lab.status()["run"]["preview"]
    assert isinstance(stats["captured"], int)


# -- staleness: three guards, one test each ------------------------------


def test_a_preview_from_a_stopped_run_is_never_served_under_the_next_one():
    """Edge stops, Depth starts, Edge's last frame must not appear.

    The case the whole contract exists for. Asserted with two experiments
    that are both cheap, because the guard is about run identity and not
    about which experiments they were.
    """

    async def main():
        lab = await armed_lab("edge_detection")
        lab.process(textured_frame())
        first_run = lab.status()["lifecycle"]["run_id"]
        rendered(lab)

        await start_and_wait(lab, "feature_detection")
        second_run = lab.status()["lifecycle"]["run_id"]
        return lab, first_run, second_run

    lab, first_run, second_run = asyncio.run(main())
    assert first_run != second_run

    # Nothing at all until the new run produces its own frame.
    refusal = lab.render_preview()
    assert isinstance(refusal, PreviewRefusal)
    assert refusal.reason == PREVIEW_NONE_YET

    # And once it has one, a request naming the OLD run is refused with
    # the current run's id rather than answered with the new picture.
    lab.process(textured_frame())
    assert rendered(lab, run_id=second_run).run_id == second_run
    stale = lab.render_preview(run_id=first_run)
    assert isinstance(stale, PreviewRefusal)
    assert stale.reason == PREVIEW_RUN_CHANGED
    assert stale.current_run_id == second_run


def test_pausing_takes_the_picture_away_immediately():
    """A frozen last frame under a `paused` label reads as live.

    `raw_ephemeral` promises live-view-only in both directions: the phone
    will not store it, and the Tower will not go on serving it once it
    stopped being a view of anything.
    """
    lab = asyncio.run(armed_lab("edge_detection"))
    lab.process(textured_frame())
    rendered(lab)

    outcome = lab.pause()
    assert outcome.accepted
    refusal = lab.render_preview()
    assert isinstance(refusal, PreviewRefusal)
    assert refusal.reason == PREVIEW_NONE_YET
    assert lab._preview._latest is None
    assert lab._preview._rendered is None


def test_resuming_starts_from_a_fresh_picture_rather_than_the_old_one():
    lab = asyncio.run(armed_lab("edge_detection"))
    lab.process(textured_frame())
    lab.pause()
    lab.resume()

    assert isinstance(lab.render_preview(), PreviewRefusal)
    lab.process(textured_frame())
    assert isinstance(lab.render_preview(), RenderedPreview)


def test_stopping_releases_the_picture_and_the_experiments_copy_of_it():
    """Both halves. The slot AND the experiment that fills it."""
    lab = asyncio.run(armed_lab("feature_detection"))
    lab.process(textured_frame())
    experiment = lab._experiment
    rendered(lab)

    lab.stop()
    assert lab._preview._latest is None
    assert lab._preview._rendered is None
    # The experiment was released, so it is holding nothing either.
    assert experiment.take_preview() is None


def test_releasing_the_lab_empties_the_slot_even_when_it_was_already_dead():
    """A release is not a state CHANGE when the Lab is already unavailable.

    So the transition hook does not fire, and `release()` has to empty
    the slot itself. Without that, a Lab released twice keeps the last
    picture the wearer was looking at.
    """
    lab = asyncio.run(armed_lab("edge_detection"))
    lab.process(textured_frame())
    lab.release("first")
    lab.release("second")
    assert lab._preview._latest is None
    assert isinstance(lab.render_preview(), PreviewRefusal)


def test_a_preview_older_than_the_bound_is_refused_rather_than_served():
    """"The picture stopped" beats "the picture is wrong"."""
    clock = {"now": 1000.0}
    preview = LivePreview(PreviewPolicy(max_age_s=2.0), clock=lambda: clock["now"])
    preview.begin("run-1", "edge_map")
    preview.capture(
        cv2.Canny(np.zeros((64, 64), np.uint8), 100, 200),
        run_id="run-1",
        result_seq=1,
        now=clock["now"],
    )
    assert isinstance(preview.render(), RenderedPreview)

    clock["now"] += 5.0
    refusal = preview.render()
    assert isinstance(refusal, PreviewRefusal)
    assert refusal.reason == PREVIEW_STALE


def test_a_render_that_finishes_after_the_run_ended_is_thrown_away():
    """The epoch guard, driven directly.

    A worker thread can be inside `imencode` when the event loop stops
    the run. The bytes it is holding belong to a run that is no longer
    live, and the whole point of the epoch is that they never get served
    under the next run's name.
    """
    preview = LivePreview()
    preview.begin("run-1", "edge_map")
    edges = np.zeros((64, 64), np.uint8)
    edges[::4, :] = 255
    preview.capture(edges, run_id="run-1", result_seq=1, now=preview._clock())

    # The loop stopping the run mid-encode, driven from inside the
    # encoder itself -- which is the one place a real race could put it.
    real = cv2.imencode

    def bump_and_encode(*args, **kwargs):
        preview.suspend()
        return real(*args, **kwargs)

    cv2.imencode = bump_and_encode
    try:
        refusal = preview.render()
    finally:
        cv2.imencode = real

    assert isinstance(refusal, PreviewRefusal)
    assert refusal.reason == PREVIEW_RUN_CHANGED


# -- conditional fetching ------------------------------------------------


def test_the_same_frame_asked_for_twice_is_encoded_once():
    lab = asyncio.run(armed_lab("edge_detection"))
    lab.process(textured_frame())
    first = rendered(lab)
    second = rendered(lab)

    assert second.image_bytes is first.image_bytes
    assert lab.status()["run"]["preview"]["encoded"] == 1
    assert lab.status()["run"]["preview"]["served"] == 2


def test_a_client_that_already_has_the_frame_gets_no_body_and_no_encode():
    lab = asyncio.run(armed_lab("edge_detection"))
    lab.process(textured_frame())
    first = rendered(lab)

    unchanged = lab.render_preview(if_none_match=first.etag)
    assert isinstance(unchanged, PreviewNotModified)
    assert unchanged.etag == first.etag
    assert lab.status()["run"]["preview"]["not_modified"] == 1
    assert lab.status()["run"]["preview"]["encoded"] == 1


def test_a_hostile_if_none_match_header_is_not_a_crash():
    """It is a remote string. Every shape of it must be an ordinary answer."""
    lab = asyncio.run(armed_lab("edge_detection"))
    lab.process(textured_frame())
    for header in ("", ",", "*", 'W/"x"', '"' * 500, "\x00", "a" * 10_000):
        result = lab.render_preview(if_none_match=header)
        assert isinstance(result, (RenderedPreview, PreviewNotModified)), header


# -- failure is contained ------------------------------------------------


def test_a_renderer_that_raises_costs_a_picture_and_not_the_run():
    """`ModuleContainer.mark_failed()` is TERMINAL. This never reaches it."""
    lab = asyncio.run(armed_lab("edge_detection"))
    lab.process(textured_frame())

    real = cv2.imencode
    cv2.imencode = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        refusal = lab.render_preview()
    finally:
        cv2.imencode = real

    assert isinstance(refusal, PreviewRefusal)
    assert refusal.reason == "preview_render_failed"
    assert lab.status()["run"]["preview"]["encode_failures"] == 1

    # The run is untouched: it keeps processing and keeps reporting.
    lab.process(textured_frame())
    assert lab.status()["run"]["frames_processed"] == 2
    assert lab.status()["run"]["frames_failed"] == 0


def test_an_experiment_that_refuses_to_be_armed_for_a_preview_still_runs():
    """A broken optional method is not a broken experiment."""

    class Hostile:
        name = "hostile"

        def load(self, settings=None):
            return None

        def run(self, raw_bytes):
            from tower.experiments import ExperimentResult

            return ExperimentResult(
                result_value=1.0,
                result_label="mean_intensity",
                processing_ms=0.1,
                stage_ms={},
            )

        def set_preview_capture(self, enabled):
            raise RuntimeError("no")

        def take_preview(self):
            raise RuntimeError("also no")

        def release(self):
            return None

    from tower.cv_lab import CVLab

    lab = CVLab("edge_detection", experiment=Hostile())
    asyncio.run(lab.load_initial())
    result = lab.process(textured_frame())

    assert result.result_value == 1.0
    assert lab.status()["run"]["frames_processed"] == 1
    assert isinstance(lab.render_preview(), (PreviewRefusal, RenderedPreview))


def test_a_degenerate_depth_frame_does_not_divide_by_zero():
    """A lens cap is one value everywhere. `astype` on an inf raises."""
    preview = LivePreview()
    preview.begin("run-1", "relative_depth")
    flat = np.full((32, 32), 7.5, np.float32)
    preview.capture(flat, run_id="run-1", result_seq=1, now=preview._clock())
    assert isinstance(preview.render(), RenderedPreview)


def test_a_depth_frame_full_of_nan_is_refused_rather_than_drawn():
    preview = LivePreview()
    preview.begin("run-1", "relative_depth")
    preview.capture(
        np.full((32, 32), np.nan, np.float32),
        run_id="run-1",
        result_seq=1,
        now=preview._clock(),
    )
    refusal = preview.render()
    assert isinstance(refusal, PreviewRefusal)
    assert refusal.reason == "preview_render_failed"


# -- the depth normaliser holds still ------------------------------------


def test_the_depth_scale_is_smoothed_so_one_bright_pixel_does_not_flash():
    """Per-frame min/max is the flicker mechanism. This is the fix.

    Two identical frames, then the same frame with a single extreme
    outlier pixel. Under MiDaS's own per-frame min/max normalisation the
    whole picture would darken; under percentile bounds with a smoothed
    scale it barely moves.
    """
    rng = np.random.default_rng(5)
    base = cv2.GaussianBlur(
        (rng.random((64, 64)).astype(np.float32) * 10.0), (9, 9), 0
    )
    preview = LivePreview()
    preview.begin("run-1", "relative_depth")

    def render(frame, seq):
        preview._last_capture_at = 0.0
        preview.capture(frame, run_id="run-1", result_seq=seq, now=preview._clock())
        result = preview.render()
        assert isinstance(result, RenderedPreview)
        return cv2.imdecode(
            np.frombuffer(result.image_bytes, np.uint8), cv2.IMREAD_GRAYSCALE
        ).mean()

    steady = render(base, 1)
    spiked = base.copy()
    spiked[0, 0] = 10_000.0
    after = render(spiked, 2)

    # A per-frame min/max stretch would have divided by a thousandfold
    # wider range and collapsed the picture towards black. Under 5% of a
    # level is "did not visibly move".
    assert abs(after - steady) / max(steady, 1.0) < 0.05


def test_the_depth_scale_does_not_survive_a_run():
    """The previous experiment must not decide this one's near and far."""
    preview = LivePreview()
    preview.begin("run-1", "relative_depth")
    preview.capture(
        np.full((16, 16), 100.0, np.float32),
        run_id="run-1",
        result_seq=1,
        now=preview._clock(),
    )
    preview.render()
    assert preview._normaliser._low is not None

    preview.begin("run-2", "relative_depth")
    assert preview._normaliser._low is None


# -- the switch ----------------------------------------------------------


def test_a_tower_with_previews_off_holds_nothing_and_says_why():
    """The frame path returns to exactly what it was.

    Which is also how anybody re-measuring the physical baselines should
    run it: no capture, no derivation, no `preview` stage in the timings.
    """

    async def main():
        from tower.cv_lab import CVLab

        lab = CVLab("feature_detection", preview=PreviewPolicy(enabled=False))
        await lab.load_initial()
        lab.process(textured_frame())
        return lab

    lab = asyncio.run(main())
    assert lab._preview._latest is None
    assert lab._experiment.take_preview() is None
    assert "preview" not in lab.status()["run"]["timings"]["stage_ms"]

    refusal = lab.render_preview()
    assert isinstance(refusal, PreviewRefusal)
    assert refusal.reason == PREVIEW_DISABLED

    annotation = lab.status()["run"]["annotation"]
    assert annotation["artifact"] is None
    assert "TOWER_CV_PREVIEW" in annotation["artifact_unavailable_reason"]


def test_a_non_visual_experiment_refuses_with_its_own_reason():
    lab = asyncio.run(armed_lab("baseline"))
    lab.process(jpeg_bytes())
    refusal = lab.render_preview()
    assert isinstance(refusal, PreviewRefusal)
    assert refusal.reason == PREVIEW_NOT_VISUAL


# -- the HTTP surface ----------------------------------------------------


def test_the_route_serves_bytes_with_their_identity_and_no_store(monkeypatch):
    client = make_client(monkeypatch, "edge_detection")
    lab = client.app.state.cv_lab
    lab.process(textured_frame())
    run_id = lab.status()["lifecycle"]["run_id"]

    response = client.get("/cv-lab/preview", params={"run_id": run_id})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-cv-preview-run"] == run_id
    assert response.headers["x-cv-preview-seq"] == "1"
    assert response.headers["x-cv-preview-kind"] == "edge_map"
    assert response.headers["x-cv-preview-treatment"] == TREATMENT_RAW_EPHEMERAL
    assert float(response.headers["x-cv-preview-age"]) >= 0.0
    assert response.content


def test_the_route_answers_304_and_409_and_404_for_the_right_reasons(monkeypatch):
    client = make_client(monkeypatch, "edge_detection")
    lab = client.app.state.cv_lab
    lab.process(textured_frame())
    run_id = lab.status()["lifecycle"]["run_id"]

    first = client.get("/cv-lab/preview")
    unchanged = client.get(
        "/cv-lab/preview", headers={"If-None-Match": first.headers["etag"]}
    )
    assert unchanged.status_code == 304
    assert not unchanged.content

    conflict = client.get("/cv-lab/preview", params={"run_id": "not-this-one"})
    assert conflict.status_code == 409
    assert conflict.json()["reason"] == PREVIEW_RUN_CHANGED
    assert conflict.json()["current_run_id"] == run_id
    assert conflict.headers["cache-control"] == "no-store"


def test_the_route_says_no_visual_output_as_404_not_as_an_error(monkeypatch):
    client = make_client(monkeypatch, "baseline")
    client.app.state.cv_lab.process(jpeg_bytes())
    response = client.get("/cv-lab/preview")
    assert response.status_code == 404
    assert response.json()["reason"] == PREVIEW_NOT_VISUAL


def test_the_descriptor_route_answers_without_transferring_a_picture(monkeypatch):
    client = make_client(monkeypatch, "edge_detection")
    client.app.state.cv_lab.process(textured_frame())

    response = client.get("/cv-lab/preview/status")
    assert response.status_code == 200
    body = response.json()
    assert body["artifact"]["treatment"] == TREATMENT_RAW_EPHEMERAL
    assert body["artifact_unavailable_reason"] is None
    # A descriptor, not a picture.
    assert len(json.dumps(body)) < 2048


def test_a_tower_with_no_lab_answers_503_on_both_preview_routes(monkeypatch):
    client = make_client(monkeypatch, "edge_detection")
    client.app.state.cv_lab = None
    for path in ("/cv-lab/preview", "/cv-lab/preview/status"):
        response = client.get(path)
        assert response.status_code == 503
        assert response.json()["reason"] == "lab_unavailable"
