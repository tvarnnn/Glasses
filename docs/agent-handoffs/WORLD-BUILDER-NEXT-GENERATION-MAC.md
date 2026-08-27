# World Builder `next-generation` — Mac / iOS handoff

**From:** World Builder lane (Tower)
**Branch:** `world-builder/next-generation`
**Base:** `origin/integration/world-builder-lifecycle-v1` @ `25eb794`
**Status:** **NO IOS CHANGE REQUIRED.** Two FOLLOW-UPs, one FUTURE.
**Covers:** point-quality gates, refusal accounting, solve-chain segmentation.
**Tower tests:** 430 passed, 10 skipped.

---

## 1. What changed on the Tower, in one paragraph

Triangulated landmarks whose two rays are parallel to within pixel noise, or
which reproject badly, are no longer **published**. They still exist in the
solver's map — they are usable bearings for PnP — but the world no longer states
a coordinate for them. Nothing about tracking, keyframe selection, or pose
solving changed: segments, keyframes and solved poses are byte-identical across
the pinned eight-capture corpus.

## 2. Why you should care, even though there is nothing to implement

**This is the change that should make fragments look like rooms.**

`WorldFragmentsView.swift:78-80` fits each fragment card to the manifest's
`bounds`, which is min/max over all points. A handful of unconstrained rays were
setting that box. Measured on the reference world, the full extent was **329x**
larger than the geometry inside it, and simulating your projector on a 140pt
card put **2,908 of segment 19's 3,033 points into a single pixel**.

Across the corpus, fragments whose real geometry occupies at least 20pt of a
140pt card went from **28 of 48 to 47 of 48**, and the worst bounding-box
overrun fell from **387.68x to 4.44x**.

You get that for free because the renderer already fits to `bounds`, and
`bounds` is now computed over a cloud that is not being dragged out to 10^5 units
by a dozen bad points.

## 3. Wire changes — all additive, no contract bump

`GEOMETRY_CONTRACT` is unchanged at `world_builder.geometry/2026-08-25`. Per the
contract's own policy (`results/world_builder_geometry.py:189-193`), a field an
older decoder ignores is not grounds for a version change.

The **build manifest** (`derived/manifest.json`, not the HTTP payload) gains:

```json
"points_discarded":   { "low_parallax": 7251, "high_reprojection": 5106 },
"points_triangulated": 59786
```

`points + low_parallax + high_reprojection == points_triangulated`, exactly.

**Neither field is on the HTTP geometry manifest or the segment chunks today.**
Your decoders are guard-list based on required keys and ignore unknown ones, so
nothing breaks either way.

### What you WILL observe change on the wire

| field | change | why |
|---|---|---|
| `point_count` per segment | **falls, ~20%** | refused landmarks are not published |
| `points[]` in each chunk | **fewer entries** | same |
| `bounds` | **much tighter** | the outliers setting it are gone |
| `content_hash` | **changes** | it hashes poses+points, and points changed |
| `segment_index`, `keyframe_count`, `solved_count`, `resolution_state`, `dominant_degeneracy` | **unchanged** | nothing in the solve moved |

**Cache behaviour is correct here and needs no work.** `content_hash` covers
points, points changed, so every cached chunk correctly invalidates. (This is
*not* true for a future registration change — see §6.)

## 4. What to expect on device — the acceptance criteria

Run against a world built by this branch.

**PASS looks like:**
- Fragment cards show recognisable structure spread across the card rather than
  a dot plus a scatter of specks.
- Segments that previously rendered as near-empty cards — the ones with the most
  points — are the ones that improve most. That inversion is the tell: before
  this change, the richest fragments were the least legible.
- `unresolvedCount` ("N areas were seen but could not be reconstructed") is
  **unchanged**. This change does not resolve anything new; it stops publishing
  coordinates it cannot defend. If that number moves, something is wrong.

**FAIL signatures, and what each means:**

| what you see | most likely cause |
|---|---|
| Fragments now *empty* rather than tighter | the gate is over-refusing; capture the manifest's `points_discarded` and send it back |
| `unresolvedCount` changed | the change leaked into pose solving; that must not happen |
| Fewer fragment cards than before | same — `segment_count` must be identical |
| Stale geometry after a rebuild | cache invalidation, unrelated to this change but report it |

## 4a. SECOND CHANGE: a broken solve chain now starts a new segment

Landed after the point-quality work. It changes what a **segment** means, so it
is the one thing here you will actually see differ in the fragments grid.

### What it does

`classical.py` has claimed for a long time that when the solve chain breaks "the
engine turns this into a new segment". It did not. The engine split only on
tracking loss, so once a chain broke, every later keyframe in that segment was
refused **without attempting any geometry**. Measured on capture `22e9d428`: 354
refusals from only 26 real decisions, 328 of them cascade, and 0 of 26 segments
ever recovered.

The engine now splits when the chain breaks, provided the broken chain had
solved at least two poses.

### What you will see change

| field | change | why |
|---|---|---|
| `segment_count` | **rises ~81%** (127 → 230 across the corpus) | breaks that used to be silent are now boundaries |
| `solved_count` | **rises ~71%** | keyframes after a break get an anchor and a chance |
| `point_count` | **rises ~59%** | those keyframes triangulate |
| `resolution_state` | more segments `resolved` | same reason |
| `unresolvedCount` on your side | **may rise** | there are simply more segments; some resolve, some do not |

**This is the opposite direction from the point-quality change**, which lowered
`point_count` per segment. Net across both, the corpus went 47,429 → 75,369
published points in more, smaller segments — with the *largest* segment in every
capture holding the same geometry it held before.

### What must NOT change

**`keyframes` is invariant.** Tracking and keyframe selection are untouched: the
tracker is deliberately not reset on a solve break, because tracking is healthy
and only the solve failed. If `keyframes` moves between a build on this branch
and one on the base branch for the same capture, something leaked.

### A new event kind

`solve_chain_broken` joins the closed `EVENT_KINDS` set. It is deliberately
**not** `tracking_lost` and deliberately does **not** set `last_tracking`: a
consumer must not read a geometry failure as the wearer having lost the world.
If anything on your side switches exhaustively on event kind, it needs to
tolerate this one.

---

## 5. FOLLOW-UP (not required now)

Tower now knows, per build, how many landmarks it refused and why. Nothing
surfaces it.

Once `points_discarded` is added to the HTTP manifest (it is not yet — say the
word and it is a one-line addition on this branch), a truthful line in the
fragments view would be:

> "12,357 measurements were too uncertain to place."

That is a different and more honest statement than the existing "N areas were
seen but could not be reconstructed", which counts tracking-loss windows. Do not
merge the two counts; they answer different questions.

### Second follow-up: fragment ranking

More segments means more fragment cards, and the grid has no ordering or
filtering. The manifest already carries `point_count`, `solved_count` and
`keyframe_count` per segment; ranking by `point_count` would put the parts of
the room that were actually mapped first. There is a larger prize behind this:
an unrestricted version of the segmentation change measured **poses 346 → 863
and points 47k → 107k** against the shipped 591/75k, and was held back only
because it produces ~470 segments, which is unusable in an unranked grid.
Registration is identical either way, so the extra fragments are raw geometry
rather than coherence. If fragments can be ranked or
collapsed, that variant becomes available.

**Do not** render refused points in a dimmed colour. Their coordinates are not
approximately right — they are unconstrained, sometimes by four orders of
magnitude. Drawing them anywhere would be a fabrication.

## 6. FUTURE — the trap waiting in registration

Recorded here so it is not discovered the hard way when registration ships.

`content_hash` deliberately **excludes** `transform_to_world`
(`results/world_builder_geometry.py:44-47`), `geometry_revision` is a rollup of
content hashes only, and the status channel's `geometry.revision` is computed
from manifest fields containing no placement. Separately,
`WorldGeometryDecoder.chunk` **does not read `transform_to_world` at all**.

So on the day a segment gains a placement without its points changing:
- its `content_hash` does not move,
- the manifest rollup does not move,
- the status revision does not move,
- and iOS would keep drawing the cached, unplaced version.

`test_no_segment_claims_registration` would not catch it — it asserts only that
the fields are still constants.

**When registration lands, iOS needs (a) to decode `transform_to_world`, and
(b) a cache key of `(content_hash, placement_hash)` rather than `content_hash`
alone.** That is a breaking client-side change and should be planned, not
retrofitted. No action today.

## 7. Physical validation procedure

Not yet run — I cannot wear the glasses.

- **Tower:** `world-builder/next-generation` @ `97dfdfd` or later.
- **iOS:** whatever is current; no Swift change is needed for this slice.
- **Walk:** a normal room scan, 60-90 s. Prefer lateral translation and arcs
  around objects over pure head rotation — the residual refusals are
  concentrated in forward motion, where the epipole sits in the image and
  parallax is genuinely ill-conditioned.
- **Preserve:** the world id, `derived/manifest.json` (for `points_discarded`),
  and a screenshot of the fragments grid.
- **Compare against:** a walk on the base branch if one is available; otherwise
  the corpus numbers in
  `tower/docs/superpowers/specs/2026-08-26-world-builder-point-quality-design.md`
  §5.5.

**Nothing here is settled by replay.** The corpus result says the fragments are
legible at 140pt. It does not say the room is recognisable. That remains
outstanding and only a wearer can answer it.
