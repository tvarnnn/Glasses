# Persisting the 2D/3D association: `support_views` and `support.json`

**Date:** 2026-08-26
**Branch:** `integration/world-builder-lifecycle-v1`
**Scope:** step 0 of `tower/docs/superpowers/research/2026-08-26-cross-segment-registration.md` section 7
**Files:** `tower/tower/world_builder/backend.py`, `backends/classical.py`,
`engine.py`, `store.py`, `tower/tests/test_world_builder_support_views.py`

---

## What changed

`PointBlock.support_views` was declared and never populated (a repo-wide grep
found the declaration and nothing else). It is now filled by the classical
backend on both paths, carried through the engine, and written to a new derived
artifact `support.json` beside `points.json`.

`points.json` is untouched. Its row shape stays `{"segment_index", "xyz"}`,
which is what `tests/test_world_builder_derived_schema.py` pins and what
`docs/contracts/WORLD-BUILDER-GEOMETRY.md` publishes. The association is several
times longer than the point list and has no consumer yet; a second file costs a
reader one `open()` and costs that contract nothing.

## Shape

In memory: a flat `(M, 3)` `int32` array, rows `[frame_index, feature_index,
landmark_index]`.

Flat and numpy-native rather than ragged for three reasons. It is the shape the
consumer wants -- registration filters by frame and joins against matched
feature indices, which is a boolean mask on a column. It costs 12 bytes a row
against the ~200 bytes a dict entry costs, and this is the one piece of solve
state that **cannot** be pruned. And it round-trips through JSON as integers
with no dtype contract to get wrong.

On disk, `support.json` is `{"support": [[segment_index, frame_index,
feature_index, point_index], ...]}` -- flat integer rows, no repeated key names.

## The frame-index convention, and why

**Window-relative, equivalently segment-relative. Position within the window the
block was solved from, `0` == the anchor. Never session-relative.**

Three reasons, in order of force:

1. **The backend cannot honestly produce anything else.** It is handed one
   window and does not know where that window sits in a session. A
   session-relative index would have to be invented by the engine and threaded
   back down, which is a coupling the backend interface deliberately does not
   have.
2. **It is the only convention both paths can agree on.** The live path's frame
   counter restarts at 0 for each segment (`backend.reset()` per segment in
   `engine.py`), so window-relative is the one indexing under which the live and
   cold tables are bit-identical -- and that identity is the strongest test
   available here.
3. **A segment is the only frame of reference the columns share.** Segments do
   not share a coordinate frame or a unit. A session-wide ordinal would imply a
   relationship between segments that the reconstruction does not have.

On disk the same index reads as "position within this segment's ordered
keyframes", which joins directly against `poses.json` (whose rows the engine
appends in the same per-segment order). `point_index` is segment-local in
exactly the same way and joins against `points.json`.

`landmark_index`/`point_index` always indexes **that block's own** `xyz`.
`Extension.new_points` is a delta, so its table names only the landmarks the
delta carries; re-observations of older landmarks are not expressible there and
reach a consumer through `snapshot()`, which is the authoritative view anyway.

## How the pruning trap was avoided

Section 1.3 of the research: `_Chain.forget_before` (`classical.py`) drops every
observation whose frame index is not the most recent, deliberately -- 26.1 MB to
0.15 MB at 155 keyframes. A table read off `_Chain.observed` at the end would
hold **one frame's worth** on the live path and the whole history on the rebuild
path: different data under one field name, and silently so.

The table is therefore **accumulated where landmarks are created**, never
derived from the lookup dict:

- `estimate_window` appends a block at the seeding pair and one per chained
  frame (re-observations, then newly triangulated points, in that order).
- `extend` appends the same blocks, in the same order, to `_Chain.support`.
- `_Chain.support` is a `list` of small `(m, 3)` arrays, is **not** pruned by
  `forget_before`, and `forget_before`'s docstring now says so and says why.
  It is affordable precisely because it is not the dict it sits beside: at 12
  bytes a row the 26.1 MB figure above is ~1.3 MB, and the 142.9 MB figure at
  1000 keyframes is ~8 MB.

`observed` is a **lookup** -- one landmark per `(frame, feature)` key, last
writer wins. `support` is a **record**. Where they differ, the record wins:
`match_indices` guarantees one entry per query index, not per train index, so
two of frame 0's features can name the same feature of frame 1. The dict keeps
one; the table emits both, because dropping one would leave a landmark with a
single view, which is not a thing that can be triangulated. This is why
`test_every_landmark_is_named_by_at_least_two_frames` holds by construction.

## Size cost, measured

Build over `data/captures/854e9688d2c54ae398eff4fb7c141522/frames` (610 frames,
196 keyframes accepted, 17 segments, 11 poses solved, 998 points), via
`scripts/world_build_session.py --root <temp> --frames ... --format json` with
`data/world_builder/intrinsics/360x640.json` copied into `<temp>/intrinsics/`.

| file | bytes | rows |
|---|---|---|
| `points.json` | 91,012 | 998 points |
| `support.json` | **39,587** | 2,152 observations |

**support.json is 0.435x points.json** -- well under the ~3x line, and the
budget is not close. Per row: 18.4 bytes for an observation against 91.2 bytes
for a point, so the ratio is `0.20 x observations_per_point`. This world carries
2.16 observations per point; the research corpus's denser segments carry ~2.8,
which lands at ~0.55x. It would take **more than 15 observations per point** to
reach 3x, which no reconstruction this backend produces comes near.

## Geometry is unchanged, verified on real data

The same 610-frame capture was built **before** the change and **after** it:

- `points.json`: **byte-identical**, 91,012 bytes, `cmp` clean.
- `poses.json`: identical modulo `keyframe_id`, which embeds a freshly minted
  session id and therefore cannot match across two separate script runs. All 196
  rows agree on `segment_index`, `status`, `degeneracy`, `rotation` and
  `translation`, compared as serialized JSON.

`test_world_builder_incremental.py::test_a_live_build_equals_a_cold_build_of_the_same_keyframes`
remains the oracle and stays green.

## Backward compatibility

`support.json` is **optional on read**. `write_derived(..., support=None)` writes
no file; `read_derived` returns `"support": None` when the file is missing, and
also when it is present but corrupt -- logged, but never a refusal. A
reconstruction is complete without it: it is an index into the reconstruction,
not part of it, and refusing poses and points over a truncated index would turn
an optional file into a hard dependency by the back door.

Checked against every world on disk under `data/world_builder`: 57 worlds, 8
with derived output, all 8 read successfully with `support` absent, 0 errors.
The derived manifest gained no key, so
`test_derived_manifest_has_exactly_the_documented_keys` is untouched.

## Tests

`tower/tests/test_world_builder_support_views.py`, 14 tests. The two that carry
the weight:

- **`test_each_row_reprojects_onto_the_feature_it_names`** -- the association is
  TRUE, not merely well-shaped. Every row's landmark is projected through the
  pose of the frame it names and compared against the keypoint it names. Median
  0.62 px; 98.7% under 10 px. `test_a_shuffled_association_would_fail_that_check`
  is its teeth: permuting the landmark column drives the median past 100 px.
- **`test_a_live_solve_records_the_same_association_as_a_cold_solve`** -- the
  pruning trap, stated as a test, compared `tobytes()`-exact with no tolerance.
  `test_the_live_table_outlives_the_pruning_it_survives` asserts both halves at
  once: the prune still keeps exactly one frame, and the table still spans many.

Suite: **1260 passed, 32 skipped, 0 failed** (1246 before, plus these 14).

## What this does not do

No registration. No `registered` / `transform_to_world` change. No geometry
change of any kind. This is step 0 of section 7 -- it unblocks every route in
the research document and removes the ~19 s re-solve, and nothing more.

One thing a consumer must not read into it: a dense `support.json` is not
evidence that a segment is registrable. Section 4.3 of the research is clear
that registration quality is bounded by `span/depth` -- the parallax within a
segment -- and this file says nothing about that. Persisting the association
removes an obstacle; it does not move the ceiling.
