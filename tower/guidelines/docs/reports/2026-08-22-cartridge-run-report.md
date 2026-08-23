# Cartridge Development Run — 2026-08-22

**Branch:** `cartridge/experimental-cv-lab-v1`, off `world-builder/v1`,
off `master @ b591e30`. Not merged.

**Suite:** 849 passed, 30 skipped by default.
**861 passed, 0 skipped** with `TOWER_RUN_MODEL_TESTS=1`.
Started from 376 passed, 3 skipped.

A sequential run: close out World Builder, reconcile every cartridge plan
against reality, then build three cartridges one at a time, each earning
completion independently.

---

## 1. What shipped

| Phase | Outcome |
|---|---|
| **0 — World Builder closeout** | Every `plan.md` requirement audited; live incremental viewing closed; capture made armable; the one open correctness question resolved |
| **1 — Plan reconciliation** | Every module doc given an honest per-part status; two missing roadmap milestones recorded; one false architectural guarantee corrected |
| **Cartridge 1 — Experimental CV Lab V1** | A measurement channel, one Module class instead of two, five new experiments |
| **Cartridge 2 — Document Memory V1** | Observe a document being read, remember its text, refuse to guess |
| **Cartridge 3 — Scene Understanding V1** | What is around the wearer now, counted by tracking, with refusals |
| **Translator** | **Plan only**, per the brief. Not implemented |

---

## 2. Phase 0 — World Builder closeout

The full requirement matrix is in
`2026-08-22-world-builder-closeout.md`. Three things were fixed.

**Capture could not be armed in a running Tower.**
`app.state.frame_observers` was populated only by tests. Every physical
validation procedure the project has written down begins "arm capture on
the Tower", and that step was not executable — invisible precisely
because the suite armed it by hand. `TOWER_CAPTURE_ROOT` now does, off by
default, and `/health` reports the state because `06-PRIVACY-DATA.md`
requires recording state to be visible and it existed only in a log.

**Live incremental viewing.** The storage design was never the gap: the
journal has always been an update stream. What was missing was a cursor
and a live producer. Both were added — and the tempting shortcut was
**rejected**. Registering a World Builder observer on `frame_observers`
would have been thirty lines; the capture recorder sits there because
*recording is not processing*, and running the mapper there is
processing whether or not the type system notices. Three processes
instead, which also means the frame path pays nothing for a rebuild.

**The 16-keyframe drift figure was the camera walking into a wall.**
1.06% / 1.97% / 21.61% at 8/12/16 keyframes was attributed to unbounded
drift. The sweep used `strafe(N, step=0.20)` from x=0 in a 6 m room, so
keyframe 16 sits at **x = 3.00 m — exactly the right wall**. Kept inside,
16 keyframes drifts **1.05%** and there is no cliff. The obvious fix — an
inlier-ratio gate — was measured and **rejected**: the healthy walk
reports a *lower* ratio (0.25) than the one heading into the wall (0.47),
so a floor would refuse the good case and admit the bad one.

---

## 3. Cartridge 1 — Experimental CV Lab V1

The Lab could not do its job: every experiment had to reduce itself to
one scalar, and a stateful experiment cost a whole `Module` subclass.

**`ExperimentResult.metrics`**, a `name -> number` bag, additive on the
wire and omitted when empty. `CARTRIDGE-GROUNDWORK.md` listed "a
non-scalar result channel" as missing infrastructure four cartridges were
waiting on — and it is the Lab's own type.

**One Module, many experiments.** `tower/modules/depth_cv.py` was
**deleted**: the refactor removes a class rather than adding one.

**Five experiments**, each answering a question something else has, with
costs measured before they were chosen. Sparse optical flow was picked
over dense on a measured **7.5–8.9×** cost difference, and the losing
option stays in the benchmark rather than becoming a comment.

`object_detection` exists because Cartridge 3 needed the measurement, and
produced the most reusable finding of the three: **detection cost is
essentially independent of input resolution** (33–37 ms from 640×360 to
1280×720), because the model resizes to 320 internally.

---

## 4. Cartridge 2 — Document Memory V1

**One correction to the brief's language, and it is not pedantry.** The
brief asked for *"sustained document attention"*. Limitation 8 is
explicit that the camera cannot establish attention. So the cartridge
detects a page-like region **present and steady**, the record is
`DocumentObservation`, and the CLI prints **OBSERVED, NOT READ**.

**OCR costs ~1.2 s per page; detection ~2.6 ms.** That 400× ratio is the
whole architecture: make the expensive stage rare, not fast.

**The headline finding is a blocker, and it is not a Tower problem.**
Word recall against known rendered text:

| Frame size | Word recall |
|---|---|
| 1280×720 | 0.957 – 1.000 |
| 640×480 | 0.905 – 1.000 |
| **640×360 — what the glasses deliver** | **0.429 – 0.810** |

Tilt barely matters; resolution dominates. Page *detection* still works
at 640×360 — only *recognition* is starved, which narrows the requirement
usefully.

---

## 5. Cartridge 3 — Scene Understanding V1

**A live state, not a memory**, and that distinction settled the design:
nothing is persisted (enforced by test), and there is no query CLI
because there would be nothing to query.

**Counting uses tracking**, measured rather than asserted: the correct
count of 2 holds exactly through 0%, 10% and 20% detector dropout.

**Orientation is off by default**, at a measured **798 ms** — 24× the
detector and 2.5× the delivered frame interval. It is never called gaze,
and an AST test bans `looking_at`, `gaze_direction`, `is_looking`,
`face_id` and `person_id` across every cartridge.

**Two relationships asserted, six refused**, each refusal recorded with
the evidence that would settle it.

---

## 6. What was rejected, and why

The rejections carry more information than the features.

| Rejected | Why |
|---|---|
| A World Builder observer on the live frame path | Would have spent the architecture decision `plan.md` §28 protects |
| An inlier-ratio gate on PnP | Measured backwards: the good walk scores lower than the bad one |
| `rapidocr_onnxruntime` | A dry-run showed it installs `opencv-python` beside `opencv-python-headless` |
| `pytesseract` | Needs a system binary pip cannot install |
| Dense optical flow | 7.5–8.9× the cost for the same headline |
| Face detection | Verified absent: no `CascadeClassifier`, no model for `FaceDetectorYN`, no ONNX/XML anywhere under `cv2/` |
| Embedding retrieval | No corpus to justify it; BM25's explainability matters more while an answer must be traceable |
| An LLM summary | No local serving path, and abstractive summary of partial capture is the fabrication the brief forbids |
| `nearer_than_same_class` | **Shipped, then withdrawn** on a counterexample: two chairs at the same distance, one face-on and one edge-on, differ 2.5× in area |
| `in_front_of`, `on`, `inside`, `near` | Need depth or support-surface reasoning that 2-D boxes cannot provide |
| A store for Scene Understanding | Would pre-empt Environmental Memory's whole reason to exist |
| `scipy.optimize.linear_sum_assignment` | Would be one line, but scipy arrived as an OCR dependency and this cartridge must not acquire it by accident |
| A scene graph type, a query CLI, semantic retrieval, voice input | Structure or surface with no consumer today |

---

## 7. New dependencies

One, as an optional `ocr` extra: **`easyocr`**, pulling `scipy`,
`scikit-image`, `imageio`, `tifffile`, `lazy-loader`, `ninja`,
`pyclipper`, `python-bidi`, `shapely`. `pip check` clean before and
after; suite unchanged either side. No new dependency for detection or
keypoints — torchvision was already present.

---

## 8. Privacy posture, by cartridge

| Cartridge | Persists | Imagery | Identity |
|---|---|---|---|
| Experimental CV Lab | Nothing | None | None |
| Document Memory | Derived text; page images opt-in and **off** | Never raw frames | None |
| Scene Understanding | **Nothing** | None | None — anonymous session-scoped track ids, IoU association only |

Two privacy defects were found and fixed: retention expiry left page
pixels on disk, and a track id reused across an occlusion carried one
person's orientation to another.

---

## 9. Known blockers

1. **No physical footage.** Every measurement is synthetic.
2. **Delivered resolution cannot read a document.** iOS/DAT work.
3. **Live orientation needs a GPU.** torch is CPU-only here.
4. **No structured result channel**, so no cartridge's real output can
   reach iOS. V1.0/V1.1, still blocked.
5. **No microphone on this host** — blocks the Translator prototype's
   own first stage.
6. **The V1.1 lifecycle ruling** is still unrecorded, and still blocks
   Object Memory Tasks 4–8.

---

## 10. The next physical test, in order

1. Print the ChArUco board; **measure the printed square**.
2. `TOWER_CAPTURE_ROOT=data/capture` and start the Tower. Confirm
   `GET /health` shows `capture.armed: true, recording: false`.
3. Connect the glasses, `stream_start`, walk the board through frame at
   varied distances and angles, `stream_stop`. Confirm
   `capture.frames_written` moved.
4. `calibrate_charuco.py --frames <capture>/frames --out intrinsics.json`.
   Check reprojection RMS **and** view count. Repeat at a second DAT
   resolution to settle whether intrinsics scale linearly.
5. Record a room walk with capture armed.
6. **In parallel, from the same capture:**
   - `world_build_session.py --follow-capture <dir> --intrinsics
     intrinsics.json --rebuild-every 8`
   - `world_inspect.py --world <id> --follow`
   That is the *watch it build* experience, end to end, on real footage.
7. `world_inspect.py --world <id> --verify --trajectory`.
8. Re-run the V0.9.3 experiments on the same footage to discharge the
   standing acceptance gate.
9. **Read a document on camera at the highest resolution DAT will give**,
   then `document_memory_session.py --follow-capture <dir>` and
   `document_query.py --text "<something on the page>"`. This is the
   measurement that confirms or refutes §4's resolution finding on real
   optics.
10. **With people in frame**, `scene_session.py --follow-capture <dir>` —
    the first and only test of detection accuracy on real people, which
    nothing on this host could validate.
