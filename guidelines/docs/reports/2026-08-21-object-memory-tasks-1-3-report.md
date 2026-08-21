# Object Memory First Slice — Tasks 1–3: Implementation Report

Status: **DONE and merged.** Data layer only. Tasks 4–8 of
`docs/superpowers/plans/2026-08-20-object-memory-first-slice.md` remain
blocked on a user ruling at that plan's Task 4 decision gate.

- Date: 2026-08-21
- Branch: `feat/object-memory-first-slice-tasks-1-3` (7 commits)
- Suite: **210 passed, 3 skipped** (from a verified 177/3 baseline; +33)
- Milestone context: works toward `03-ROADMAP.md` V1.2 (First Promoted
  Production Module). Does **not** complete it.

## What was built

Three standard-library-only modules under `tower/object_memory/`. None of
them import torch, so a Tower running the `baseline` experiment starts
unaffected.

| File | Responsibility |
|---|---|
| `records.py` | `Confidence` enum + `ObjectObservation` frozen dataclass (15 fields) and its JSON round-trip. Pure data. |
| `relevance.py` | `RelevancePolicy` / `RelevanceFilter` — decides which detections are worth persisting. Pure logic. |
| `store.py` | `ObservationStore` — JSONL append/read/`last_seen`/`purge`/`prune_expired`. The only filesystem toucher. |

**Nothing consumes them yet.** The detector, the `Module` subclass, and the
HTTP query/purge endpoints are Tasks 5–7, gated behind Task 4. This is a
data layer shipped ahead of its producer, deliberately.

## Truthfulness and privacy properties, as actually verified

- `observed_at` is **tower-receipt time, not capture time**, and the
  `time_basis` field records that explicitly. No capture timestamp exists
  on the wire (`tower/frames.py` carries no time field), so the record
  cannot claim one (Rule 16).
- **`Confidence` is persisted as its label and never recomputed** from
  `detector_score` on read. A later threshold change therefore cannot
  retroactively re-label history.
- **There is no soft-delete flag.** `purge()` and `prune_expired()` hard-
  delete. `06-PRIVACY-DATA.md` forbids hiding data from a query interface
  as a substitute for deletion.
- Retention keys off **`recorded_at`, not `observed_at`** — how long *we*
  held the data is the privacy-relevant clock. Now pinned by a test using
  divergent values.
- Derived data only: no crops, no frames, no embeddings. The only spatial
  data is a `bounding_box` of floats.

## Defects found and fixed during review

Every task passed its spec review on the first pass with no scope creep.
The value came from the reviews, which found four real defects — two of
them privacy-critical.

**1. A rewrite temp file defeated `purge()` (Critical).** `_rewrite` wrote
`observations.jsonl.tmp` then `replace()`d it. A crash in between left a
full copy of observations that nothing read, pruned, or deleted — while
`purge()` still returned a success count. Reproduced directly: after
`purge()` returned `1`, the directory still held `observations.jsonl.tmp`
containing a readable record. Because `all_observations()` never opened
that path, the data was invisible to queries *and* unreachable by the
delete API — worse than hiding. Fixed: `purge()` removes every artifact the
store owns, `_rewrite` unlinks its temp on any failure, and the rewrite
flushes and `fsync`s before replacing.

**2. `prune_expired` could wipe the entire store and report `0` (Critical
— a regression introduced mid-run by this session's own ruling).** An
earlier fix made prune rewrite whenever unparseable lines existed, to close
a hole where a corrupt line outlived its retention window. But the read
path treated `KeyError`/`ValueError` as "unparseable", and those fire on
**valid JSON with a schema mismatch** — a newly-required field or an
unknown `Confidence` label. So a schema change would delete every record
and return `0`. The plan's own Known Gap 2 schedules exactly that change.
Fixed by parsing in two stages: JSON-decode to raw dicts (counting only
genuinely non-JSON lines as corruption), then convert dicts to records
separately. `prune_expired` now applies the cutoff to the raw dict's
`recorded_at`, so a schema-mismatched record within retention survives.

**3. Rewrites destroyed the reserved forward-compatibility fields
(Important).** `records.py` documents `spatial_ref`/`external_refs` as
carried "so a later cross-module need does not require rewriting
already-persisted records" — but the old rewrite round-tripped through the
current dataclass and dropped any key it did not know, including exactly
those. Fixed as a side effect of (2): the rewrite now serialises raw dicts,
so unknown keys survive. Verified — an unrecognised key is preserved
through a prune that genuinely rewrites the file.

**4. No synchronisation between `append` and the mutating operations
(Important).** `append` runs in the frame path while `purge`/`_rewrite`
unlink and replace the file. On Windows a concurrent purge raised
`PermissionError` and **left the data in place**; on POSIX an interleaved
append was silently lost. Task 7 will run purge in FastAPI's threadpool
against a live append path. Fixed with a single non-reentrant
`threading.Lock` — the first lock in `tower/`. Verified: 300 concurrent
appends against 60 purges now produce zero errors.

## Deferred, with reasons

- **Reads do not apply the retention cutoff.** Retention is enforced only
  by `prune_expired`, which the plan calls only from `_do_load`. A
  long-running tower therefore *serves* expired observations until the next
  prune. Not fixed here: read-time filtering requires injecting a clock
  into a store that is currently clock-free and deterministic to test.
  Recorded in the plan as a hard Task 6 requirement — prune on a cadence.
- **`purge()`'s count is parseable observations, not lines deleted.** With
  a corrupt line present it returns fewer than it erased. Judged correct
  (a corrupt line is not an observation) and now documented and tested
  rather than accidental.
- **Bystander/`person` observations.** COCO includes `person`; wiring this
  up would persist a record per bystander. A privacy/product decision, not
  an executor's — escalated, not decided. No exposure today: nothing is
  wired.
- Minor: `_parse_observations`'s warning lost the line-number detail the
  unified read path had; `object_observation_from_json_dict` still
  hardcodes the two reserved fields at the object level (the on-disk
  promise is what was fixed).

## Test coverage note

Three behaviours were found to be **claimed but unverified** — mutation
testing showed the suite passed with the implementation deliberately
broken: the retention clock choice, `last_seen`'s newest-by-timestamp
semantics, and `Confidence.from_score`'s exact bucket boundaries. All three
are now pinned. Load-bearing prose in a comment is not coverage.
