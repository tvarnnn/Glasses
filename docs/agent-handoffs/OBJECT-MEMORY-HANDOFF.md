# Object Memory — lifecycle, policy and semantics

**Autonomous overnight run, 2026-08-27.** Tower lane, Object Memory
cartridge. This document is the durable record: what was built, what was
measured, what was rejected, what is still owed, and exactly what the Mac
lane needs to do.

| | |
|---|---|
| Branch | `object-memory/lifecycle-and-semantics-v1` |
| Worktree | `C:\Users\tvllo\Projects\Glasses-object-memory` (isolated; the primary tree stays on `integration/world-builder-lifecycle-v1`) |
| Starting commit | `6e325f8` — *measure: the shipped detector is blind below 2% of the frame* |
| Commits | `d5000b7` lifecycle · `f489da5` policy · `5b329ad` semantics · plus the documentation commit that carries this file |
| Push status | pushed to `origin/object-memory/lifecycle-and-semantics-v1` |
| Tests | **1650 passed, 64 skipped** (was 1513 / 64 at the starting commit) |
| Never touched | `ios/**`, `tower/tower/world_builder/**`, `main` |

---

## 1. What was wrong, in the words of the physical run

A real Ray-Ban → iPhone → Tower → Object Memory → HTTP → iPhone run
succeeded on 2026-08-26: 2,203 frames, 0 undecodable, 4,287 detections,
9 new observations, 0 write failures, 64 stored, and the iOS app
displayed real laptop and phone memories with their timestamps.

Getting there cost a human four manual steps:

1. start a generic Home recording;
2. find the capture directory that had just been minted;
3. run `object_memory_session.py --follow-capture <dir>` in a second
   terminal;
4. set `TOWER_OBSERVATION_ROOT` to the directory the producer had
   *already defaulted to*, because until then every HTTP request answered
   404 about the memory that had just been written.

And what it remembered was two COCO classes, timestamped, with no picture.

**None of the four steps exists any more, the two classes became a
measured policy, and the pointer became a picture.**

---

## 2. The five things that changed

### 2.1 A cartridge you can start and stop

`CartridgeSession` (`tower/tower/cartridge_session.py`) is a three-state
machine — `stopped` / `active` / `paused` — in **shared code that knows no
cartridge**. It is handed a worker name, a supervisor and a way to ask
what is recording. The next producer that needs a button gets it free.

`POST /cartridges/object_memory/session/{start,pause,resume,stop}` and
`GET /cartridges/{cartridge}/session`. Contract
`cartridge_session.control/2026-08-27`, documented in
`docs/contracts/OBJECT-MEMORY.md` §9.

Decisions worth knowing:

- **Pause detaches the producer** rather than signalling it to idle. The
  alternative was a control file the producer polls, and it was rejected:
  it would give the web process a write into the cartridge's own
  directory, add a second source of truth for whether the cartridge is
  running, and go stale after a crash. Stopping the process is observable
  in the process table and cannot go stale. It costs one model load to
  undo.
- **`state` is intent; `following` is fact.** The payload says
  `state_means: "intent-not-liveness"`. An `active` session whose producer
  died is the "looks successful but does nothing" failure the whole
  surface exists to make visible.
- **Refusals are 409, not 200 with a flag.** An action that could not be
  honoured is not a fact about anything, and a client that ignored the
  body would read 200 as "paused".
- **Nothing is persisted.** A Tower restart comes back `stopped`.
- **A producer attached mid-walk is told it arrived late**
  (`--attach-mode from-now`, `CaptureFollower(start_at_end=True)`). A
  wearer who starts remembering at 15:03 has not asked for the 15:00 part
  of the walk to be remembered, and reading it back would be a consent
  decision no script has standing to make.

### 2.2 A supervisor that runs more than one thing

`CaptureWorkerSupervisor` ran exactly one spec, and that slot was taken by
the world builder. It now runs a **list**, each named, each optionally
gated by a predicate the wiring point supplies, with **per-spec lineage
bookkeeping** — a dead builder must not make the Tower believe the
producer is dead too.

It stays cartridge-blind: it runs an argv and a callable.
`test_the_capture_worker_supervisor_is_cartridge_blind` still passes
without an exemption.

### 2.3 One observation root

`tower/config.py` owns `DEFAULT_OBSERVATION_ROOT` and hands the **same
string** to the read routes and to the producer's argv. There is no
second default to drift.

**The unset-means-404 default is reversed**, and the reasoning is the
important part. It defaulted to `None` on the grounds that "a memory of
what a wearer's camera saw does not go on the network because a process
happened to start in a directory that has one". The physical test showed
what that bought: the producer wrote 64 observations regardless, and the
only thing the unset default prevented was **the wearer reading their own
memory back**. Data existed, nothing served it, no log line said why. A
default that hides data from its owner while still storing it protects
nobody.

The switch moved to `TOWER_OBSERVATION_ENABLED`, where the decision
actually is. The 404 state still exists and is still reachable.

### 2.4 A relevance policy made of evidence

Full evidence:
`tower/docs/superpowers/research/2026-08-27-object-memory-corpus-precision.md`.

Every figure this cartridge had been designed against described the
**detector's opinion of itself**. Nothing in the repository had ever
looked at a crop. So every detection over all 18,821 real frames was
dumped, grouped into sightings, and the strongest frame of each sighting
was cropped onto a contact sheet and **read by eye**:

| class | inspected | correct | the wrong ones |
|---|---|---|---|
| laptop | 24 | **24** | — |
| cell phone | 24 | **24** | — |
| **remote** | 8 | **3** | the three **highest-scoring** are laptop keyboards (0.87, 0.77, 0.71) |
| refrigerator | 6 | **0** | a white door with light switches, at **0.95** |
| airplane | 7 | **0** | a ceiling fan, at **0.99** |
| scissors | 4 | **0** | the same ceiling fan, at **0.93** |
| chair | 6 | 5 | a phone held in a hand, at **0.94** |

**Score does not order correctness across classes.** And the objects
people lose — keys, wallet, glasses — have **no COCO class at all**.
Together those say that widening a class whitelist over this detector
alone would fill a wearer's memory with ceiling fans.

So the policy became:

- **`classes.py`** — four tiers, with the counts behind each carried as
  data. `remembered` is written on the detector's word; `verify` only if
  something else agrees; `context` is furniture (a live question that
  belongs to Scene Understanding, not a permanent record); everything else
  ignored. `person` is **not a tier**: a separate constant, checked first,
  unreachable by any model.
- **`sightings.py`** — the unit of memory is a run of frames in which a
  class stayed in view, broken by a gap over 3 seconds. Over the corpus:
  763 sightings, 499 of at least three frames, 404 excluding `person`.
  Three frames because 264 of the 763 are one- or two-frame flickers.
  The 30-second resample window is gone; it was an interval with no
  relationship to what the camera did.
- **`RelevanceFilter` holds no state at all.** The `last_recorded_at`
  table *was* the resample window.
- **A part is not a second memory.** A `keyboard` sighting is suppressed
  while a `laptop` sighting is open — concurrent, not blanket, because
  the other keyboard record in the same replay is a lit mechanical
  keyboard at a desk with no laptop near it.

### 2.5 A second opinion, and a picture

**The verifier.** `google/owlv2-base-patch16-ensemble` — Apache-2.0,
155 M parameters, plain `transformers`, no compiled operator. Benchmarked
against `llmdet_tiny` over 94 human-labelled crops:

| model | accepts correct | rejects wrong | median ms | peak VRAM |
|---|---|---|---|---|
| **owlv2-base** | **0.949** | 0.857 | **128** | 842 MB |
| llmdet-tiny | 0.407 | 1.000 | 3,508 | 1,648 MB |

Asked once per sighting: **53 verify-tier sightings across 18,821
frames**, one call per 355. On the validated capture, one run at a time:

| | observations | ms/frame | verifier calls | model time |
|---|---|---|---|---|
| `--verifier none` | 8 | 69.262 | — | — |
| `--verifier owlv2` | 13 | 69.487 | 7 | 1.50 s |
| `owlv2` + part-of rule | **12** | — | **5** | 1.05 s |

**+0.225 ms/frame — 0.3% — for five more memories.** Queue peak depth 0,
zero backlog drops.

**The picture.** `/object-memory/observations/{id}/{imagery,frame,crop}`.
The handle is **derived**, so the 64 records already on disk are
addressable with no migration and no rewrite of a wearer's memory. Every
picture passes a face filter on the way out; a Tower whose weights are
missing serves **nothing**; the label says `display-filter/...` because
the stored frame is unchanged. A record whose imagery has aged out
answers **410 with `memory_retained: true`**.

---

## 3. The model decision, and what was rejected

The brief said to decide rather than to present a menu. The decision is
`owlv2-base-patch16-ensemble`, and the reasoning is architectural rather
than a leaderboard reading.

| candidate | verdict | why |
|---|---|---|
| **OWLv2-base-patch16-ensemble** | **chosen** | Per-query design: 31 prompts give 31 scores, so "did the proposed label rank first" has an answer. Apache-2.0. 128 ms, 842 MB peak. |
| LLMDet-tiny | rejected | Stronger on LVIS rare-class AP, and the wrong shape. Phrase grounding returns text *spans* (`a set`, `a pair`, `a`) that must be string-matched back to classes; scored 0/24 on `cell phone` under that mapping. 3.5 s a crop, 27× slower, because cross-attention scales with text length. |
| OmDet-Turbo | not benchmarked | Its weight download failed on this host with a Windows symlink privilege error. Noted rather than concluded. |
| Grounding DINO 1.5+ / DINO-X | rejected unbenchmarked | API-only. A cartridge that sends a wearer's frames to a vendor endpoint is a different product. |
| YOLO-World / YOLOE | rejected unbenchmarked | GPL-3.0 in its own repo and **AGPL-3.0** through Ultralytics — the same model under two copyleft licences depending on the import. YOLO-World also pins `torch==1.11.0`, impossible on sm_120, and had the worst measured motion-blur collapse of the family. |
| SAM 3 | rejected | No longer Apache-2.0. |
| MobileCLIP2, AIMv2 | rejected | Research-only licences. |
| Qwen2.5-VL-3B | rejected | Non-commercial (the 7B is Apache; the 3B is not). |
| A small VLM as the *matcher* | rejected on evidence | Every candidate small VLM is at or below chance on "are these the same object" on the 561k-query Twin benchmark. Do not ask a VLM that question. |
| A real multi-object tracker (ByteTrack / BoT-SORT / OC-SORT) | rejected for now | `EgoTracks` (5,708 egocentric videos, 602.9 h) puts off-the-shelf trackers at 20–37 AO on first-person footage, with recall far below precision — they give up rather than misfire, which is the wrong failure direction for a memory. A tracker's motion model assumes the camera is still; here the opposite is true. Class-level sighting association asks much less and cannot be wrong the way a broken motion model is. |
| Cross-session instance identity (DINOv2 / CLIP embeddings) | **deliberately not built** | See §5. |
| ConceptGraphs / HOV-SG / OpenMask3D style 3D scene graphs | rejected | 2.0–8.1 s/frame; 11 h 12 m for one Replica scene; and OpenLex3D — an independent re-benchmark — puts object-retrieval mAP for the whole family at **1.45%–11.47%**. Also: Object Memory does not run SLAM. |

---

## 4. Every measurement, in one table

Host: RTX 5070 (Blackwell, sm_120) 12 GB, driver 596.21, torch
2.13.0+cu132, Windows 11, 20 logical cores. Corpus: 34 captures, 18,821
frames, 360×640.

| what | figure |
|---|---|
| detections ≥0.15 / ≥0.4 / ≥0.5 / ≥0.7 | 78,546 / 30,727 / 24,028 / 14,613 |
| sightings (≥0.5, gap 3 s) | 763; 499 at ≥3 frames; 404 excluding `person` |
| sightings by tier (≥3 frames) | 158 `remembered`, 53 `verify`, 158 `context` |
| detector, CPU, validated capture | 152.6 s / 2,203 frames = **69.262 ms/frame**, 4,287 detections |
| detector, CUDA, same | 221.3 s = 100.436 ms/frame, 4,285 detections |
| read + JPEG decode | 1.06 ms/frame, 46 MB RSS |
| producer steady-state RSS | **704 MB** (CPU) / 1,442 MB (CUDA) |
| long-session drift, 6,000 frames | **none** — window-median ratio 0.968 (CUDA), 0.808 (CPU); CUDA reserved plateaus at 436 MB |
| verifier, CUDA | **128 ms** median / 141 p95 per crop; 620 MB resident, 842 MB peak; 5.7 s cold load |
| verifier, CPU | 2,473 ms per crop, +796 MB RSS — **19× slower** |
| verifier accuracy (94 labelled crops) | accept 0.932 / reject 0.943 at min score 0.45 |
| end-to-end cost of the verifier | **+0.225 ms/frame (0.3%)**, 7 calls, peak queue depth 0 |
| face filter firing rate on real frames | **40.2%** of 1,845 frames; median region 12.5% of frame; of 36 inspected, **4 real faces, 32 not** |
| face filter cost | 27.5 ms/frame |

### 4.1 One retraction

A first pass reported that the detector gets monotonically slower over a
long session (49.5 → 87.8 ms across 18,821 frames). **That was wrong.**
It was a *cumulative mean* read off a run competing with a test suite and
a render. Measured directly in windows, one job at a time, there is no
trend and no leak. The claim is retracted in
`scripts/research/detector_long_session.py` and in the research doc.

---

## 5. What was deliberately NOT built

**Cross-session instance identity.** The brief asked for cautious
research, and the research says do not ship it:

- best frozen embeddings: **26.4% Recall@1** on small mass-produced
  objects;
- tracking IDF1 collapses **~100% → ~40%** from identical same-class
  distractors alone;
- zero-shot egocentric object re-ID tops out at **45.3% mAP**;
- humans hit ~0.90 where networks hit ~0.40 on high-similarity pairs;
- and re-run as an *online* task with real detection and tracking, Ego4D
  episodic-memory success collapses to **4.02%** against 81.92% with
  oracle components.

The wire already says `identity: "category-not-instance"` and the shipped
iOS decoder refuses a change to it. That position is now **measured
rather than inherited** — see §6.2 for a correction to how the contract
justified it.

If it is ever revisited, the literature has already determined the shape,
and it is not a cosine threshold: a weighted candidate set rather than a
hard assignment; an explicit "new object / none of the above" hypothesis
(this *is* the "prefer ambiguity" primitive, and it has a published
formalism); spatial and co-occurrence context as a first-class cue rather
than a tiebreaker; and collapse only on evidence accumulated across
observations.

**SLAM, anchors, or anything spatial.** `spatial_ref` stays an explicit
`null`. The shape it will take when World Builder can supply one is
written down in `docs/contracts/OBJECT-MEMORY.md` §12, including the
`anchor_keyframe_id` requirement without which the first loop closure
permanently and undetectably invalidates every earlier anchor.

**Stored crops or embeddings.** The only imagery this cartridge ever
holds is one crop per open sighting, in memory, released when the
sighting closes. Nothing reaches disk.

---

## 6. Contract changes

### 6.1 `object_memory.observations/2026-08-26` — UNCHANGED

Verified against the shipped-but-uncompiled iOS decoder's constraints:
`claim`, `identity` and `absence_means` carry their original values, and
`spatial_ref` is still an explicit `null` at envelope, record and `where`
level. Added fields are additive; a Swift `Codable` decoder ignores
unknown keys.

Added to the observation: `observation_id`, `last_seen_at`,
`frame_count`, `tier`, `verification`. Added to the envelope: `imagery`.

**One thing for the iOS lane to watch:** `recorded_classes` is now
configuration-dependent. Its value on a default Tower is byte-identical
to before — `["laptop", "cell phone"]`, in that order — but a client that
hard-coded those two names rather than reading the list will mis-render a
Tower with a verifier enabled.

### 6.2 A correction to the contract's own reasoning

`docs/contracts/OBJECT-MEMORY.md` §1 said persistent identity was
"forbidden outright by the cartridge brief (`07-PLATFORM-CONSTRAINTS.md`
Core Principle 3)". That citation is wrong twice. Core Principle 3 is
"Absence of Observation ≠ Observation of Absence". And Limitation 6 of
that same document explicitly lists visual embeddings and
"confidence-scored identity association rather than binary identity
claims" as **mitigations**, and says identity "should be represented
probabilistically unless strongly established". The module brief says
*"Do not claim unique-object identity unless the implementation actually
supports it"* — a condition, not a prohibition.

Corrected in place. The behaviour did not change; the justification did,
from an inherited ban to a measured position that can be revisited when
the measurement changes.

### 6.3 Two new contracts

`cartridge_session.control/2026-08-27` (§9) and
`object_memory.imagery/2026-08-27` (§10).

### 6.4 Not declared over the socket, on purpose

`registry.declare()` is **unchanged**. Adding Object Memory to it would
break the pinned iOS test `testTheTowerDeclaresOnlyTheWorldBuilder
Contract`, and this lane may not edit `ios/`. `CARTRIDGE_OBJECT_MEMORY`
exists in `tower/tower/results/contracts.py` because the session URL and
the `/health` row are keyed on it; declaring it is a change both halves
should take together. See §7.4.

---

## 7. For the Mac lane

**Nothing under `ios/` was touched.** These are requirements, not
patches. They belong in `docs/agent-handoffs/IOS-EXECUTION-PLAN.md`.

### 7.1 Run the Tower

```powershell
cd tower
# All of these now have defaults. Only the capture root is mandatory,
# and only because the imagery routes need somewhere to look.
$env:TOWER_CAPTURE_ROOT = "data"
# Optional: unlock the verify tier (~600 MB downloaded once).
$env:TOWER_OBSERVATION_VERIFIER = "owlv2"
powershell -NoProfile -File scripts\start_tower.ps1
```

`TOWER_OBSERVATION_ROOT` no longer needs setting. That was step 4 of the
old manual dance.

### 7.2 The flow to build

```
GET  /cartridges/object_memory/session            -> {state: "stopped", supported: true}
POST /cartridges/object_memory/session/start      -> {state: "active",  changed: true}
     ... the wearer records normally from the Home screen ...
GET  /cartridges/object_memory/session            -> {state: "active", following: ["<capture id>"]}
POST /cartridges/object_memory/session/pause      -> {state: "paused"}
POST /cartridges/object_memory/session/stop       -> {state: "stopped"}
GET  /object-memory/observations                  -> the memories, unchanged shape plus new keys
GET  /object-memory/observations/{id}/imagery     -> whether there is a picture
GET  /object-memory/observations/{id}/crop        -> image/jpeg
```

### 7.3 Six things the UI must get right

1. **Render liveness from `following`, never from `state`.** `state` is
   what the wearer asked for. An `active` session with an empty
   `following` *while a capture is recording* is a producer that died,
   and the copy for it should say so — it is the failure mode this
   surface exists to expose.
2. **`supported: false` disables Start with a reason.** A Start button
   that silently does nothing is worse than one that says why it cannot.
3. **409 is a real answer, not an error toast.** The body carries
   `reason` (`not-active`, `not-paused`, `unsupported`,
   `unknown-action`) and the state actually reached.
4. **410 on `/frame` or `/crop` is "the memory is kept and the picture is
   not".** `memory_retained: true` is in the body. This must not render
   as a broken image or an empty row; it is a true and useful sentence
   about capture-side retention.
5. **`subject_obscured > 0` means part of the object is behind a fill.**
   Say so, or fall back to `/frame`. Do not show a black rectangle
   without comment. Zero `regions_filled` means *nothing was detected*,
   not that nothing was there.
6. **Read `recorded_classes` from the payload.** Do not hard-code
   `["laptop", "cell phone"]`. The existing `ObjectMemoryCopy`
   forbidden-phrase tests generate per-recorded-class phrases; they need
   to generate them from the payload's list, or a Tower with a verifier
   will produce classes the copy safety net never covers.

### 7.4 Two decisions for a human, not for an agent

- **Declare Object Memory over the socket?** It breaks
  `testTheTowerDeclaresOnlyTheWorldBuilderContract` and needs both halves
  landed together. The Tower change is four lines in
  `tower/tower/results/registry.py`.
- **Turn the verifier on by default?** The evidence is in §4 and in the
  research doc. It is one environment variable, it costs ~600 MB of
  weights and ~620 MB of VRAM on a shared card, and it triples what the
  cartridge remembers. The default stays `none` because 94 crops from one
  home justify building it and not switching it on for everybody.

### 7.5 The copy problem the new surface creates

The existing iOS copy is held by a forbidden-phrase test that refuses
present-tense possession and location claims. **A picture is a much
stronger location cue than a sentence**, and no string test can catch it.
The published evidence says that is the *point* — MemPal's last-seen
images were right only 53% of the time and still moved retrieval accuracy
from 0.81 to 0.95 — but it means the caption around the picture is now
doing more work than before, not less. Suggested shape, to be tested on a
person rather than accepted from here:

> *A laptop was visible. This is the frame the Tower kept the record
> against — a picture from the recording, not a place. It does not say
> anything about now.*

---

## 8. Known limitations

1. **One home, one activity.** 34 captures, overwhelmingly a person using
   a laptop in a bedroom. `laptop` at 24/24 is a strong statement about
   this laptop in this room. No kitchen, no car, no office, no bystander,
   and no set of keys was ever recorded. Every precision figure is a
   lower bound on how wrong a class can be.
2. **The size floor is not fixed; it moved.** Every verifier false reject
   is a crop of ≤5.3% of the frame — including three real remotes at
   3.7–3.9%. On 360×640 source imagery that is a property of the pixels.
   The upstream fixes are a higher capture resolution or tiled detection
   on the async path, and neither is this wave's.
3. **The verifier threshold is fitted to 94 crops.** 0.45 is the peak of
   a plateau on a small set from one home.
4. **The face filter fires on 40% of real frames and is mostly wrong when
   it does.** Handled here by reporting `subject_obscured`; it matters
   more to World Builder (§9).
5. **`keyboard` largely duplicates `laptop`** even with the part-of rule,
   because the rule only fires while both are concurrently in view.
6. **`update_sighting` rewrites the whole JSONL file.** Bounded by the
   rate limiter to a handful of writes per sighting (62 over a 2,203-frame
   replay), and the store's own docstring already names SQLite as the
   move when the file stops being small.
7. **`transformers` is a new dependency**, installed only into this
   worktree's venv for the run (`--target`, so the primary tree's venv is
   untouched). It is **not yet in `pyproject.toml`** — see §11.
8. **The session is in-process state with no lock.** FastAPI runs sync
   handlers in a threadpool, so two concurrent `POST`s are possible. The
   actions are idempotent and the worst case is a redundant attach the
   supervisor refuses, but it is not formally serialised.

---

## 9. Requirements this lane has for other lanes

### 9.1 World Builder — the face filter's false-positive rate

`tower/tower/world_builder/redaction.py` fills detected face regions
**before persistence**. Its own measurement — "0 false positives on 40
face-free frames" — was made on forty **synthetic room renders**.

Measured on the real corpus, at the same settings: it fires on **40.2%**
of frames, 976 regions across 1,845 frames, median region **12.5% of the
frame**, largest 84%. Of 36 firings inspected by eye, **4 were a real
face** (the wearer in a mirror) and **32 were not** — hands on a keyboard
in the large majority, plus screens, a white door and a sink.

That module's analysis priced the honest cost as "the 5% row — no
keyframes lost, about 9% of the point cloud", which assumed a firing rate
far below this one. **Please re-price it against real footage.** The
harness is `scripts/research/face_filter_false_positives.py`.

Not acted on here: that tree is frozen to your lane, and a cartridge may
not import another cartridge.

### 9.2 World Builder — `spatial_ref`, when you are ready

`docs/contracts/OBJECT-MEMORY.md` §12 specifies the shape Object Memory
will consume, including `anchor_keyframe_id` and `frame_revision`.
Object Memory will not build it and will keep working without it.

---

## 10. Rollback

Every piece is independently revertible.

| to undo | do this |
|---|---|
| the verifier | it is already off. `TOWER_OBSERVATION_VERIFIER` unset ⇒ `recorded_classes` is `["laptop", "cell phone"]`, no weights load, no VRAM. |
| the imagery routes | `TOWER_FACE_REDACTION_MODEL=/nonexistent` ⇒ every picture route answers 503 and nothing else changes. Or unset `TOWER_CAPTURE_ROOT`. |
| automatic attachment | `TOWER_OBSERVATION_ENABLED=false` ⇒ no producer is attachable, both `GET`s answer 404, exactly the pre-change dark state. |
| the whole cartridge | as above. The Tower, World Builder and the frame path are untouched by it. |
| the code | `git revert 5b329ad f489da5 d5000b7`, in that order. The three commits are layered and each leaves a green suite. |

Records written by the new policy are **readable by the old code**: every
added field is optional with a `.get()` default, and the old
`update_best_score` still exists and still works.

---

## 11. What is still owed

**Physical validation.** Everything below needs the glasses, the phone
and a person. None of it is reachable from a test.

1. **Press Start on a phone and walk.** The whole claim. Expect
   `following` to fill within a second of the recording starting, and a
   memory to appear within a few seconds of an object coming into view.
2. **Press Pause mid-walk.** The producer should exit; `/health` should
   show it gone from `capture_workers.workers` while the builder stays.
3. **Press Resume after a reconnect.** It must attach to the capture
   recording *now*, and it must not re-read the part of the walk that
   happened while paused.
4. **Look at a picture.** The 410 path in particular: purge a capture
   with `scripts/object_query.py`'s neighbour and confirm the app says
   the memory is kept and the picture is not.
5. **Show a found-record screen with its picture to someone who has not
   read any of this**, and ask what it told them. If the word "where"
   comes back, the caption is wrong. That is the only real test of this
   work, and it is the one that would justify changing the layout.
6. **Run with `TOWER_OBSERVATION_VERIFIER=owlv2` on a real walk** and
   check the verifier counters in the producer's report: `dropped_backlog`
   must stay 0 and `peak_pending` must stay low. If either moves, the
   finding is that the model is too slow for this host, not that the
   queue is too small.
7. **A room this corpus does not contain.** A kitchen, a desk with keys
   on it, a bag by a door. Every precision figure here is from one
   bedroom.

**Repository work.**

8. **`transformers` is not in `pyproject.toml`.** It was installed into
   this worktree's venv with `--target` so the primary tree's venv stayed
   untouched. Before this branch merges, add it to a new optional extra
   (`semantic`, alongside `ml` and `ocr`), pin it, and record that the
   resolve adds only `tokenizers`, `regex`, `typer`, `rich`,
   `markdown-it-py`, `mdurl` and `shellingham` — nothing already
   installed is upgraded.

---

## 12. Adversarial review

Two independent reviewers were commissioned specifically to find
"looks successful but does nothing", stale state, duplicate memories,
privacy regressions, lifecycle races, unbounded compute, producer/API
disagreement, tests that only validate mocks, and unsupported numeric
claims.

<!-- REVIEW FINDINGS -->

---

## 13. Where everything is

| | |
|---|---|
| Policy and evidence | `tower/tower/object_memory/classes.py` |
| Sightings | `tower/tower/object_memory/sightings.py` |
| Gates | `tower/tower/object_memory/relevance.py` |
| Producer | `tower/tower/object_memory/engine.py`, `tower/scripts/object_memory_session.py` |
| Verifier | `tower/tower/object_memory/verification.py` |
| Imagery | `tower/tower/object_memory/imagery.py` |
| Session machine | `tower/tower/cartridge_session.py` |
| Supervisor | `tower/tower/capture_workers.py` |
| Routes | `tower/tower/routes/observations.py`, `tower/tower/routes/sessions.py` |
| Adapter | `tower/tower/results/object_memory.py` |
| Contract | `docs/contracts/OBJECT-MEMORY.md` |
| Corpus measurement | `tower/docs/superpowers/research/2026-08-27-object-memory-corpus-precision.md` |
| Model landscape | `tower/docs/superpowers/research/2026-08-27-object-memory-vision-model-landscape.md` |
| Harnesses | `tower/scripts/research/` |
