# Scene Understanding on the wire — design

**Date:** 2026-08-26
**Lane:** Tower / cartridges (`integration/world-builder-lifecycle-v1`)
**Status:** designed, not implemented. Contract identifier
`scene_understanding.live/2026-08-26`.

Unblocked by the module lifecycle ruling — see
`research/2026-08-26-lifecycle-load-timeout.md`. Before it, a live module
could not load a model under an enforceable bound, and this cartridge
**must** be live: it has no store by design, so the journal-follower
pattern that gave Object Memory a route is unavailable to it.

---

## 1. What the cartridge actually computes

Verified by reading `tower/tower/scene/`, not from its design docs:

- **Confirmed-track counts** (`engine.observe`) over 13 `CLASSES_OF_INTEREST`.
- **Tracks** — IoU-only association, session-scoped integer ids.
- **`left_of` / `right_of` / `higher_in_view`**, and `describe_position`
  (normalised x/y, `side`, `view_offset`).
- **Coarse facing** — **off by default**: `_pose` is `None`, and
  `orientation_enabled` additionally requires one real success.

`in_front_of`, `behind`, `on`, `inside`, `near`, and
`nearer_than_same_class` are **refused data, not gaps** — see §4.

## 2. The privacy position, which drives the payload

The reflex is to minimise disclosure. The correct analysis is narrower and
sharper:

> **Tower → phone is inside the local-first boundary.** The phone sent the
> pixels. A count therefore discloses strictly *less* than the frame the
> phone already holds, and withholding it while shipping frames is theatre.

**What is genuinely new is joinability.** A stable `track_id` plus a
timestamp lets a client assemble the per-person dwell timeline that Tower
refuses to keep — **persists-nothing laundered onto the consumer.** The
cartridge's strongest property would be defeated not by what it says, but
by what a recipient could accumulate from it.

**Therefore excluded from the wire, for people:**
`track_id`, bounding boxes, `normalised_x` / `view_offset`, per-person
facing state, and `visible_eyes` / `visible_ears`. Facial-landmark evidence
must not cross the boundary at all. Facing is an **aggregate count or
`null` with a reason** — never zero. Position is `side` only, and only for
**non-person** labels.

## 3. Payload — `scene_understanding.live/2026-08-26`

Self-describing, in the style Object Memory established:

- `claim: "visible-now-not-a-record"`,
  `identity: "anonymous-and-unpublished"`,
  `absence_means: "not-visible-to-this-cartridge"`,
  `persistence: "none"`, `frame_of_reference: "camera"`,
  `time_basis: "tower-receipt"`.
- `observed_at` float|null, `staleness_seconds` float|null,
  `frames_observed` int, `frames_skipped` int.
- `detector`, `score_threshold`, `reported_classes` (the fixed 13 — fixed
  arity keeps `counts` bounded), `counts: {label: int}`,
  `count_basis: "confirmed-tracks"`.
- `people: {count, may_include_wearer: true, validated: false,
  facing_wearer: int|null, facing_answered, facing_unavailable_reason,
  oldest_estimate_seconds}`.
- `where: {label: "left"|"centre"|"right"}` — **non-person labels only**.
- `relations: null` plus `relations_absent_reason` and
  `refused_relations: [...]`.

`may_include_wearer: true` and `validated: false` are not hedging: the
corpus `person` boxes **are** the wearer's own torso, and no bystander
footage exists on this host, so an unqualified count would overclaim.

**Added 2026-08-26 — every count is an UNDERCOUNT, and must say so.**
Measured against a `fasterrcnn_resnet50_fpn_v2` oracle over 14,128 real
frames (`research/2026-08-26-detector-oracle-and-the-size-floor.md`), the
shipped detector's recall is **0.306 for `person`**, 0.497 for
`cell phone`, 0.209 for `tv` — and it is effectively **blind below ~2% of
frame area** (recall 0.000 under 1%). Disagreement is overwhelmingly
missing rather than inventing: 40,075 misses against 5,660 inventions.
And because the oracle shares COCO training data with the shipped model,
**0.306 is an upper bound**, not an estimate.

So the payload requires `count_is_lower_bound: true` and a
`count_limitations` entry naming the size floor. A count published without
it is a new overclaim of exactly the kind this cartridge's contract exists
to prevent — and the failure is invisible, because an undercount looks
like a quiet room.

`SCORE_THRESHOLD` is **not** the lever: the F1 sweep is a plateau (0.512 at
T=0.20 → 0.467 at 0.40) and lowering it buys +0.05 recall for 1.7x the
false boxes. The floor is the model's, not the threshold's.

**Every boolean must be wrapped in `bool()`.** `bool` subclasses `int` in
Python, and a `registered: 1` already shipped once this run and would have
failed every Swift `as? Bool` decode.

## 4. Refusals the contract must make unexpressible

`in_front_of` / `behind` were **measured and refused** on real frames
(`research/2026-08-26-depth-ordering-on-real-frames.md`): the flip rate is
fine while static and collapses under motion — 0.0% (n=124) → 11.5% (n=52)
at *matched* separation — and the corpus contains no walking, so the regime
the relation needs is unsampled.

**No field may be capable of holding such a relation.** `relations` is
`None` and no schema slot accepts `"in_front_of"`. A refusal that depends
on remembering not to populate a field is not a refusal.

**Also excluded:** "where is the desk / chair". `dining table` appears
**once in 9,199 frames** and `chair` in 4 of 340 — publishing that is
publishing detector noise. Orientation stays off by default.

## 5. Cadence and overrun

**Publish at the existing hub poll (0.5 s) with the 2 s heartbeat — not at
12 Hz.** The result sender shares an `asyncio.Lock` with the frame path,
and starving frame delivery is exactly what forced World Builder's geometry
onto HTTP. `side`-granularity fields keep `revision` stable so coalescing
works; `observed_at`, `staleness_seconds` and `frames_*` are excluded from
`revision`, following the `mapping_seconds` precedent.

The engine runs **off-loop in a single-slot worker** fed by
`frame_observers`. Busy → drop the frame and increment `frames_skipped`,
which is why that field is on the wire: a silently dropped frame is
indistinguishable from a quiet room.

Detector load goes through `run_abandonable` + `LoadInvalidation` under
`LOAD_TIMEOUT_S`.

## 6. The two blocking tests — RULINGS

### 6.1 `test_shared_code_does_not_import_scene_understanding` — extend the exemption

Precedented. `_RESULT_CHANNEL_ADAPTERS` already exempts
`results/world_builder.py`, `results/world_builder_geometry.py` and
`results/__init__.py`. A Scene adapter is the same shape and takes the same
exemption. **Low risk; the boundary is unchanged in intent.**

### 6.2 `test_scene_understanding_is_not_registered_as_a_production_module` — rewrite ONLY if unavoidable, and only to a stronger assertion

Today it reads:

```python
assert "tower.scene" not in main
assert not (TOWER / "modules" / "scene.py").exists()
```

**The second assertion is the real invariant and must survive verbatim.**
Scene must never become a `Module`.

The first is a **proxy**. It is about to become wrong while the property it
stands for stays true, because `_build_frame_observers` lives in `main.py`
and `main.py:68` is explicitly "the ONE place in the web process that knows
a world builder exists — and it knows it as an argv". A live in-process
observer cannot be wired that way.

**Ruling, in order of preference:**

1. **Preferred: do not touch this test.** Wire the observer through a
   factory in another module that `main.py` imports generically, exactly as
   it already does `from tower.results import build_hub`. `main.py` should
   not have to know every cartridge; this is better architecture, not a
   dodge, and it keeps the guard at full strength.
2. **If that is genuinely not possible**, rewrite to assert the *property*
   rather than the proxy: `modules/scene.py` does not exist (verbatim),
   Scene is never the `ModuleContainer`'s module, and no Scene class
   subclasses `Module`.

**Binding condition on option 2:** the rewritten test must be **proven to
fail** when Scene *is* registered as the production module. A rewrite that
cannot fail is a deleted test wearing its name. Demonstrate the red.

## 7. Test plan

- **Extend `test_scene_understanding_persists_nothing` from
  `tower/scene/**` to every file on the wire path** — adapter, observer,
  producer. Otherwise "publish" quietly becomes "buffer to disk", which is
  the single most likely way this change destroys the cartridge's best
  property.
- Assert **no** `track_id`, `box`, `x0`, or `visible_eyes` substring appears
  anywhere in a serialised payload.
- `bool` **identity** on every boolean field, not truthiness.
- Payload ≤ 8 KB with all 13 classes saturated.
- `relations` is `None`, and no schema slot accepts `"in_front_of"`.
- Publishing changes no `SceneState` — observation must not mutate.

## 8. iOS consequence — FOLLOW-UP, not required now

Supersedes §5.3 of `docs/agent-handoffs/IOS-EXECUTION-PLAN.md`, which
currently says "build no Scene Understanding UI".

A new `(scene_understanding, status)` offer; subscribe / coalesce / error
machinery unchanged. Required behaviour: render `null` as **"not
measured"**, never as 0; never persist a snapshot; no relation UI.
Acceptance: `facing_wearer: null` renders as a refusal string, not a zero.

**The Mac lane implements this. This lane does not touch `ios/`.**
