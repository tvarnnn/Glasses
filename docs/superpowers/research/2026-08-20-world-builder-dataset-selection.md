# Dataset Selection for World Builder Experiments 1–2 — Decision Record

Status: **autonomous engineering ruling made during the 2026-08-20 weekend
run**, recorded per the Master Guide §22 ("record: issue, evidence, ruling,
alternatives considered, and cost if wrong").

## Issue

Master Guide §17 MUST item 2 requires confirming whether real-motion footage
is obtainable before Experiments 1 (`depth_temporal_consistency`) and 2
(`feature_trackability`) can run. §10 states these experiments cannot be
exercised by synthetic single-frame JPEGs.

## Evidence gathered

Checked, in this environment, on 2026-08-20:

- **No webcam hardware.** `cv2.VideoCapture(0..2, CAP_DSHOW)` — all three
  indices fail to open ("backend is generally available but can't be used to
  capture by index"). No physical camera attached to this Windows machine.
- **No video assets in the repo.** No `.mp4`/`.mov`/`.avi` anywhere outside
  `.venv`; no fixtures/assets directory.
- **The only prior real-motion path was Mac-side.** `V0.7`'s
  `mock-device-kit` capture was driven through the iOS app
  (`guidelines/docs/reports/V0.7-sustained-streaming-report.md` line 12–13),
  which this Windows session cannot reach (Master Guide §4).
- **GTEA Gaze+ (literal glasses-mounted camera — the ideal match) is
  dead.** Its host `webshare.ipat.gatech.edu` returns NXDOMAIN; the Stanford
  index page still links to it, but every video URL is unresolvable.

So **physical-glasses and locally-captured footage are both genuinely
unavailable**, exactly as the Master Guide anticipated.

## Ruling

Use a **bounded window of one public, real-captured, head-mounted egocentric
sequence** as *feasibility* input for Experiments 1 and 2, while treating
real DAT/Ray-Ban footage as a required later validation gate (see Acceptance
Gate below).

### Dataset chosen

| Property | Value |
|---|---|
| Dataset | EPIC-KITCHENS-100 |
| Sequence | `P01_107` |
| Source URL | `https://data.bris.ac.uk/datasets/2g1n6qdydwa9u22shpxqzp0t8m/P01/videos/P01_107.MP4` |
| Size | 362,078,738 bytes (smallest verified-available P01 extension sequence) |
| Resolution / rate | 1920×1080 @ 50 fps, 119.4 s, 5972 frames |
| Capture device | **Head-mounted GoPro** (real optics, real sensor) |
| License | CC BY-NC 4.0 — non-commercial research use |
| Verified motion | mean inter-frame abs gray diff **9.28** (min 1.88, max 17.81) over first 200 frames — genuine continuous motion, not a static shot |

### Why this sequence is representative enough for the specific questions

- **Head-mounted, not handheld or robot-mounted.** This is the single
  property that matters most. The research doc's load-bearing worry
  (`2026-08-20-world-builder-foundations.md` §1.4) is precisely that
  standard VO/SLAM benchmarks (EuRoC, TUM-RGBD, TartanAir) use *deliberate,
  steady, or robot-mounted* motion unlike casual wearable use. EPIC-KITCHENS
  is the opposite: undirected, unscripted, natural head motion during real
  activity — the regime the experiments actually need to probe.
- **Real optics and real compression artifacts**, not synthetic rendering.
- **Neither experiment requires camera intrinsics.** Experiment 1 measures
  frame-to-frame stability of MiDaS output (no geometry at all). Experiment
  2 uses ORB matching with RANSAC verification via
  fundamental-matrix/homography, which is intrinsics-free — only
  `recoverPose` (Experiment 3) needs a calibrated camera, and Experiment 3
  remains out of scope and blocked.

### Alternatives considered and rejected

- **TUM RGB-D `freiburg1`** — has ground-truth trajectory *and* depth, which
  is attractive, but it is **handheld Kinect** motion in a lab, i.e. exactly
  the "more deliberate/steady than wearable" regime the research doc warns
  does not transfer. Ground truth we cannot use (Exp 1/2 need neither) does
  not outweigh losing the head-mounted property.
- **GTEA Gaze+** — the best match on paper (SMI eye-tracking *glasses*), but
  the host is dead (NXDOMAIN). Unusable.
- **Synthetic/AI-generated motion** — explicitly excluded; would not answer
  either question honestly.
- **Downloading the full EPIC-KITCHENS corpus** — rejected as
  disproportionate; one 2-minute sequence, of which only a bounded window is
  used, is sufficient.

### Handling

The video is **not vendored into the repository** (362 MB; git-inappropriate).
It lives outside the repo and is reproducible from the documented URL above.
Only a bounded window is actually analysed.

## Limitations that must be carried into every resulting report

Every measurement derived from this dataset is **dataset-based feasibility
evidence, NOT physical-glasses/DAT validation.** Concretely, EPIC-KITCHENS
differs from the target platform in:

1. **Optics/FOV** — GoPro wide-angle vs. Ray-Ban Meta's narrower field.
2. **Encoding** — a fixed high-bitrate recording vs. DAT's *adaptive bitrate
   ladder* (`07-PLATFORM-CONSTRAINTS.md` Limitation 2), which is documented
   to produce exactly the low-texture/blur conditions that most threaten
   both experiments.
3. **Resolution/frame rate** — 1920×1080@50 vs. the platform's 504×896@15
   target (mitigated by resampling in the harness, not eliminated).
4. **Scene regime** — close-range indoor kitchen work with heavy hand
   presence; not a general sample of wearable use.
5. **No Ray-Ban-specific sensor characteristics** of any kind.

## Acceptance Gate (required future work)

**Both Experiment 1 and Experiment 2 MUST be re-run on real DAT/Ray-Ban
glasses footage before any of their conclusions may be used to justify
building World Builder, selecting a smoothing strategy for production, or
closing out the feasibility question.** A dataset-based result may
*deprioritize* a direction (a clear negative is informative), but may never
be cited as positive validation for the platform's own camera. This gate is
tracked in the resulting report(s) and is not discharged by this document.

## Cost if wrong

**Low and bounded.** If EPIC-KITCHENS turns out to be unrepresentative of
Ray-Ban footage, the cost is the analysis time already spent plus a re-run
of two cheap, self-contained scripts against the real clip when it exists —
no production code depends on these results, no dependency is adopted, and
no architectural commitment is made. The specific risk is *over-confidence*:
a "MiDaS flicker is manageable" result on GoPro footage could be wrong for
DAT's more aggressive compression. The Acceptance Gate above exists to
prevent exactly that, which is why it is stated as a hard requirement rather
than a caveat.
