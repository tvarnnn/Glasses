# Geometry transport — deferred findings

**Date:** 2026-08-25
**Branch:** `integration/world-builder-lifecycle-v1`
**Source:** nine task reviews plus one whole-branch review of
`2026-08-25-world-builder-geometry-transport.md`.

Every item here was **raised by a reviewer, triaged, and deliberately not
fixed**. The whole-branch review judged each one "can stand" for merge. This
file exists so that judgement is inspectable rather than lost with the scratch
directory.

Nothing below is a truthfulness defect. The five non-negotiables in the design's
§3.3 were verified holding end to end.

---

## Tower

| # | Finding | Why it can stand |
|---|---|---|
| 1 | `world_builder_geometry.py` `_REFUSED` hardcodes `"unavailable"` / `"rotation_only"` rather than importing `POSE_STATUS_*` from `world_builder.schema`, which the same file already imports `POSE_CONVENTION` from | Values verified matching; drift risk is low but real. Cheapest item here |
| 2 | No test asserts `dominant_degeneracy is None` for a **resolved** segment with no refusals; only the unresolved case is covered | Behaviour verified correct by reading |
| 3 | No unknown-**session** route test (unknown world and unknown segment are both covered) | Behaviour traced correct: `read_derived` returns `None`, route 404s |
| 4 | `world_builder_geometry.py` `world.pose_convention or POSE_CONVENTION` — the fallback is unreachable, since `records.py` supplies a `default_factory` and `store.py` refuses anything unequal to `POSE_CONVENTION` | Harmless, but the `or` implies a fallback that cannot fire |
| 5 | `routes/geometry.py` takes caller-controlled `world_id` / `session_id` into filesystem paths. `session_id` is a query param, so no URL normalisation applies | Reads are gated by the digest check and confined to `poses.json` / `points.json`. **This is the first Tower route taking caller-controlled ids to disk** — worth a deliberate look before anything less constrained follows it |
| 6 | Stray mid-file imports in `test_world_builder_geometry_transport.py` (inherited from the plan's own snippets) | Cosmetic |

## iOS — all BUILD UNVERIFIED

| # | Finding | Why it can stand |
|---|---|---|
| 7 | `WorldGeometryClient` — non-404 statuses (a 500, or a 422 from a missing `session_id`) decode their `{"detail": …}` body fine and then surface as `.undecodable`. A `2xx` guard would be honest | Diagnostics quality only; the brief asked for 404 |
| 8 | A `JSONSerialization` throw is labelled `.transport` where `.undecodable` is truthful | Same |
| 9 | `CancellationError` is swallowed into `.transport` | Same |
| 10 | `URLComponents.queryItems` does not encode `+`; a session id containing one would arrive as a space | Session ids are hex today |
| 11 | `WorldGeometryClient`'s default property values make its memberwise init `@MainActor`; a future **client** test in the nonisolated test target would need `await MainActor.run` | Not hit today — Task 9's tests construct it successfully |
| 12 | `WorldGeometryStore.hashesMissing(from:)` is dead production code, pinned by two tests | Dead code with a maintenance cost. Delete both, or use it to skip the cached-segment loop |
| 13 | `WorldFragmentsModel.fragments` filters on `resolutionState`, not `pointCount`; a `.resolved` segment with `pointCount == 0` and non-nil bounds would still get an empty tile | Not a fabrication — an empty tile is honest |
| 14 | A chunk that has not arrived yet renders a blank tile beside a "N points" label rather than saying "loading" | The label and the tile disagree. **More visible now** that behind-the-journal geometry is served during a walk |
| 15 | An isolated valid pose between two refusals produces a lone `move(to:)` and strokes nothing | Honest, but invisible |
| 16 | No in-flight fetch dedup or cancellation; each revision change starts a full manifest+segment chain | Staleness guards make it *correct*, just wasteful. Can stack several chains on a live walk |
| 17 | `WorldBuilderClient` fetches **every** segment the manifest names, including the ~32 of 51 that resolved to nothing and are never drawn | ~51 round trips where 19 are usable. The clearest efficiency win on this list |
| 18 | `WorldFragmentsModel.headline` returns `"1 world"` once `hasSharedFrame` is true, while the grid still renders one tile per segment | Safe — no compositing — but the two disagree. Only reachable after registration lands |
| 19 | Duplicate contract assertion across `testTheAdoptedContractIsTheOneThisBuildDeclaresItImplements` and `testTheTowerDeclaresOnlyTheWorldBuilderContract` | Redundant, not wrong |
| 20 | The `URLProtocol` test stub uses lock-guarded static state; `protocolClasses` relies on array-literal coercion to `[AnyClass]` | Unsafe only under in-process parallel testing |
| 21 | Dead `upAxis:` parameter in the `manifestJSON` test helper | Cosmetic |

---

## Measure this first on the Mac

`WorldCanvasView` is re-evaluated at the **24 Hz capture rate** (its own doc
comment on `explanation` says so), and it now carries a
`[String: WorldSegmentChunk]` by value. Dictionaries are copy-on-write, so that
is a retain/release per body rather than a copy of 12,023 points — but
`LazyVGrid` + `Canvas` re-rendering at 24 Hz during capture has never been
measured, and this is the first build where it happens.

## Closed, recorded because the ruling was wrong

`from tower import world_builder` in shared code used to evade
`test_shared_code_does_not_import_a_cartridge`, because `_imports()` recorded
only `node.module` for an `ImportFrom` and discarded the imported name. I parked
this as "unbounded work that may surface unrelated latent violations."

**That was fear, not evidence.** A reviewer tested it: extending `_imports()`
yields **zero** offenders across `tower/`. It was a two-line change and it is
now fixed (`55c2149`), with the probe recorded — adding
`from tower import world_builder` to a shared file now fails the check where it
previously passed.
