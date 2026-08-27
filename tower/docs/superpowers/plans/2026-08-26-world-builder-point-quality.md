# World Builder Point Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discard triangulated landmarks that the pipeline's own declared invariants say are not geometry, so fragments render at a legible scale.

**Architecture:** One shared gate helper in `geometry.py` applied at both triangulation sites (`triangulate_points` for the seed pair, `_triangulate_new` for chain extension). Discard counts flow up through the existing `GeometryEstimate.diagnostics` dict into `BuildResult.diagnostics` and the manifest. No tracking, keyframe-selection, or pose-solving code is touched.

**Tech Stack:** Python 3.12, numpy, OpenCV (`cv2`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-world-builder-point-quality-design.md`

## Global Constraints

- Branch: `world-builder/next-generation`. Never commit to `integration/world-builder-lifecycle-v1` or `main`.
- Worktree: `C:\Users\tvllo\Projects\Glasses-world-builder`. Run everything from its `tower/` directory.
- Interpreter: `C:\Users\tvllo\Projects\Glasses\tower\.venv\Scripts\python.exe`. The worktree has no venv; the main checkout's venv resolves `tower` to the worktree via `sys.path` because the editable finder is appended to `sys.meta_path`, not prepended. Verified.
- Capture corpus lives ONLY in the main checkout: `C:\Users\tvllo\Projects\Glasses\tower\data\captures`. `data/` is gitignored. Read it read-only; never write there.
- Baseline test state: **402 passed, 10 skipped** for `-k world`.
- Gate 1 threshold: `MIN_TRIANGULATION_ANGLE_DEG = 0.5` — the EXISTING constant at `geometry.py:30`. Do not introduce a new tuning constant and do not change its value.
- Gate 2 threshold: `3.0` px, matching `classical.PNP_REPROJECTION_ERROR_PX` (`classical.py:64`).
- Exactly two discard reasons: `low_parallax`, `high_reprojection`. There is no retention/`unassessable` category — see spec §2.4.
- `segments` and `keyframes` must be unchanged on every capture by these gates. Any movement means the change leaked outside its surface.
- Never report `points` without `poses_solved` beside it.

---

## File Structure

| File | Responsibility |
|---|---|
| `tower/world_builder/geometry.py` | MODIFY — add `MAX_LANDMARK_REPROJECTION_PX`, add `landmark_gate()`, apply it inside `triangulate_points` |
| `tower/world_builder/backends/classical.py` | MODIFY — apply `landmark_gate()` in `_triangulate_new`; surface counts into `GeometryEstimate.diagnostics` |
| `tower/world_builder/engine.py` | MODIFY — aggregate per-segment discard counts into `BuildResult.diagnostics` and the manifest |
| `tests/test_world_builder_point_quality.py` | CREATE — characterisation, unit, adversarial, accounting tests |
| `scripts/world_builder_corpus_benchmark.py` | CREATE — pinned-corpus A/B driver with `--label` and `--compare` |

---

## Task 1: Characterisation — pin today's behaviour

**Files:**
- Test: `tests/test_world_builder_point_quality.py` (create)

**Interfaces:**
- Consumes: `tower.world_builder.geometry.triangulate_points`
- Produces: nothing consumed by later tasks; this task's tests INVERT in Task 3.

- [ ] **Step 1: Write the characterisation test**

```python
"""Point-quality gates. Task 1 pins today's behaviour; Task 3 inverts it."""
import numpy as np
import pytest

from tower.world_builder.geometry import triangulate_points

CAMERA = np.array([[438.23, 0.0, 174.88],
                   [0.0, 437.78, 323.38],
                   [0.0, 0.0, 1.0]], dtype=np.float64)


def _near_parallel_pair():
    """A tiny baseline viewing a very distant point.

    Baseline 0.001 units, point at depth ~1000 => inter-ray angle far
    below MIN_TRIANGULATION_ANGLE_DEG. The intersection is numerically
    arbitrary, which is exactly what the gate must reject.
    """
    rotation = np.eye(3)
    translation = np.array([-0.001, 0.0, 0.0])
    world = np.array([[0.0, 0.0, 1000.0]])
    pa = (CAMERA @ world.T).T
    pa = (pa[:, :2] / pa[:, 2:3]).astype(np.float32)
    cam_b = (rotation @ world.T).T + translation
    pb = (CAMERA @ cam_b.T).T
    pb = (pb[:, :2] / pb[:, 2:3]).astype(np.float32)
    return pa, pb, rotation, translation


def test_characterisation_near_parallel_point_survives_today():
    """CHARACTERISATION. Inverted by Task 3 -- do not delete, flip it."""
    pa, pb, rotation, translation = _near_parallel_pair()
    points = triangulate_points(pa, pb, rotation, translation, CAMERA)
    assert len(points) == 1, (
        "Today triangulate_points keeps a near-parallel pair. If this "
        "fails, the gate already landed -- flip to the Task 3 assertion."
    )
```

- [ ] **Step 2: Run it and confirm it PASSES (this pins current behaviour)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_world_builder_point_quality.py -v -p no:cacheprovider`
Expected: PASS. A failure here means the premise is wrong — stop and re-measure before continuing.

- [ ] **Step 3: Commit**

```bash
git add tests/test_world_builder_point_quality.py
git commit -m "test: pin that near-parallel rays currently survive triangulation"
```

---

## Task 2: The gate helper

**Files:**
- Modify: `tower/world_builder/geometry.py`
- Test: `tests/test_world_builder_point_quality.py`

**Interfaces:**
- Produces, consumed by Tasks 3 and 4:
  - `MAX_LANDMARK_REPROJECTION_PX: float = 3.0`
  - `landmark_gate(xyz, points_a, points_b, pose_a, pose_b, camera_matrix, min_angle_deg=MIN_TRIANGULATION_ANGLE_DEG, max_reprojection_px=MAX_LANDMARK_REPROJECTION_PX) -> tuple[np.ndarray, dict[str, int]]`
  - `xyz` is `(N,3)` in the frame `pose_a`/`pose_b` map FROM. `points_a`/`points_b` are `(N,2)` observed pixels. Each pose is `(rotation (3,3), translation (3,))` mapping world→camera. Returns `(keep_bool_mask_of_len_N, {"low_parallax": int, "high_reprojection": int})`.

- [ ] **Step 1: Write the failing unit tests**

```python
from tower.world_builder.geometry import (
    MAX_LANDMARK_REPROJECTION_PX,
    MIN_TRIANGULATION_ANGLE_DEG,
    landmark_gate,
)

IDENTITY_POSE = (np.eye(3), np.zeros(3))


def _project(world, pose, camera=CAMERA):
    rotation, translation = pose
    cam = (rotation @ np.asarray(world, dtype=np.float64).T).T + translation
    uv = (camera @ cam.T).T
    return (uv[:, :2] / uv[:, 2:3]).astype(np.float64)


def test_gate_rejects_near_parallel_landmark():
    pose_b = (np.eye(3), np.array([-0.001, 0.0, 0.0]))
    world = np.array([[0.0, 0.0, 1000.0]])
    keep, counts = landmark_gate(
        world, _project(world, IDENTITY_POSE), _project(world, pose_b),
        IDENTITY_POSE, pose_b, CAMERA,
    )
    assert not keep[0]
    assert counts["low_parallax"] == 1
    assert counts["high_reprojection"] == 0


def test_gate_keeps_distant_but_well_triangulated_landmark():
    """ADVERSARIAL, REQUIRED. A gate that discards everything passes
    every other test in this file. Distance alone is not the defect --
    an unconstrained ray is. Baseline 30 at depth 1000 subtends ~1.7 deg,
    comfortably above the 0.5 deg bar, and must SURVIVE."""
    pose_b = (np.eye(3), np.array([-30.0, 0.0, 0.0]))
    world = np.array([[0.0, 0.0, 1000.0]])
    keep, counts = landmark_gate(
        world, _project(world, IDENTITY_POSE), _project(world, pose_b),
        IDENTITY_POSE, pose_b, CAMERA,
    )
    assert keep[0], "a genuinely distant, well-triangulated point must survive"
    assert counts == {"low_parallax": 0, "high_reprojection": 0}


def test_gate_rejects_high_reprojection_landmark():
    pose_b = (np.eye(3), np.array([-1.0, 0.0, 0.0]))
    world = np.array([[0.0, 0.0, 10.0]])
    good_a, good_b = _project(world, IDENTITY_POSE), _project(world, pose_b)
    bad_b = good_b + np.array([[40.0, 0.0]])
    keep, counts = landmark_gate(
        world, good_a, bad_b, IDENTITY_POSE, pose_b, CAMERA,
    )
    assert not keep[0]
    assert counts["high_reprojection"] == 1
    assert counts["low_parallax"] == 0


def test_gate_handles_coincident_camera_centres_without_raising():
    """Degenerate pair: zero baseline. Angle is zero, so gate 1 rejects.
    Must not raise, divide by zero, or emit a non-finite angle."""
    pose_b = (np.eye(3), np.zeros(3))
    world = np.array([[0.0, 0.0, 10.0]])
    keep, counts = landmark_gate(
        world, _project(world, IDENTITY_POSE), _project(world, pose_b),
        IDENTITY_POSE, pose_b, CAMERA,
    )
    assert not keep[0]
    assert counts["low_parallax"] == 1


def test_gate_counts_are_mutually_exclusive_and_total_correctly():
    """Accounting: kept + low_parallax + high_reprojection == produced."""
    pose_b = (np.eye(3), np.array([-1.0, 0.0, 0.0]))
    world = np.array([[0.0, 0.0, 10.0],      # good
                      [0.0, 0.0, 100000.0],  # near-parallel
                      [1.0, 0.0, 10.0]])     # good, perturbed below
    pa, pb = _project(world, IDENTITY_POSE), _project(world, pose_b)
    pb[2] = pb[2] + np.array([50.0, 0.0])
    keep, counts = landmark_gate(world, pa, pb, IDENTITY_POSE, pose_b, CAMERA)
    assert int(keep.sum()) + counts["low_parallax"] + counts["high_reprojection"] == 3
    assert set(counts) == {"low_parallax", "high_reprojection"}


def test_gate_on_empty_input_returns_empty_mask_and_zero_counts():
    keep, counts = landmark_gate(
        np.zeros((0, 3)), np.zeros((0, 2)), np.zeros((0, 2)),
        IDENTITY_POSE, (np.eye(3), np.array([-1.0, 0.0, 0.0])), CAMERA,
    )
    assert keep.shape == (0,)
    assert counts == {"low_parallax": 0, "high_reprojection": 0}
```

- [ ] **Step 2: Run and verify they FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/test_world_builder_point_quality.py -v -p no:cacheprovider`
Expected: FAIL — `ImportError: cannot import name 'landmark_gate'`

- [ ] **Step 3: Implement the helper in `geometry.py`**

Add after `MIN_INLIERS` (near `geometry.py:39`):

```python
# A landmark that reprojects worse than the budget solvePnPRansac uses to
# call a pose an inlier (classical.PNP_REPROJECTION_ERROR_PX) is
# inconsistent with the pose that produced it, by the pipeline's own
# standard. Not a new tuning constant -- the same 3.0 px, applied to the
# landmark instead of only to the pose.
MAX_LANDMARK_REPROJECTION_PX = 3.0
```

Add near `triangulate_points`:

```python
def _camera_centre(pose):
    """World-frame position of a camera given a world->camera pose."""
    rotation, translation = pose
    return -rotation.T @ np.asarray(translation, dtype=np.float64).reshape(3)


def landmark_gate(
    xyz,
    points_a,
    points_b,
    pose_a,
    pose_b,
    camera_matrix,
    min_angle_deg: float = MIN_TRIANGULATION_ANGLE_DEG,
    max_reprojection_px: float = MAX_LANDMARK_REPROJECTION_PX,
):
    """Which triangulated landmarks are geometry, and why the rest are not.

    Two gates, both enforcing invariants this pipeline already declares:

    1. The angle subtended at the landmark by the two camera centres must
       reach MIN_TRIANGULATION_ANGLE_DEG. Below that the two rays are
       near-parallel and their intersection is numerically arbitrary --
       measured up to 33,363 baselines out on real captures, which is what
       destroys the bounding box the phone renders against.
    2. The landmark must reproject into BOTH source views within
       MAX_LANDMARK_REPROJECTION_PX.

    Returns (keep, counts). A rejected landmark is counted under exactly
    one reason; gate 1 is evaluated first, so a point failing both is
    counted as low_parallax.
    """
    xyz = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
    count = len(xyz)
    counts = {"low_parallax": 0, "high_reprojection": 0}
    if count == 0:
        return np.zeros(0, dtype=bool), counts

    centre_a = _camera_centre(pose_a)
    centre_b = _camera_centre(pose_b)

    ray_a = centre_a - xyz
    ray_b = centre_b - xyz
    norm_a = np.linalg.norm(ray_a, axis=1)
    norm_b = np.linalg.norm(ray_b, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        cosines = np.einsum("ij,ij->i", ray_a, ray_b) / (norm_a * norm_b)
    angles = np.degrees(np.arccos(np.clip(cosines, -1.0, 1.0)))
    # A zero-length ray (camera centre coincident with the landmark) or a
    # zero baseline yields a non-finite cosine. That is not geometry.
    angles = np.where(np.isfinite(angles), angles, 0.0)
    parallax_ok = angles >= min_angle_deg

    def _reprojection_error(pose, observed):
        rotation, translation = pose
        cam = (rotation @ xyz.T).T + np.asarray(
            translation, dtype=np.float64
        ).reshape(3)
        with np.errstate(divide="ignore", invalid="ignore"):
            uv = (camera_matrix @ cam.T).T
            uv = uv[:, :2] / uv[:, 2:3]
        error = np.linalg.norm(
            uv - np.asarray(observed, dtype=np.float64).reshape(-1, 2), axis=1
        )
        return np.where(np.isfinite(error), error, np.inf)

    reprojection_ok = (
        _reprojection_error(pose_a, points_a) <= max_reprojection_px
    ) & (_reprojection_error(pose_b, points_b) <= max_reprojection_px)

    keep = parallax_ok & reprojection_ok
    counts["low_parallax"] = int((~parallax_ok).sum())
    counts["high_reprojection"] = int((parallax_ok & ~reprojection_ok).sum())
    return keep, counts
```

- [ ] **Step 4: Run and verify they PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_world_builder_point_quality.py -v -p no:cacheprovider`
Expected: all PASS except the Task 1 characterisation test, which still passes (the gate is not wired in yet).

- [ ] **Step 5: Commit**

```bash
git add tower/world_builder/geometry.py tests/test_world_builder_point_quality.py
git commit -m "feat: landmark_gate enforces the parallax invariant per point"
```

---

## Task 3: Wire the gate into the seed pair

**Files:**
- Modify: `tower/world_builder/geometry.py` (`triangulate_points`)
- Test: `tests/test_world_builder_point_quality.py`

**Interfaces:**
- Consumes: `landmark_gate` from Task 2.
- Produces: `triangulate_points(..., return_mask=True)` keeps its `(xyz, keep)` shape. `return_counts=True` additionally returns the counts dict, used by Task 5.

- [ ] **Step 1: Invert the characterisation test and add the pass-through test**

Replace the body of `test_characterisation_near_parallel_point_survives_today` with:

```python
def test_near_parallel_point_is_now_discarded():
    """Was the Task 1 characterisation. Inverted deliberately."""
    pa, pb, rotation, translation = _near_parallel_pair()
    points = triangulate_points(pa, pb, rotation, translation, CAMERA)
    assert len(points) == 0


def test_triangulate_points_keeps_well_conditioned_geometry():
    """Guards against the gate simply emptying the cloud."""
    rotation = np.eye(3)
    translation = np.array([-1.0, 0.0, 0.0])
    world = np.array([[0.0, 0.0, 10.0], [1.0, 0.5, 12.0], [-1.0, -0.5, 9.0]])
    pa = _project(world, IDENTITY_POSE).astype(np.float32)
    pb = _project(world, (rotation, translation)).astype(np.float32)
    points = triangulate_points(pa, pb, rotation, translation, CAMERA)
    assert len(points) == 3


def test_triangulate_points_mask_and_counts_agree():
    rotation = np.eye(3)
    translation = np.array([-1.0, 0.0, 0.0])
    world = np.array([[0.0, 0.0, 10.0], [0.0, 0.0, 100000.0]])
    pa = _project(world, IDENTITY_POSE).astype(np.float32)
    pb = _project(world, (rotation, translation)).astype(np.float32)
    points, keep, counts = triangulate_points(
        pa, pb, rotation, translation, CAMERA,
        return_mask=True, return_counts=True,
    )
    assert len(points) == int(keep.sum())
    assert int(keep.sum()) + counts["low_parallax"] + counts["high_reprojection"] == 2
```

- [ ] **Step 2: Run and verify the inverted test FAILS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_world_builder_point_quality.py -v -p no:cacheprovider`
Expected: `test_near_parallel_point_is_now_discarded` FAILS (1 point still returned).

- [ ] **Step 3: Apply the gate inside `triangulate_points`**

Replace the tail of `triangulate_points` (from `in_front_a = ...` through the returns) with:

```python
    in_front_a = xyz[:, 2] > 0
    xyz_b = (rotation @ xyz.T).T + translation.reshape(3)
    in_front_b = xyz_b[:, 2] > 0
    cheirality_keep = np.isfinite(xyz).all(axis=1) & in_front_a & in_front_b

    # Cheirality and finiteness say the point is in front of both
    # cameras. They do not say the two rays actually intersect there.
    #
    # The gate runs ONLY on rows cheirality already accepted, so a point
    # dropped for being behind a camera is never also counted under a
    # gate reason. That keeps the accounting identity exact:
    #   produced == kept + low_parallax + high_reprojection + cheirality
    gate_keep = np.zeros(len(xyz), dtype=bool)
    counts = {"low_parallax": 0, "high_reprojection": 0}
    if cheirality_keep.any():
        subset_keep, counts = landmark_gate(
            xyz[cheirality_keep],
            np.asarray(points_a, dtype=np.float64).reshape(-1, 2)[cheirality_keep],
            np.asarray(points_b, dtype=np.float64).reshape(-1, 2)[cheirality_keep],
            (np.eye(3), np.zeros(3)),
            (rotation, translation),
            camera_matrix,
        )
        gate_keep[cheirality_keep] = subset_keep
    keep = gate_keep

    if return_mask and return_counts:
        return xyz[keep], keep, counts
    if return_counts:
        return xyz[keep], counts
    if return_mask:
        return xyz[keep], keep
    return xyz[keep]
```

Update the signature to `def triangulate_points(..., return_mask: bool = False, return_counts: bool = False):` and the docstring to name both gates.

- [ ] **Step 4: Run and verify all PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_world_builder_point_quality.py -v -p no:cacheprovider`
Expected: all PASS.

- [ ] **Step 5: Run the surrounding suite for collateral damage**

Run: `.venv/Scripts/python.exe -m pytest tests/ -k world -q -p no:cacheprovider`
Expected: 402 passed, 10 skipped. Any new failure is a real regression — investigate before proceeding, do not adjust the gate to make a test pass.

- [ ] **Step 6: Commit**

```bash
git add tower/world_builder/geometry.py tests/test_world_builder_point_quality.py
git commit -m "feat: the seed pair stops keeping rays that do not intersect"
```

---

## Task 4: Wire the gate into chain extension

**Files:**
- Modify: `tower/world_builder/backends/classical.py` (`_triangulate_new`, ~line 684-728)
- Test: `tests/test_world_builder_point_quality.py`

**Interfaces:**
- Consumes: `landmark_gate` from Task 2.
- Produces: `_triangulate_new` returns `(new_points, new_observed, counts)` — a THIRD element. Its single caller must be updated in the same commit.

- [ ] **Step 1: Write the failing test**

```python
def test_chain_extension_discards_near_parallel_landmarks():
    from tower.world_builder.backends.classical import ClassicalTwoViewBackend

    backend = ClassicalTwoViewBackend()
    backend._camera_matrix = CAMERA

    class _KP:
        def __init__(self, pt):
            self.pt = pt

    pose_p = (np.eye(3), np.zeros(3))
    pose_c = (np.eye(3), np.array([-0.001, 0.0, 0.0]))
    world = np.array([[0.0, 0.0, 1000.0]])
    kp_p = [_KP(tuple(_project(world, pose_p)[0]))]
    kp_c = [_KP(tuple(_project(world, pose_c)[0]))]

    points, observed, counts = backend._triangulate_new(
        kp_p, kp_c, [(0, 0)], pose_p, pose_c, 0, 1,
    )
    assert points == []
    assert observed == {}
    assert counts["low_parallax"] == 1
```

- [ ] **Step 2: Run and verify it FAILS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_world_builder_point_quality.py::test_chain_extension_discards_near_parallel_landmarks -v -p no:cacheprovider`
Expected: FAIL — returns 2 values, not 3 (`ValueError: not enough values to unpack`).

- [ ] **Step 3: Apply the gate in `_triangulate_new`**

Change the early return to `return [], {}, {"low_parallax": 0, "high_reprojection": 0}`.

After the `xyz` computation and before the accumulation loop, insert:

```python
        observed_p = points_p.T
        observed_c = points_c.T
        finite = np.isfinite(xyz).all(axis=1)
        gate_keep = np.zeros(len(xyz), dtype=bool)
        counts = {"low_parallax": 0, "high_reprojection": 0}
        if finite.any():
            subset_keep, counts = landmark_gate(
                xyz[finite], observed_p[finite], observed_c[finite],
                pose_previous, pose_current, self._camera_matrix,
            )
            gate_keep[finite] = subset_keep
```

In the accumulation loop, replace the `isfinite` guard with a `gate_keep[offset]` check, keeping the existing depth checks:

```python
            if not gate_keep[offset]:
                continue
            depth_p = (rotation_p @ point + translation_p)[2]
            depth_c = (rotation_c @ point + translation_c)[2]
            if depth_p <= 0 or depth_c <= 0:
                continue
```

Change the final return to `return new_points, new_observed, counts`.

Add `landmark_gate` to the existing `from ..geometry import (...)` block at `classical.py:47`.

- [ ] **Step 4: Update the caller**

Find the single call site with `grep -n "_triangulate_new" tower/world_builder/backends/classical.py`. Unpack three values and accumulate `counts` into a per-window running total so Task 5 can read it.

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_world_builder_point_quality.py -v -p no:cacheprovider`
Then: `.venv/Scripts/python.exe -m pytest tests/ -k world -q -p no:cacheprovider`
Expected: new test passes; 402 passed, 10 skipped overall.

- [ ] **Step 6: Commit**

```bash
git add tower/world_builder/backends/classical.py tests/test_world_builder_point_quality.py
git commit -m "feat: chain extension applies the same landmark gate"
```

---

## Task 5: Report the discards

**Files:**
- Modify: `tower/world_builder/backends/classical.py` (populate `GeometryEstimate.diagnostics`)
- Modify: `tower/world_builder/engine.py` (aggregate into `BuildResult.diagnostics` and the manifest, ~`engine.py:552-584`)
- Test: `tests/test_world_builder_point_quality.py`

**Interfaces:**
- Consumes: counts from Tasks 3 and 4.
- Produces: manifest key `points_discarded` = `{"low_parallax": int, "high_reprojection": int}`, and `BuildResult.diagnostics["points_discarded_by_segment"]` = `{segment_index: {reason: int}}`.

- [ ] **Step 1: Write the failing test**

```python
def test_manifest_reports_discard_counts_and_accounts_for_every_point(tmp_path):
    """produced == retained + low_parallax + high_reprojection, per build.

    Uses the synthetic room the existing suite already builds with, so
    this asserts the plumbing, not the optics.
    """
    from tests import synthetic_scene as ss  # noqa: F401  (import guard)
    # Build a short session through the real engine, then assert the
    # manifest carries the key and that the arithmetic closes.
    # (Implementer: mirror the session construction used in
    # tests/test_world_builder_incremental.py -- do not invent a new one.)
```

IMPLEMENTER NOTE: read `tests/test_world_builder_incremental.py` first and reuse its
session-construction helper verbatim rather than writing a new fixture. The
assertion is: `manifest["points_discarded"]` exists, both keys are ints, and
`manifest["points"] + sum(manifest["points_discarded"].values())` equals the
total landmarks the backend produced (exposed via `BuildResult.diagnostics`).

- [ ] **Step 2: Run and verify it FAILS** (`KeyError: 'points_discarded'`)

- [ ] **Step 3: Populate `diagnostics` in the backend and aggregate in the engine**

In `classical.py`, carry the per-window counts into the returned
`GeometryEstimate(..., diagnostics={"points_discarded": {...}})`.

In `engine.py`, sum them per segment while the existing per-segment loop runs
(near `engine.py:487`), store `points_discarded_by_segment` in
`BuildResult.diagnostics`, and add the rolled-up `points_discarded` to the
manifest dict at `engine.py:552-570`.

- [ ] **Step 4: Run tests** — new test passes; `-k world` still 402 passed, 10 skipped.

- [ ] **Step 5: Commit**

```bash
git add tower/world_builder/backends/classical.py tower/world_builder/engine.py tests/test_world_builder_point_quality.py
git commit -m "feat: discarded points are counted, not silently dropped"
```

---

## Task 6: The corpus A/B instrument

**Files:**
- Create: `scripts/world_builder_corpus_benchmark.py`

**Interfaces:**
- Produces: a CLI. `--label NAME --out results.json` writes one run; `--compare A.json B.json` prints a per-capture and corpus-total diff.

- [ ] **Step 1: Write the driver**

Requirements, all load-bearing:

- Pinned capture ids, as a module-level constant — never a glob of `data/captures`, so the set cannot drift as the corpus grows:
  `e1c52b9f, 22e9d428, b35d8ab8, 20ce3c23, 2e6cffa2, fe744b68, 64f48114, 4fea31e2`
  (match by directory-name prefix; error loudly if a prefix matches zero or more than one directory).
- Corpus root defaults to `C:\Users\tvllo\Projects\Glasses\tower\data\captures`, overridable with `--captures`. Read-only.
- Replay via the `--follow-capture` journal path used by `scripts/world_build_session.py` (preserves `source_seq` / `received_at`). Do NOT use the `--frames` path: it fabricates `source_seq` and drops `received_at` (`world_build_session.py:130-133`).
- Call `cv2.setRNGSeed(0)` before any work.
- Write derived output to a scratch root under `--scratch`, never into `data/world_builder`.
- Per capture, record: `segments, keyframes, poses_solved, poses_refused, points, points_discarded{low_parallax,high_reprojection}, bbox_blowup, legible_fragments, drawable_fragments, wall_seconds`.
- `bbox_blowup` = max-axis full extent ÷ max-axis p2–p98 extent, over all points in the session.
- `legible_fragments` = count of segments with ≥20 points whose p2–p98 core occupies ≥20pt when fitted to a 140pt card by the `WorldFragmentsView` rule: `scale = min(140/spanX, 140/spanZ) * 0.9` on the X/Z axes.
- `--compare` must print `poses_solved` and `points` side by side for every capture and refuse to print a verdict if `segments` or `keyframes` moved on any capture.

- [ ] **Step 2: Smoke-run it on the two cheapest captures**

Run: `.venv/Scripts/python.exe scripts/world_builder_corpus_benchmark.py --label smoke --only 64f48114,4fea31e2 --out /tmp/smoke.json`
Expected: completes; `4fea31e2` reports 0 poses and 0 points.

- [ ] **Step 3: Commit**

```bash
git add scripts/world_builder_corpus_benchmark.py
git commit -m "feat: a corpus benchmark that reports points beside poses"
```

---

## Task 7: Run the A/B and rule on it

**EXECUTION ORDER NOTE.** Task 6 (the instrument) is built and Arm A is
recorded BEFORE Tasks 2-5 land. This is deliberate. The alternative — an
env-gated bypass such as `WORLD_BUILDER_DISABLE_LANDMARK_GATE` — would add
a production code path that nothing else exercises, purely to serve the
benchmark. Running the instrument first costs one extra checkout of
ordering discipline and keeps exactly one code path under test.

Actual execution order: Task 1 → Task 6 → Arm A → Task 2 → Task 3 → Task 4
→ Task 5 → Arm B → rule.

- [ ] **Step 1: Arm A — baseline.** Recorded at the commit where the benchmark exists and no gate does. `--label baseline --out results/ab-a-baseline.json`.
- [ ] **Step 2: Arm B — gated.** Same command, same pinned set, after Task 5 lands. `--label gated --out results/ab-b-gated.json`.
- [ ] **Step 3: Compare.** `--compare results/ab-a-baseline.json results/ab-b-gated.json`
- [ ] **Step 4: Rule against spec §5.4.** Every clause must hold. `segments`/`keyframes` unchanged on every capture is the strongest check — if it moved, the change leaked outside its surface and the result is void regardless of how good the other numbers look.
- [ ] **Step 5: Write the results into the spec** as a new "Measured outcome" section, replacing the projections in §2.6 with real numbers. If the measured result contradicts the projection, say so plainly and follow the spec §8 instruction rather than retuning to fit.
- [ ] **Step 6: Commit the results file and the updated spec.**

---

## Self-Review Notes

- Spec coverage: §2.2→Task 3/4, §2.3→Task 2, §2.5→Task 5, §5→Tasks 6/7, §6→Tasks 1-5.
- Task 3 Step 3 scaffolding removed in self-review; only the correct implementation remains.
- Execution order is Task 1 -> Task 6 -> Arm A -> Tasks 2-5 -> Arm B, so the baseline is measured with no gate in the binary and no bypass path exists.
- Task 5 Step 1 intentionally defers fixture construction to the existing incremental test rather than inventing a parallel fixture.
