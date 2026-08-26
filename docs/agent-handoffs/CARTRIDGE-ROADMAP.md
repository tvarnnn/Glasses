# Cartridge roadmap — all nine

**Date:** 2026-08-26
**Branch:** `integration/world-builder-lifecycle-v1`
**Tower suite:** 1497 passed, 30 skipped, 0 failed

Program-level view: what each cartridge is, what is actually true of it
today, what gates it, and the order the dependencies imply. It is
deliberately not a schedule — nothing here can be dated, because the two
largest gates are a Mac and a wearer.

**The rule this document applies:** a capability counts as working only
where something ran and produced evidence. "Implemented and tested" is a
statement about code, not about the world. Every row separates them.

Companions: `2026-08-25-cartridge-evidence-map.md` (what exists, in
detail), `WORLD-BUILDER-STATUS.md` (P1–P11 physical gates),
`OVERNIGHT-RUN-HANDOFF.md` (this run's log).

---

## 1. Status

| # | Cartridge | Code | Evidence on real frames | Gated by |
|---|---|---|---|---|
| 1 | **World Builder** | Tower complete, tested | **Yes** — 5 real captures; 51 segments, 3 registered | Mac compile, then a walk |
| 2 | **Experimental CV Lab** | Implemented, 86 tests | Partly — `baseline` only, 2026-08-21 | Nothing; it is a lab |
| 3 | **Scene Understanding** | Implemented, persists nothing | **Yes** — constants re-derived at the true 12 fps | The lifecycle ruling |
| 4 | **Object Memory** | Store + producer + route + **iOS surface (UNCOMPILED)** | **Yes** — 55 observations from 9,199 frames | iOS compile; the `person` ruling |
| 5 | **Document Memory** | Engine + CLI, 145 tests | **Yes, and it falsified the premise** | Camera resolution |
| 6 | **Environmental Memory** | Design only | None | Its own design says *do not begin* |
| 7 | **Translator** | Two plans, both stamped DO NOT IMPLEMENT | None | No audio path exists |
| 8 | **Visual Q&A** | Doc only | None | Voice half: audio. Visual half: nothing |
| 9 | **Accessibility** | Doc only | None | Audio, plus its own hard block |

There is no `tower/tower/cartridges/` directory. Cartridges are sibling
packages under `tower/tower/`. "Cartridge" is a docs word; the code says
"module" only for the lifecycle contract.

---

## 2. The blockers that actually gate the program

Ranked by how much they hold back, not by how hard they are.

### 2.1 No Mac — RESOLVABLE, and it gates the most

**Over 4,383 lines of Swift across 18+ files have never been compiled by
anything**, and Object Memory's new workspace adds five more files to
that pile. No Swift toolchain exists on this host and none can. This
gates every user-visible claim in the program: World Builder's viewer,
Object Memory's new surface, and any future cartridge UI.

A static review (`IOS-STATIC-REVIEW.md`) found and fixed one certain
compile error and verified the wire contract field-by-field against the
Tower producer. Its judgement was "close to compiling". **That raises the
odds of a clean first build; it is not a build.**

### 2.2 The module lifecycle ruling — PENDING, and its blast radius grew

`ModuleContainer` bounds lifecycle calls with `asyncio.wait_for`, which
**cannot interrupt synchronous work** inside `_do_load()`. So the 10 s
timeout is fiction for any module that loads a model. Five options are
costed in `plans/2026-08-20-object-memory-first-slice.md:826-896`;
the recommendation there is **E+A now, B at V1.1**.

**What changed this run:** Object Memory sidestepped this by producing
out of process — tailing a capture journal, writing a derived artifact,
serving it over HTTP. That worked, and it is why Object Memory now has a
route.

**It does not transfer to Scene Understanding.** That cartridge has no
store *by design* — `test_scene_understanding_persists_nothing` enforces
it against 17 write primitives and calls it "its strongest privacy
property". The journal-follower pattern requires writing a derived
artifact, so a cartridge forbidden from writing anything cannot use it.
Scene Understanding must deliver live, which needs the in-process module
route, which is exactly what this ruling gates.

So the ruling is no longer one cartridge's implementation detail. **It is
the sole blocker on Scene Understanding reaching a user at all**, and it
is the single highest-value decision available.

### 2.3 Camera resolution — newly identified, and it is physics

DAT delivers **360×640**, offering 720×1280 / 504×896 / 360×640, all
9:16. **No landscape mode at any resolution.**

- **Document Memory is bound by this.** At 360×640 a laptop screen
  occupies ~200×140 px and its glyphs are **roughly two pixels tall**.
  Measured: EasyOCR finds **zero** text regions in full frames a human
  confirms show a screen full of text.
- **Raising it is not free.** 720p was tested and is *actively harmful*
  for tracking: `min_sharpness = 25.0` is absolute, and at 720p **73.3%**
  of frames fall below it and are rejected as blurred.

This is the one blocker that is neither a decision nor a compiler. It is
a property of the hardware and the pipeline, and it deserves its own
investigation before any more work is spent on text.

### 2.4 No audio path anywhere — hard, structural

`frames.py` accepts JPEG only; `Module.process()` takes one still image.
There is no capture, transport, or contract for audio anywhere in the
system. This hard-blocks Translator outright and the voice halves of
Visual Q&A and Accessibility. Building it is a subsystem, not a feature.

### 2.5 The `person` ruling — open, and reframed

Whether a cartridge may persist a record per detected bystander. Object
Memory sidesteps it with a store-enforced whitelist. **The corpus
reframes it:** the `person` detections here are the **wearer's own
torso** (median box bottom edge 0.981, 59% touching the frame edge), so
this host has never seen a bystander. That makes the question less
urgent, and also means no measurement here can inform it.

---

## 3. What the dependencies imply

```
        Mac compiler ──────────► World Builder viewer ──► P3..P11 walks
             │
             └─────────────────► Object Memory surface

    Lifecycle ruling ─────────► Scene Understanding wire ──► its first user

  Camera resolution ──────────► Document Memory ──► Visual Q&A (visual half)

        Audio subsystem ──────► Translator, and the voice halves
```

**Nothing on the left is engineering this host can do.** One is a
machine, one is a decision, one is hardware, one is a subsystem nobody
has scoped. That is the honest shape of the program right now: the Tower
side has run ahead of every gate that would let it reach a person.

---

## 4. Order

**Unblocked, no permission needed:**

1. **Depth on real frames.** Scene Understanding refused `in_front_of` /
   `behind` on a **synthetic** 6–8% MiDaS flicker measurement. Needs
   `timm`. Cheap, and it either restores two spatial relations or retires
   them on evidence.

   **Measure it on both devices.** Orientation is the cautionary case: the
   feared 798 ms was CPU-with-synthetic-input and is withdrawn, but the
   replacement is **43.4 ms on CUDA and 956.4 ms on CPU — and CPU is the
   default device.** So the synthetic figure was wrong in both directions
   at once: far too pessimistic for the GPU path, and too *optimistic* for
   the one that actually runs by default, where it is 29.1× the detector
   against an 83.5 ms frame interval. A depth measurement taken only on
   CUDA would repeat that mistake.
2. **Experimental CV Lab beyond `baseline`.** The only cartridge with no
   external gate at all.

**Waiting on the user, cheap to answer:**

3. **The lifecycle ruling** (§2.2). Recommendation already written and
   costed. This one unblocks a whole cartridge.

**Waiting on a Mac:**

4. World Builder P1/P2, then the Object Memory surface.

**Waiting on a wearer, in value order:**

5. **P11** — a walk where the wearer *sidesteps* rather than pans. 16 of
   19 segments are refused because scale is unobservable when standing
   still. This **tests a prediction** rather than gathering data, which
   makes it the highest-leverage physical experiment available.
6. **P3** — do fragments appear *during* a walk. The entire product claim.
7. **P9/P10** — a loop closure, so registration composition finally has
   an independent check. Nothing automated can catch a wrong Sim3: pair
   (30,50) fits at 1.62 px while being **3.2× wrong on scale**.
8. **P7** — footage containing an actual second person, which would make
   redaction and the `person` question measurable for the first time.

**Do not start:** Environmental Memory (its own design says so; six of
its seven prerequisites are not engineering), Translator, and the voice
halves of Visual Q&A and Accessibility.

---

## 5. What this run changed, in one line each

- **World Builder** — geometry reaches the wire; tracking measurably
  better (poses 211→265, points 27,406→42,100); registration produces its
  first merged geometry and refuses more than it admits.
- **Scene Understanding** — constants re-derived at the true 12 fps.
  Counting at 60% detector dropout **0.252 → 0.783**.
- **Object Memory** — went from a data layer with no producer to a
  cartridge with 55 real observations, an enforced retention promise, and
  its first route.
- **Document Memory** — premise falsified, gate re-derived, false
  positives **6 → 0**. It stopped being wrong, which is not the same as
  starting to be useful.
- **The environment** — the ML stack went from absent (everything
  model-backed inert) to CUDA-verified on Blackwell sm_120.
- **Object Memory got a UI**, uncompiled, whose copy is enforced rather
  than reviewed: the view holds **no user-facing string literal**, all
  copy lives in `ObjectMemoryCopy`, and the tests sweep that same source
  for phrases the cartridge may not say — "your laptop", "still there",
  "last seen in session" — including on buttons, because "Find my laptop"
  on a button would walk straight past a test that only read record rows.
