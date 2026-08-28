# Translator — benchmark plan: how to settle the architecture with measurements

Date: 2026-08-25
Status: **PLAN ONLY. DO NOT IMPLEMENT. NO DEPENDENCY INSTALLED BY THIS DOCUMENT.**

Companions, both of which this document depends on and neither of which it
replaces:

- `docs/superpowers/plans/2026-08-22-translator-research-plan.md` — the
  research plan. Read it first; §0 below states exactly what it settled.
- `guidelines/docs/modules/TRANSLATOR.md` — the module concept.

This document's job is narrow: produce a **benchmark that decides between
four architectures**, and make the first phase of it runnable on this
machine without buying anything. It deliberately does not recommend an
architecture. A recommendation written before the measurements exist would
be the thing `02-DEVELOPMENT-RULES.md` Rule 17 and the OCR/optical-flow
precedents exist to prevent.

## Legend

| Marker | Meaning |
|---|---|
| `[VERIFIED]` | Measured or enumerated on this host during this session (2026-08-25) |
| `[REPO]` | Cited from a file in this repository, with the path |
| `[AGENT]` | From outside knowledge or a web search made during this session. Not a repository finding. Dated where the source is dated |
| `[INFERENCE]` | My reasoning from the two above. Not a fact |
| `EXISTS` | Code or capability present in this repository today |
| `PROPOSED` | Does not exist. Would have to be built |

---

## 0. What the 2026-08-22 research plan already settled, and what this adds

**Do not re-derive these.** The 2026-08-22 plan settled them and they stand:

1. **The sequencing ruling.** Prototype Tower-local, entirely outside the
   glasses path, before any Ray-Ban / iPhone / Bluetooth integration
   (`2026-08-22-translator-research-plan.md` §1).
2. **There is no audio path anywhere in this system** (§1, §2).
3. **The four candidates**, and the instruction not to pre-select (§4).
4. **Latency is three distinct numbers, reported p50 and p95, never a
   mean** (§5.1).
5. **End-to-end latency is measured by loopback and cross-correlation, not
   by summing per-stage timings** (§5.2). Summation produces a flattering
   wrong number.
6. **Candidate 4 can cheat by construction; score what the wearer HEARD**
   (§5.3).
7. **The failure modes are part of the result**, including what the
   pipeline does when it understood nothing — Rule 16 applies to audio
   (§5.4).
8. **Local-first is not optional; persist nothing by default; no speaker
   identification** (§8).
9. **The sequencing gate** before glasses integration (§9).

**What this document adds, and only this:**

| # | Addition | Why the 2026-08-22 plan did not have it |
|---|---|---|
| A | The DAT audio answer is **already in this repository** and is stronger than "unestablished". §1 below. | §7 of that plan listed "does DAT expose microphone audio at all" as a must-not-assume. `07-PLATFORM-CONSTRAINTS.md` Limitation 13 answers it, and the answer changes the benchmark |
| B | A **Phase 1 that needs no microphone**, no glasses and no new hardware | That plan's own first stage is blocked on a microphone this host does not have. It says so itself (§2). A plan whose first step cannot run is not yet actionable |
| C | **Named** accuracy and latency metrics, **named** corpora, and the licence of each | §5 correctly demanded "a stated metric" and "a fixed evaluation set" but deliberately did not choose them |
| D | The **glasses / phone / Tower division**, per candidate, with its latency and battery cost | Out of scope there — that plan is Tower-local by construction |
| E | A **harness design**, and the four specific reasons Translator does not fit the `Experiment` protocol | Not attempted there |
| F | **Sizing with licences**, and the dependency-collision analysis against this repo's recorded posture | §6 said "check the cv2 conflict" and named no sizes |
| G | **Updated host reality**, including two findings that change the plan | §2 was measured 2026-08-22. Two things moved |

---

## 1. The audio-path finding, first and plainly

### 1.1 No audio reaches the Tower. This is not close.

`[REPO]` `[VERIFIED]` The wire carries exactly one content message and it
is a JPEG:

- `tower/frames.py:8` — `REQUIRED_FIELDS = ("seq", "width", "height",
  "format", "data")`, and `SUPPORTED_FORMAT = "jpeg"` on the next line.
  A frame whose `format` is anything else is rejected as a protocol error.
- `tower/routes/ws.py` handles `ping`, `stream_start`, `frame`,
  `stream_stop`. There is no other content message type.
- `tower/modules/container.py:76` — `def process(self, raw_bytes: bytes)`.
  A module receives bytes and nothing else: no timestamp, no sample rate,
  no channel count, no sequence context.
- `IOS-to-Tower.md` §0 tabulates the entire vocabulary iOS implements and
  it is the same six messages. That table is the contract, and it has no
  audio row.

So the finding is not "audio is immature here". It is that **the only
sensor observation this platform has a word for is a still image.**

### 1.2 DAT does not expose audio — and that is *not* the headline

`[REPO]` `guidelines/docs/07-PLATFORM-CONSTRAINTS.md` Limitation 13
("Audio Is a Separate Sensor Path"), verified against DAT 0.9.0 by an
earlier documentation pass, and corroborated by
`docs/superpowers/research/2026-08-21-world-builder-readiness.md` §5.2,
which enumerated the complete `MWDATCamera` surface from the fetched DAT
0.9 iOS API reference and found no audio in it at all:

> Microphone capture uses the Bluetooth **HFP** (Hands-Free Profile) via
> standard iOS `AVFoundation` (`AVAudioSession`, `AVAudioEngine`) — **not**
> a DAT SDK call.

**The headline is better and worse than "DAT does not expose audio".**
Better, because the microphone is reachable — it is an ordinary iOS
Bluetooth audio route, not a missing SDK feature, so no Meta API has to
ship for this to be possible. Worse, because Limitation 13 records two
properties that reshape the entire benchmark and that no amount of Tower
work can fix:

**(a) HFP is documented here as 8 kHz mono, beamformed.** Every
Whisper-family and Parakeet/Canary-family model in the candidate set
expects 16 kHz `[AGENT]`. Narrowband telephony audio is half the band
these models were trained on, and it removes exactly the high-frequency
energy that distinguishes fricatives — the consonants that carry the most
lexical information per unit of duration. **A benchmark run only on 16 kHz
studio audio will produce numbers that do not transfer to the glasses.**
This is the single most consequential fact in this document, and it is why
§4.1 makes a narrowband arm mandatory rather than optional.

**(b) A2DP and HFP are mutually exclusive.** Activating HFP switches the
glasses away from A2DP for the session. So the wearer cannot be listening
to high-quality audio *out of the glasses* while the glasses microphone is
capturing. Whatever the translated speech comes out of, it is either the
same narrowband bidirectional HFP link, or the phone's own speaker, or a
separate device. This is a product decision disguised as a Bluetooth
profile constraint, and it is unresolved.

**(c) There is an ordering constraint.** Add the DAT camera stream to the
session first, then configure and start HFP and wait for the route to
settle, *then* start the DAT stream. Starting the DAT stream before HFP is
ready can cause the audio route to fail **silently** — which is the worst
failure mode a benchmark can have, because it produces a plausible number
from the wrong microphone.

`[REPO]` Rule 4 (`05-DAT-INTEGRATION.md`) requires querying current Meta
documentation via `search_dat_docs` before writing DAT code. This document
did not do that — no MCP access from this session — so Limitation 13 is
cited as a repository finding, not as freshly verified truth. **Re-verify
(a) in particular before building the tier-C corpus**, because modern HFP
implementations commonly negotiate mSBC at 16 kHz, and if Ray-Ban Gen 2
does, the narrowband penalty largely disappears. See Open Question 1.

### 1.3 What would have to exist before any of this is testable

| Layer | What must exist | Status |
|---|---|---|
| **Glasses** | Nothing new. The HFP microphone is existing hardware behaviour, not a firmware ask. This is the one layer that is already done | EXISTS (hardware) |
| **Phone** | An `AVAudioSession` HFP capture route; the microphone permission flow, distinct from the camera one; PCM buffering and chunking; the Limitation 13 ordering dance relative to the DAT camera stream; route-loss detection and recovery; and a decision about where translated audio is played | PROPOSED — none of it written |
| **Wire** | An audio message type. Today `frame` is the only content message and it is JPEG-only by validation, not by convention. `docs/superpowers/research/2026-08-20-platform-backend-audit.md` §13 names this exact case: protocol versioning "becomes valuable once module-specific message shapes diverge (e.g. a future Translator's streaming audio chunks vs. CV Lab's `frame_result`)" | PROPOSED |
| **Tower** | An asynchronous, continuous ingest path. `Module.process()` is synchronous and bytes-only; `ExperimentResult` is five scalars plus a `dict[str, float]`; `ModuleContainer` is a registry of one; and `CARTRIDGE-GROUNDWORK.md` §5.4 records that no worker, queue or asynchronous execution path exists at all | PROPOSED — see §6.2 |

### 1.4 The scope consequence, stated so it cannot be missed

**Everything measurable in the next N weeks is offline, file-driven and
hardware-free.** Phase 1 (§7) runs entirely on recorded audio files. It
needs no glasses, no phone, no microphone, no wire protocol and no module
registration. It can still rank four architectures, because ranking
architectures is a question about models, not about transports.

Everything else — barge-in, real acoustic conditions, Bluetooth latency,
battery, the A2DP/HFP decision — is contingent on §1.3 and belongs after
it. Any benchmark result presented before that must carry the same
disclaimer this repository already puts on synthetic imagery
(`scripts/cv_lab_benchmark.py` docstring: "SYNTHETIC, NOT PHYSICAL"). The
audio equivalent: **RECORDED, NOT WORN.**

---

## 2. Host reality as of 2026-08-25 — two things moved since 08-22

`[VERIFIED]` this session.

| Component | 2026-08-22 | 2026-08-25 |
|---|---|---|
| GPU | RTX 5070, 12227 MiB | RTX 5070, 12227 MiB, driver 596.21, CUDA 13.2, WDDM |
| **Free VRAM at measurement** | not recorded | **~7.0 GB — 5228 MiB was already resident** (desktop, TeamViewer, SnippingTool) |
| `torch` | 2.13.0 **+cpu** | **not installed at all** — `scripts/verify_cuda.py` fails with `ModuleNotFoundError: No module named 'torch'` |
| CPU | — | 20 logical / 20 physical cores |
| RAM | — | 34.0 GB total, **4.4 GB available at measurement** |
| Audio libraries | all missing | all still missing: `sounddevice`, `pyaudio`, `soundfile`, `librosa`, `torchaudio`, `webrtcvad`, `silero_vad`, `faster_whisper`, `whisper`, `transformers`, `ctranslate2`, `sentencepiece`, `piper`, `pyttsx3`, `TTS`, `av`, `onnxruntime`, `scipy`. Only `winsound` |
| `ffmpeg` | not on PATH | still not on PATH |

**Two new findings.**

**2.1 `[VERIFIED]` The audio-device picture is slightly different from
what 2026-08-22 recorded, and the conclusion is unchanged.** That plan
said no capture endpoint is listed. Enumerating today:

```
Win32_SoundDevice:   NVIDIA High Definition Audio            OK
                     NVIDIA Virtual Audio Device (WDM)       OK
                     Realtek High Definition Audio           OK
AudioEndpoint:       Headset Microphone (DualSense …)        Unknown
                     Headset Microphone (2- DualSense …)     Unknown
                     Speakers (DualSense …)                  Unknown
                     Speakers (2- DualSense …)               Unknown
                     Dell AW2720HF (NVIDIA HD Audio)         OK
```

Capture *endpoint entries* do exist — a DualSense controller's headset
microphone has been attached at some point. All four are `Unknown`, which
on `Get-PnpDevice` means not currently present. The only `OK` endpoint is
still a monitor. **Refined conclusion: no capture device is attached, but
one has been, and a DualSense controller is a capture device this host
already has drivers for.** That is a cheaper unblock than buying hardware
and worth trying before assuming a purchase.

**2.2 `[VERIFIED]` Ollama is installed, with three models already on
disk.** This was not recorded anywhere in the repository and it materially
changes candidate 3's cost:

```
ollama version 0.32.13
llama3.1:8b           4.9 GB
qwen2.5-coder:14b     9.0 GB
phi4-reasoning:plus    11 GB
```

`[INFERENCE]` This makes candidate 3 the *cheapest* of the four to test,
not the most expensive: no pip dependency, no weight download, and — the
part that matters for §9 — **Ollama runs out-of-process with its own
bundled runtime, so it cannot put a second CUDA runtime inside this
project's venv.** It costs VRAM, which competes with the ASR model and
with the 5.2 GB the desktop is already holding, but it costs nothing in
dependency risk. Naming this so nobody budgets a model download that has
already happened.

**2.3 Prerequisite, unchanged and now worse.** `torch` must be restored
from the CUDA index *before* the extras, per the install-order hazard
recorded at `README.md:62-95` — installing `.[dev,ml]` first resolves a
CPU-only wheel from PyPI, which then satisfies the unconstrained
requirement forever and makes `TOWER_CV_DEVICE=auto` silently fall back to
CPU. Every GPU number in this plan is blocked on that.

---

## 3. Scope

**In scope:** ranking four architectures by measurement, on recorded audio,
on this Tower.

**Out of scope, explicitly:** the wire protocol; a `Module` subclass; iOS
work of any kind; the A2DP/HFP product decision; visual context fusion
(`TRANSLATOR.md` already defers it, and it introduces a second sensor
stream onto an unmeasured latency budget); speaker identification
(forbidden, `2026-08-22-translator-research-plan.md` §8); and choosing an
architecture, which is what the benchmark is for.

---

## 4. The metrics, defined precisely enough to be measured

### 4.1 The corpus decision comes before the metric decision

A metric name without a corpus is not a specification. Three tiers, and
all three are required for a result to count.

**Tier A — the reproducible floor. `CoVoST 2`.** `[AGENT]` A large-scale
multilingual speech-to-text translation corpus, 21 languages into English
and English into 15, **released under CC0**
(`github.com/facebookresearch/covost`). CC0 matters: it can be used, kept
and redistributed without a licence question, which is not true of every
speech corpus.

*Why it resembles the real use case badly, stated up front:* it is read
speech. Common Voice prompts, one speaker, no overlap, no disfluency, no
repair, no background. Every characteristic that makes conversational
translation hard is absent. Tier A exists so two candidates can be
compared on identical input with published references — **it is a
comparability instrument, not a prediction of field performance.** Do not
report a CoVoST COMET score as if it forecasts what a wearer will
experience. The same warning applies to FLEURS and MuST-C (TED talks):
read/prepared speech, same gap.

**Tier B — the tier that actually resembles the use case. Recorded here.**
Two people, real turn-taking, deliberate overlap, disfluency, self-repair,
a name or two, background noise, one far speaker. This is the only tier
whose numbers mean anything about the product.

Its cost is honest and must be budgeted: **it has no reference
translations until a human writes them.** That is real work, it is the
main non-compute cost in this plan, and it is Open Question 5. Tier B also
needs a microphone, which §2.1 says this host does not currently have
attached — so tier B is Phase 1b, not Phase 1a.

**Tier C — the narrowband arm. Mandatory, not optional.** Every tier A and
tier B item resampled to **8 kHz mono** and band-limited to approximate the
HFP path of §1.2(a). Run every candidate on tier C as well as at native
rate. **Tier C is the only arm whose numbers transfer to the glasses.** If
a candidate wins on 16 kHz studio audio and collapses at 8 kHz, it has not
won anything. If Open Question 1 resolves to "Ray-Ban HFP actually
negotiates 16 kHz mSBC", tier C becomes a robustness check rather than the
headline — but it is built either way, because the cost of building it is
a resampling call and the cost of not having it is a wrong decision.

**One language pair, both directions, for Phase 1.** Enough to rank four
architectures. N pairs multiplies run cost and does not change a ranking.
Expanding the pair set is a Phase 2 question.

### 4.2 Latency — four clocks, each with a named start and a named stop

The 2026-08-22 plan named three latencies and was right about all three.
This splits its first one, because "time to first translated audio"
bundles two very different failures — a pipeline that is not streaming at
all, and a pipeline that streams text but cannot synthesise incrementally.

| ID | Name | Start | Stop | What a bad number means |
|---|---|---|---|---|
| **L1** | first-partial | last audio sample of the first content word | first partial hypothesis emitted by the pipeline | The pipeline is not streaming. It is batching and pretending |
| **L2** | first-audio (TTFA) | same start as L1 | **first translated audio sample leaves the output device** — not "is handed to the TTS buffer" | The TTS will not emit until a sentence is complete. §6 of the 2026-08-22 plan calls this out and it is the most common way a good pipeline feels bad |
| **L3** | sentence-final | VAD-declared endpoint of the utterance | last sample of the corresponding translated audio | Trailing latency. The conversation cannot resume yet |
| **L4** | end-to-end perceived | a sound enters the microphone | the corresponding translated sound leaves the speaker | The number the conversation actually feels |

**L4 is measured by loopback and cross-correlation, never by summing L1–L3
or the per-stage timings.** That is `2026-08-22-translator-research-plan.md`
§5.2 and it is correct: summation misses device buffer latency, queue
waits, and the time a stage holds a partial before committing. The gap
between the sum and the measured total is real latency the instrumentation
cannot see, and finding it is the point.

**But L4 cannot be measured in Phase 1**, because Phase 1 has no acoustic
path and this host has no capture endpoint (§2.1) and no virtual audio
cable. Phase 1 reports **L4-sim**: the pipeline is fed from a file at
exactly 1× wall-clock with the feed timestamps recorded, and emissions are
timestamped on the same clock. **Never label L4-sim as L4.** It excludes
every hardware buffer, which is precisely the term the loopback method
exists to catch.

**Two more required distinctions, both `[AGENT]` from the simultaneous-
translation evaluation literature:**

- **Computational-aware vs. ideal latency.** A system evaluated
  faster-than-real-time can look fast for a reason that will not survive
  deployment. SimulEval reports both; so must this. Run every candidate
  **twice**: once at 1× real-time, once as-fast-as-possible. The gap is
  how much of the latency is compute and how much is policy.
- **p50 and p95 always, never a mean** (2026-08-22 §5.1). Add **p99 for the
  interruption suite only** (§4.5), where the tail is the finding.

Per-stage attribution (VAD / ASR / MT / TTS / **the buffering between
them**) explains the total; it does not constitute it.
`tower/instrumentation.py`'s `StageTimer` EXISTS and is the right shape for
this — a context manager per named stage, snapshotted per unit of work.

### 4.3 Accuracy — three metrics and one gate, all applied identically

**Quality of the delivered translation.**

- **Headline: COMET.** `[AGENT]` A neural quality-estimation metric that
  correlates better with human judgement than n-gram overlap, and standard
  in the IWSLT simultaneous tracks alongside BLEU.
- **Secondary: sacreBLEU.** Reproducible and version-pinnable, which COMET
  is not by default.
- **Pin both.** Record the sacreBLEU signature string and the exact COMET
  checkpoint name in the report. A COMET score without a checkpoint name is
  not a number anyone can reproduce — the same discipline
  `tower/experiments/depth.py` already applies by pinning the MiDaS hub
  commit, and for the same recorded reason ("floating on the default branch
  is a reproducibility risk for a measured baseline, not theoretical").

**Latency and quality jointly: StreamLAAL.** `[AGENT]` Length-Adaptive
Average Lagging, in its streaming/unbounded-speech form, computed within
the SimulEval framework; it is what the IWSLT simultaneous speech-to-text
track uses. This matters more than either metric alone: **a streaming
translator has no single quality number, it has a quality-versus-lag
curve**, and a candidate wins by dominating the curve, not by winning one
column. Report a scatter of COMET against StreamLAAL with one point per
policy setting per candidate, and read the Pareto front.

**Instability: revision count and contradiction rate.** For every candidate
that revises partials — 2, 3 and especially 4:

- *revisions per utterance*: how many times an already-emitted token was
  replaced.
- *contradiction rate*: the fraction of utterances in which a token the
  wearer **already heard** was later replaced by a semantically
  incompatible one. This is `2026-08-22-translator-research-plan.md` §5.3's
  trap, made countable. **Score the spoken output, not the final corrected
  text.** A hybrid that speaks badly and silently fixes the transcript has
  not helped the conversation, and a correction the listener has to un-hear
  is worse than a consistent imperfect translation.
- This requires the spoken output to be logged as a timestamped token
  stream, which is why §6.3's emission log is the harness's primary
  artifact rather than a debug convenience.

**The gate, not a metric: fabrication rate.** Two extra corpora — pure
silence, and noise-only (traffic, café, fan) — with **zero** reference
content. Count non-empty outputs. `[AGENT]` Whisper-family models are known
to emit fluent text on silence. `[REPO]` Rule 16 applies to audio exactly
as to pixels: a translation of audio the system did not resolve is a
fabrication. **A candidate that fabricates does not get a quality score; it
gets a defect report.** The pipeline must be able to say "I did not catch
that."

### 4.4 GPU and CPU utilisation, and the number that actually decides

- **VRAM.** Peak *allocated* and peak *reserved* via
  `torch.cuda.max_memory_allocated` / `max_memory_reserved` where torch owns
  the model — **plus** process-level `nvidia-smi` sampling, because
  CTranslate2 and Ollama do not allocate through torch and would report
  zero. Record **headroom, not usage**: §2 measured 5228 MiB already
  resident on an idle desktop, so "fits in 12 GB" is a false claim on this
  machine and a true one on a clean one.
- **The deciding number: co-resident VRAM.** Measure ASR + MT/LLM + TTS
  **all loaded at once**, because that is the deployed condition. The sum of
  three separately-measured peaks is not the same number, and a candidate
  that fits component-by-component and not together has failed.
- **GPU utilisation** sampled at ≥5 Hz across the utterance and reported as
  a distribution, not an average. An average over a mostly-idle window
  hides a saturating burst, and the burst is what collides with a second
  model.
- **CPU** via `psutil` (already a project dependency, `pyproject.toml`):
  per-process CPU-seconds and peak RSS. Report **cores-equivalent**, not
  percent — 20 cores make percentages meaningless.

### 4.5 Streaming behaviour under interruption and overlapping speakers

`2026-08-22-translator-research-plan.md` §5.4 names these; here is how to
make each one produce a number.

**Interruption suite.** A scripted set, each item recorded or constructed
deliberately: speaker stops mid-clause; speaker restarts with a different
sentence; a 2-second pause mid-clause; a cough; a false start with
self-repair ("I went to — we went to the market"). For each: does the
pipeline emit a truncated translation, wait, or **fabricate a
completion**? A fabricated completion is a Rule 16 failure and goes in the
gate of §4.3, not the quality table.

**Overlap suite.** Built by mixing two single-speaker recordings at
controlled offsets (0%, 25%, 50% overlap) and controlled relative SNR
(0, −6, −12 dB). **Synthetic mixing, labelled as synthetic** — the same
honesty this repo already applies to rendered imagery
(`scripts/scene_benchmark.py` docstring). Three outcomes to count:

1. which speaker survives, and whether the choice is stable;
2. whether the output **interleaves two speakers into one grammatical
   sentence** — the worst failure available, and the one an LLM-based
   candidate is structurally most prone to, because fluency is its
   objective;
3. whether the system reports that it could not resolve the input.

Two people talking at once is the *normal* case in the conversation this
feature exists for, so this suite is not an edge case and its results are
not a footnote.

**Barge-in.** New speech arrives while translated audio is still playing.
On a shared HFP link (§1.2b) this is not hypothetical — the output and the
input are the same Bluetooth session. Phase 3 only, because it requires the
real link.

### 4.6 Memory and cold start

- Steady-state RSS, and RSS after 30 minutes of continuous streaming — a
  leak check, in the shape of `scripts/soak_test_stream.py`.
- **Cold-start model load time, per component and summed.** This is not
  cosmetic: `tower/modules/container.py:16` sets
  `LIFECYCLE_TIMEOUT_S = 10.0`, and a candidate whose stack cannot load in
  ten seconds cannot ever become a `Module` under the current contract.
  See §6.2(d).

---

## 5. Division of responsibility: glasses, phone, Tower

### 5.1 The glasses row is the same for every candidate

`[REPO]` DAT exposes no compute, no IMU, no depth and no audio
(`2026-08-21-world-builder-readiness.md` §5.2), and Limitation 13 puts
audio outside DAT entirely. **The glasses capture and play back. That is
all they can do, under every candidate.** So the division question is not
three-way; it is *phone versus Tower*, with a fixed glasses row.

### 5.2 Three splits, independent of which model wins

| Split | Where the work runs | Latency cost | Battery cost | The question it answers |
|---|---|---|---|---|
| **A — thin phone** | Glasses mic → phone relays raw PCM → Tower does VAD+ASR+MT+TTS → audio back → phone → glasses | Two Bluetooth hops plus a WiFi round trip, **each way**. Uplink is continuous audio, not bursty | Phone radio active continuously in both directions; glasses HFP session continuous. Worst of the three for both devices | Is the Tower's compute worth two extra hops? |
| **B — phone segments** | Phone does VAD and phrase segmentation, sends only speech segments; Tower does ASR+MT+TTS | Same hops, but far fewer bytes and no uplink during silence. Adds phone CPU for VAD | Better than A on radio (silence costs nothing), worse on CPU. `[AGENT]` Silero-class VAD is a few MB and cheap enough for a phone | Does moving the cheapest stage to the edge pay for itself? |
| **C — phone only** | Everything on the phone. No Tower at all | No network at all. Bounded by phone compute | Phone CPU/NPU heavy, radio idle. Thermal risk on a long conversation | **The one that must be measured or the Tower's value is asserted rather than shown** |

**Split C is not a strawman and skipping it would be dishonest.** If a
phone-local pipeline lands within ~100 ms of the Tower pipeline at
comparable quality, the Tower contributes latency and a dependency and
nothing else for this module. That would be a real finding and the plan
must be able to produce it. `[INFERENCE]` It is also the split most likely
to be true for candidate 2 with small models, and least likely for
candidates 1 and 3.

### 5.3 Per candidate

| Candidate | Glasses | Phone | Tower | Latency consequence | Battery consequence |
|---|---|---|---|---|---|
| **1 — direct S2ST** | capture, playback | relay (split A) or nothing (C) | one model, audio in → audio out | Fewest stage boundaries, so the fewest hidden buffers. Whole-pipeline latency is one model's latency | Best case for phone CPU under A; C is unlikely — S2ST models are the largest in the set |
| **2 — ASR + NMT** | capture, playback | VAD under B | two models, one shared runtime if both are CTranslate2 | NMT waits on ASR finalisation. That wait is the whole risk and it is measurable as (L3 − L1) | Most plausible split-C candidate: smallest models in the set |
| **3 — ASR + local LLM** | capture, playback | VAD under B | ASR + an out-of-process LLM server | Two processes and an IPC boundary that the per-stage timers will not see. Measure it explicitly or it hides in the gap between summed and measured L4 | Tower-only in practice. An 8B model is not a phone budget |
| **4 — hybrid** | capture, playback | VAD under B | fast path + LLM correction path, concurrent | Best L2 by construction; worst contradiction rate by construction. §4.3 is the metric that keeps it honest | Two models resident. Worst VRAM co-residency (§4.4) |

**On battery, one honest statement:** this repository has measured nothing
about battery, on any device, ever. The measurable proxies are (i) glasses
battery drain per hour of continuous HFP session, (ii) phone CPU-seconds
per minute of conversation, (iii) uplink bytes per minute. All three need
hardware and are Phase 3. Until then, every battery claim in this
document — including the table above — is `[INFERENCE]` about where work
happens, not a measurement of energy.

---

## 6. Benchmark harness design

### 6.1 What the repository's measurement convention actually is

EXISTS, and it is consistent across four scripts
(`scripts/cv_lab_benchmark.py`, `scripts/depth_benchmark.py`,
`scripts/scene_benchmark.py`, `scripts/world_builder_benchmark.py`):

- A standalone `scripts/*_benchmark.py`, argparse, `--format json`.
- A docstring that states **what the numbers do not say** before it states
  what they do ("SYNTHETIC, NOT PHYSICAL").
- `_timed()`: one untimed warm-up, then N repeats, reporting mean / median
  / max — "without it the first sample carries one-off initialisation and
  publishes an artifact as a cost".
- Model-backed work is opt-in behind a flag (`--models` / `--no-models`),
  because weights are a download.
- `sys.path.insert` to import `tower`, and library stdout redirected to
  stderr so `--format json` stays machine-readable.
- Behind it, `tower/experiments/__init__.py`: an `Experiment` protocol
  (`load` / `run` / `release`), `ExperimentSettings`, `ExperimentResult`,
  and `EXPERIMENTS`, a registry of **factories** — deliberately not
  instances, so importing the module does not load weights.

### 6.2 Translator does not fit `Experiment`, for four structural reasons

Not "would be awkward". Structurally cannot.

**(a) `run(raw_bytes) -> ExperimentResult` is one-shot.** One input, one
result, returned when finished. A streaming translator produces *N* outputs
per input, and **the times at which it produces them are the measurement**.
There is no return slot for a sequence of timestamped emissions, and adding
one changes the Lab's own type.

**(b) `ExperimentResult.metrics` is `dict[str, float]`.** A translation is
text. `tower/experiments/__init__.py:111-115` states the constraint and its
reason in a comment: "Floats only, on purpose: this is a measurement
channel, not a general result channel." `CARTRIDGE-GROUNDWORK.md` §5.3 goes
further — widening it beyond numbers "would be a quiet way of pretending"
the structured-result gap is closed. **So do not widen it.** The gap is
real and V1.0 work, and this benchmark must not be the thing that spends
that decision.

**(c) The module path is synchronous and single-slot.**
`Module.process()` takes bytes and returns synchronously;
`ModuleContainer` is "a registry of one" by its own docstring; and
`CARTRIDGE-GROUNDWORK.md` §5.4 records that no worker, queue or
asynchronous execution path exists. Audio ingest is continuous and
inherently asynchronous. These do not meet.

**(d) `LIFECYCLE_TIMEOUT_S = 10.0`** (`tower/modules/container.py:16`), and
the load path calls `asyncio.wait_for(self._module.load(), ...)`. `[AGENT]`
A cold faster-whisper + NMT + TTS load — three model loads, plus any
first-run weight download — will not reliably complete in ten seconds. And
the fix cannot be applied:
`docs/superpowers/specs/2026-08-21-v1.1-lifecycle-timeout-enforcement-design.md`
is marked **"⛔ BLOCKED — NOT AUTHORIZED TO IMPLEMENT"**, pending a user
ruling that is still unrecorded (`2026-08-22-cartridge-run-report.md` §9,
blocker 6). **A Translator `Module` cannot be registered today even if
everything else in §1.3 existed.** This is worth stating because it
removes an entire tempting shortcut.

### 6.3 PROPOSED: `scripts/translator_benchmark.py`, standalone

Do not make Translator an `Experiment`. Do not make it a `Module`. Build a
standalone offline harness that matches the *conventions* of §6.1 while
declining the *type* of §6.2 — because fitting it would require changing
files that three other cartridges depend on, which both the cartridge run
report and `CARTRIDGE-GROUNDWORK.md` flag as the expensive move.

```
scripts/translator_benchmark.py
  --corpus <dir>          tier A / B / C corpus root
  --pipeline <name>       one of the registered candidates
  --device {cpu,cuda}
  --narrowband            resample to 8 kHz mono before feeding (tier C)
  --realtime / --asap     the §4.2 computational-vs-ideal pair
  --repeat N
  --format json
```

Its own protocol, deliberately shaped like `Experiment` where the lifecycle
discipline is worth copying and unlike it where the one-shot return is the
problem:

```python
# PROPOSED — not written, not authorised.
@dataclass(frozen=True)
class Emission:
    t_emit_s: float          # harness clock, same clock as the feed
    kind: str                # "partial" | "final_text" | "audio"
    text: str | None
    n_samples: int | None
    revises: bool            # did this replace something already emitted?

class TranslationPipeline(Protocol):
    name: str
    def load(self, settings: PipelineSettings) -> None: ...
    def stream(self, source: AudioSource) -> Iterator[Emission]: ...
    def release(self) -> None: ...

PIPELINES: dict[str, Callable[[], TranslationPipeline]] = {...}
```

`load` / `stream` / `release`, and a registry of **factories** — same
reason the CV registry gives, that constructing at import would load
weights in any process that so much as imports the module.

**The emission log is the primary artifact, and the harness computes no
quality metric.** It records what was emitted and when; every number in §4
is derived from that log offline, by a separate scorer. Two reasons: a
harness that scores is a harness that must be re-run when the metric
changes, and the contradiction rate of §4.3 is a property of the log's
*history*, not of any single result object.

### 6.4 SimulEval: score with it, do not drive with it

`[AGENT]` SimulEval is the standard toolkit for AL / LAAL / StreamLAAL and
is what the IWSLT simultaneous track uses. **PROPOSED:** emit a
SimulEval-compatible instance log from our own harness and score it in a
**throwaway virtualenv**, so nothing enters `pyproject.toml`. Driving the
pipeline *through* SimulEval's agent API would mean adopting its dependency
tree into this project for the sake of a scorer.

`[INFERENCE]` Whether its instance-log format is stable enough to be
produced by a foreign harness is unverified. Open Question 4.

---

## 7. Phase 1 — what can be measured TODAY, with no hardware change

This is the actionable part and it comes first for that reason.

### Phase 1a — zero hardware, zero purchases

| # | Step | Blocks |
|---|---|---|
| **1a.0** | **Restore CUDA torch**, CUDA index *first*, per `README.md:62-95`. Confirm with `scripts/verify_cuda.py`, which today fails with `ModuleNotFoundError` | every GPU number |
| **1a.1** | `pip install --dry-run` **every** audio candidate before installing any of them. Check three things: a second `cv2`; `nvidia-*` wheels (a second CUDA runtime); a system `ffmpeg` requirement. Precedent and reason: the `ocr` extra comment in `pyproject.toml`, where a dry-run is what rejected `rapidocr_onnxruntime` | §9 |
| **1a.2** | Fetch tier A (CoVoST 2, CC0). Files only. No hardware | corpus |
| **1a.3** | Derive tier C from tier A: 8 kHz mono, band-limited. A resampling call | the only arm that transfers |
| **1a.4** | Build the silence and noise-only gate corpora. Silence is free; noise can be sourced or generated | §4.3 gate |
| **1a.5** | Build the overlap suite by mixing tier A speakers at controlled offset and SNR. **Label synthetic** | §4.5 |
| **1a.6** | Write `scripts/translator_benchmark.py` (§6.3) and one pipeline adapter per candidate | harness |
| **1a.7** | Run all four candidates × {native, narrowband} × {realtime, asap}. Record the emission log for every run | everything |
| **1a.8** | Score offline: COMET + sacreBLEU (pinned), StreamLAAL, revision/contradiction counts, fabrication counts, co-resident VRAM, CPU-seconds, cold-start | the decision |

**What Phase 1a settles:** the relative ranking of four architectures on
translation quality, on streaming lag, on the quality-versus-lag curve, on
fabrication, on VRAM co-residency and on cold-start. That is enough to
eliminate candidates. It is most of the value of this plan.

**What Phase 1a cannot settle, and must say so in its report:** anything
about real acoustics, real conversation, barge-in, Bluetooth latency,
battery, or the wearer's experience. `L4` does not exist here; only
`L4-sim`. The report header should read **RECORDED, NOT WORN**, in the
tradition of `SYNTHETIC, NOT PHYSICAL`.

### Phase 1b — one microphone (a ~$20 change, not a platform change)

Try the DualSense controller first (§2.1) before buying anything. Then:
record tier B; produce its reference translations (Open Question 5); re-run
1a.7–1a.8 against tier B. **Tier B is the arm that can overturn a tier-A
ranking**, and it should be expected to.

### Phase 2 — Tower-local acoustic path

The 2026-08-22 plan's own first stage: Tower microphone, Tower speakers,
loopback rig, real L4 by cross-correlation. Needs a capture endpoint and a
loopback path, neither of which exists here today.

### Phase 3 — the glasses path

Gated by `2026-08-22-translator-research-plan.md` §9, unchanged, plus §1.3
of this document. Answer Open Questions 1 and 2 **before** anything else in
this phase, because both can invalidate a tier-C assumption or a product
decision.

---

## 8. The four candidates: what would have to be measured to choose each

No pre-selection. For each: the claim, the measurement that would make it
win, and the specific thing that would disqualify it.

### Candidate 1 — direct speech-to-speech / speech translation

- **Claim:** one model beats a chain because no stage waits for the
  previous one to finalise.
- **Wins if:** it dominates the COMET-vs-StreamLAAL curve on **tier C**,
  and its co-resident VRAM fits with room for nothing else because it needs
  nothing else.
- **Disqualified by:** Rule 16. It is the least inspectable candidate —
  when it is wrong there is no transcript to look at — so if it cannot
  signal "I did not catch that", it fails the §4.3 gate regardless of its
  quality score.
- **Licence trap:** `[AGENT]` SeamlessM4T v2 and SeamlessStreaming are
  **CC-BY-NC 4.0**. That is research-only. They can legitimately be
  measured as a **quality ceiling** — a reference showing what the class of
  approach can do — but not shipped, and the report must not present a
  CC-BY-NC number as an available option. `[AGENT]` Apache-2.0
  alternatives in this space as of 2026 include Voxtral Mini/Small (audio
  chat, Apache-2.0) and Qwen3-Omni-30B-A3B (Apache-2.0, but 30B — see §9).
  Note that Voxtral **TTS** is CC-BY-NC while Voxtral's audio models are
  Apache-2.0; the licence differs within one product family, so check
  per-artifact, not per-vendor.

### Candidate 2 — streaming ASR + dedicated NMT

- **Claim:** two specialised models, each doing one thing well.
- **Wins if:** the added chain lag `(L3 − L1)` is small enough that its
  point on the curve is not dominated, **and** it stays within a stated
  COMET margin of candidate 1.
- **Disqualified by:** an NMT that only accepts complete sentences. That is
  not a tuning problem, it is the architecture's failure mode, and it shows
  up as a large L2 with a good final COMET.
- **The operational advantage worth measuring, not assuming:** `[AGENT]`
  faster-whisper and Opus-MT can both run on **CTranslate2**, so ASR and MT
  share one inference runtime — one dependency, one quantisation story, one
  set of CUDA libraries. `[INFERENCE]` If that holds, it is a real cost
  advantage over every other candidate and it belongs in the decision
  alongside the latency numbers.

### Candidate 3 — streaming ASR + a small local LLM

- **Claim:** an LLM handles idiom and context an NMT model misses.
- **Cheapest to test on this host** (§2.2): Ollama and `llama3.1:8b` are
  already installed, out-of-process, no pip dependency, no download.
- **Wins if:** it beats candidate 2 **on tier B** — the conversational
  tier, where idiom and context actually appear — by a margin that survives
  its lag penalty on the curve. A win on tier A read speech is not a win;
  read speech is where NMT is strongest and idiom is scarcest.
- **Disqualified by:** fabrication rate. An LLM's objective is fluency, and
  the §4.3 silence/noise gate and the §4.5 overlap-interleaving check are
  aimed squarely at it.
- `[REPO]` Standing project rule: do not force every problem through an
  LLM. Candidate 3 exists to be **measured against** the dedicated path,
  not assumed better.

### Candidate 4 — hybrid: fast path + LLM contextual correction

- **Claim:** speak the fast translation immediately, correct it as context
  arrives.
- **Cannot be evaluated first.** It is *defined* in terms of 2 and 3, so it
  is only meaningful once both have numbers. Sequence it last.
- **Wins if:** scored **on the spoken output** (never the corrected text)
  it is Pareto-better on the curve than both its components, **and** its
  contradiction rate is low enough that a listener is not repeatedly asked
  to un-hear something.
- **Disqualified by:** a contradiction rate above whatever threshold is set
  *before* the run. Set the threshold first. Setting it afterwards is how a
  hybrid wins a benchmark it should have lost.

---

## 9. Honest sizing: models, VRAM, downloads, licences, and dependency cost

`[AGENT]` throughout, from searches made 2026-08-25. **Every figure here is
an estimate to be replaced by a measurement in Phase 1a.** Sizes and VRAM
are quoted from vendor and third-party benchmark write-ups, not measured on
this Tower.

| Role | Candidate | Size | Approx VRAM | Licence | Runtime | New pip deps |
|---|---|---|---|---|---|---|
| ASR | faster-whisper `large-v3` int8 | ~1.5 GB weights | **~2.5 GB** | MIT (impl), MIT (weights) | CTranslate2 | `faster-whisper`, `ctranslate2`, `nvidia-*` |
| ASR | faster-whisper `small`/`medium` int8 | smaller | <2.5 GB | as above | CTranslate2 | as above |
| ASR+ST | NVIDIA Canary-1b-v2 (transcribe **and** translate) | 1B | ~2–3 GB | **CC-BY-4.0 — permissive** | NeMo | **NeMo is a large tree.** Flag it |
| ASR | NVIDIA Parakeet TDT 0.6b v3 | 0.6B | ~1–2 GB | permissive | NeMo | as above |
| NMT | Opus-MT / MarianMT, per pair, CTranslate2 int8 | tens of MB | small | **Apache-2.0** | CTranslate2 (**shared with ASR**) | none beyond CTranslate2 |
| NMT | NLLB-200-600M int8 | ~600 MB | ~1 GB | **CC-BY-NC** | CTranslate2 | reference only |
| S2ST | SeamlessStreaming / SeamlessM4T v2 | large | multi-GB | **CC-BY-NC** | fairseq2 | reference ceiling only |
| Speech LLM | Voxtral Mini / Small | 3–24B class | pair-dependent | **Apache-2.0** | transformers/vLLM | large |
| Omni | Qwen3-Omni-30B-A3B | 30B (A3B MoE) | **exceeds 12 GB** | Apache-2.0 | transformers/vLLM | **out of range on this GPU** |
| LLM | llama3.1:8b q4 | **4.9 GB, already on disk** | ~5–6 GB | Llama community licence | **Ollama, out-of-process** | **none** |
| TTS | Piper | ~50–100 MB/voice | CPU-viable | **MIT** | onnxruntime | `onnxruntime` |
| TTS | Kokoro 82M | ~341 MB | ~1–2 GB | **Apache-2.0** | torch/onnx | modest |
| TTS | Voxtral TTS | 4B | multi-GB | **CC-BY-NC** | transformers | reference only |

**Three sizing observations that change decisions, not just budgets:**

1. **VRAM co-residency is tighter than the table suggests.** §2 measured
   5228 MiB already resident, leaving ~7.0 GB. faster-whisper large-v3
   (~2.5 GB) + llama3.1:8b (~5 GB) does **not** fit in 7 GB. Candidate 3 on
   this host, today, needs either a smaller ASR model, a smaller LLM, or a
   clean desktop. Measure it; do not assume the 12 GB figure.
2. **A published TTS latency number can disqualify a component on its
   own.** `[AGENT]` Piper is reported at ~1,720 ms first-token-to-speech and
   Kokoro at ~3,658 ms in one 2026 on-device comparison. If either figure
   holds in our configuration, the TTS alone blows the L2 budget no matter
   how fast the rest of the pipeline is — exactly the failure
   `2026-08-22-translator-research-plan.md` §6 warns about. These numbers
   are from someone else's hardware and configuration and **must be
   re-measured**; they are cited here as a reason to measure TTS *first*,
   not as a verdict.
3. **`[AGENT]` int8 quantisation is reported at ~2× the speed of float16
   with ~40% less VRAM and negligible accuracy loss** for CTranslate2 ASR.
   `[INFERENCE]` If that holds, quantisation is the cheapest lever in this
   plan and belongs in the run matrix from the start — the same reasoning
   `2026-08-20-gpu-nvidia-roadmap.md` §4 applies to FP16 ("a cheaper first
   step than TensorRT").

### The dependency posture this repository actually has

`pyproject.toml` records a specific reason for every choice, and the
Translator stack must clear the same bar:

- **A second `cv2` is a known breakage.** The `ocr` extra comment records
  that `rapidocr_onnxruntime` was rejected because a `pip --dry-run` showed
  it would install `opencv-python` alongside this project's
  `opencv-python-headless`. Run the same dry-run for every audio candidate.
- **A second CUDA runtime is the new version of that hazard.**
  `[AGENT]` CTranslate2's GPU support pulls NVIDIA CUDA/cuDNN libraries as
  `nvidia-*` wheels. Those may or may not collide with the CUDA-indexed
  torch build that `README.md:62-95` goes out of its way to protect. **This
  is the single highest-risk dependency question in the plan** and it is
  answerable by a dry-run before anything is installed.
- **`torchaudio` is a trap here.** Installing it can resolve a torch
  variant and quietly replace the CUDA build — the `README.md:62-95` hazard
  in a new place, with the same silent symptom (`TOWER_CV_DEVICE=auto`
  falling back to CPU with no error). `[AGENT]` `soundfile` (libsndfile,
  bundled, no ffmpeg, no torch) is the cheaper WAV read path. Verify by
  dry-run.
- **`ffmpeg` is not on PATH** (§2) and installing a system binary is
  outside pip's reach. `[AGENT]` faster-whisper can be fed numpy arrays
  directly, avoiding it — **verify that** rather than assuming it, because
  "needs a system binary pip cannot install" is exactly why `pytesseract`
  was rejected for the `ocr` extra.
- **Ollama's out-of-process design is a genuine advantage** for candidate 3
  and should be counted as one: it cannot pollute the venv. Its cost is
  VRAM and an IPC boundary, both of which §4.4 and §5.3 already measure.

---

## 10. What I would NOT do, and why

1. **Would not add an audio message type to the WS protocol in Phase 1.**
   Nothing can produce audio to put in it. The backend audit's §13 says
   protocol versioning becomes valuable *when* message shapes diverge — it
   should land with the divergence, not ahead of it.
2. **Would not widen `ExperimentResult.metrics` beyond floats.**
   `CARTRIDGE-GROUNDWORK.md` §5.3 calls that "a quiet way of pretending"
   the structured-result gap is closed. A benchmark must not spend a V1.0
   architecture decision as a side effect.
3. **Would not make Translator a `Module`.** `LIFECYCLE_TIMEOUT_S = 10.0`
   and the V1.1 timeout spec is explicitly blocked pending an unrecorded
   user ruling. Doing it anyway means either shipping a module that cannot
   load, or making the ruling on the user's behalf.
4. **Would not build the loopback rig in Phase 1.** It is the correct way
   to measure L4 and the 2026-08-22 plan is right about it — but it
   measures the *acoustic path*, and Phase 1 has none. Built now, it would
   produce a number about this desktop's sound card and nothing else.
5. **Would not benchmark on CoVoST alone and call it decided.** Read speech
   is not the use case, and a ranking from tier A that is never checked
   against tier B is the most likely way this plan produces a confident
   wrong answer.
6. **Would not use a cloud translation API as a reference ceiling on tier
   B.** Tier A is CC0 public data and a cloud reference on it is fine. Tier
   B is locally recorded human conversation, and sending a bystander's
   voice to a third party is what `06-PRIVACY-DATA.md` treats as an
   explicit documented opt-in exception, never a benchmark convenience.
7. **Would not adopt TensorRT, ONNX Runtime EPs or `torch.compile` for
   this.** `2026-08-20-gpu-nvidia-roadmap.md` sets the trigger discipline
   (and records that `torch.compile` has no Windows support). More
   specifically: CTranslate2 *is already* a compiled C++ inference engine,
   so the graph-compiler question does not arise here the way it did for
   MiDaS.
8. **Would not install `torchaudio` to read a WAV file** (§9).
9. **Would not benchmark more than one language pair in Phase 1.** Both
   directions of one pair is enough to rank four architectures. N pairs
   multiplies run cost and changes no ranking.
10. **Would not report a mean.** p50 and p95, per the 2026-08-22 plan. A
    translator that is usually fast and occasionally three seconds late is
    a translator nobody trusts, and a mean hides exactly that.
11. **Would not let candidate 4 be scored on its corrected transcript.**
    Stated three times across two documents now, because it is the single
    easiest way for this benchmark to produce a wrong winner.

---

## 11. Open questions

1. **Does Ray-Ban Gen 2 HFP actually deliver 8 kHz, or does it negotiate
   mSBC at 16 kHz?** Limitation 13 says 8 kHz mono beamformed. This one
   answer determines whether tier C is the headline arm or a robustness
   check, and it can change which candidate wins. *Answered by:*
   `search_dat_docs` per Rule 4, plus real-hardware route inspection on the
   iOS side.
2. **If HFP is active, what does the wearer hear the translation
   through?** A2DP is unavailable during HFP (§1.2b). Glasses over
   narrowband HFP, the phone's speaker, or a third device — these have
   very different products attached to them. *Answered by:* iOS, and it is
   a product decision before it is a technical one.
3. **What is the observation-time source for an audio chunk?**
   `IOS-to-Tower.md` §0.3 already flags that it is unresolved whether DAT's
   `CMSampleBuffer` presentation timestamp is capture time or phone-arrival
   time. Audio has no answer at all yet, and every `observedAt` claim and
   every latency number depends on one.
4. **Is SimulEval's instance-log format stable enough to be produced by a
   foreign harness (§6.4)?** If not, either the scorer is reimplemented —
   with the reproducibility cost that carries — or SimulEval drives the
   pipeline and its dependency tree enters the project.
5. **Who writes the reference translations for tier B, and what does it
   cost?** This is the main non-compute cost in the plan and it has no
   owner.
6. **Does this project intend commercial distribution?** If not, CC-BY-NC
   models — SeamlessStreaming, NLLB-200, Voxtral TTS — become live options
   and the candidate set widens considerably. This is a product question
   that materially changes a technical answer, and it should be settled
   before Phase 1a.7 rather than after.
7. **Is Split C allowed to win?** If a phone-local pipeline is good enough,
   does the platform accept a cartridge that does not use the Tower at all?
   `01-SYSTEM-ARCHITECTURE.md`'s heterogeneous-compute section is the
   nearest thing to a policy and it is listed under Future Research.
8. **Must the VRAM budget accommodate a second cartridge?** Today no —
   `ModuleContainer` is a registry of one. But that is an artifact of V0.8,
   not a decision, and the answer changes every co-residency number in
   §4.4.
9. **Is the DualSense controller usable as the Phase 1b capture device?**
   Cheapest possible unblock (§2.1), untested.

---

## 12. Sources

Repository documents this plan is grounded in:

- `docs/superpowers/plans/2026-08-22-translator-research-plan.md`
- `guidelines/docs/modules/TRANSLATOR.md`
- `guidelines/docs/modules/CARTRIDGE-GROUNDWORK.md` §4 (Translator), §5
- `guidelines/docs/07-PLATFORM-CONSTRAINTS.md` Limitation 13, Core Principles 2/4/5
- `guidelines/docs/05-DAT-INTEGRATION.md` (Rule 4)
- `guidelines/docs/03-ROADMAP.md` Phase 3
- `guidelines/docs/06-PRIVACY-DATA.md` Real-World Capture, Explicit Dataset-Recording Sessions
- `docs/superpowers/research/2026-08-20-platform-backend-audit.md` §6, §7, §13
- `docs/superpowers/research/2026-08-20-gpu-nvidia-roadmap.md`
- `docs/superpowers/research/2026-08-21-world-builder-readiness.md` §3.1, §5.2
- `docs/superpowers/specs/2026-08-21-v1.1-lifecycle-timeout-enforcement-design.md` (BLOCKED)
- `guidelines/docs/reports/2026-08-22-cartridge-run-report.md` §9
- `IOS-to-Tower.md` §0
- `tower/frames.py`, `tower/routes/ws.py`, `tower/modules/base.py`,
  `tower/modules/container.py`, `tower/experiments/__init__.py`,
  `tower/instrumentation.py`, `tower/config.py`
- `scripts/cv_lab_benchmark.py`, `scripts/depth_benchmark.py`,
  `scripts/scene_benchmark.py`, `scripts/verify_cuda.py`
- `pyproject.toml` (`ml` and `ocr` extra comments), `README.md:62-95`

`[AGENT]` external sources, searched 2026-08-25. These are outside
knowledge, not repository findings, and every quantitative claim taken from
them is marked as an estimate to be replaced by measurement:

- [Ultimate Guide — The Best Open Source Models for Speech Translation in 2026 (SiliconFlow)](https://www.siliconflow.com/articles/en/best-open-source-models-for-speech-translation)
- [Best open source speech-to-text (STT) model in 2026, with benchmarks (Northflank)](https://northflank.com/blog/best-open-source-speech-to-text-stt-model-in-2026-benchmarks)
- [Whisper.cpp vs faster-whisper 2026: STT Speed Test (PromptQuorum)](https://www.promptquorum.com/power-local-llm/local-whisper-stt-comparison-2026)
- [faster-whisper (PyPI)](https://pypi.org/project/faster-whisper/)
- [Simulstream: Open-Source Toolkit for Evaluation and Demonstration of Streaming Speech-to-Text Translation Systems (arXiv 2512.17648)](https://arxiv.org/pdf/2512.17648)
- [CMU's IWSLT 2025 Simultaneous Speech Translation System (arXiv 2506.13143)](https://arxiv.org/pdf/2506.13143)
- [SimulEval: An Evaluation Toolkit for Simultaneous Translation](https://www.researchgate.net/publication/347234300_SIMULEVAL_An_Evaluation_Toolkit_for_Simultaneous_Translation)
- [Seamless: Multilingual Expressive and Streaming Speech Translation (arXiv 2312.05187)](https://arxiv.org/pdf/2312.05187)
- [facebookresearch/seamless_communication (licence)](https://github.com/facebookresearch/seamless_communication)
- [CoVoST: A Large-Scale Multilingual Speech-To-Text Translation Corpus (CC0)](https://github.com/facebookresearch/covost)
- [CoVoST 2 and Massively Multilingual Speech-to-Text Translation (arXiv 2007.10310)](https://arxiv.org/abs/2007.10310)
- [Popular Open-Source Translation Models for Mobile & Embedded, 2026 (Picovoice)](https://picovoice.ai/blog/open-source-translation/)
- [Transformers — CTranslate2 documentation](https://opennmt.net/CTranslate2/guides/transformers.html)
- [On-device TTS Comparison: Open-source Benchmark 2026 (Picovoice)](https://picovoice.ai/blog/on-device-tts/)
- [Kokoro vs Piper vs XTTS v2: Local Text to Speech, 2026 (Contra Collective)](https://contracollective.com/blog/kokoro-vs-piper-vs-xtts-local-text-to-speech-m5-max-2026)
- [2026 European Open Speech Models: Parakeet, Canary, Nemotron (NVIDIA)](https://perspectives.nvidia.com/nemotron-speech/task/faq/what-are-the-most-production-ready-open-speech-recognition-models-for-european-l/)
- [NVIDIA Releases Open Dataset, Models for Multilingual Speech AI](https://blogs.nvidia.com/blog/speech-ai-dataset-models/)
- [Voxtral (arXiv 2507.13264)](https://arxiv.org/pdf/2507.13264)
- [Speaking of Voxtral (Mistral AI)](https://mistral.ai/news/voxtral-tts/)
- [Qwen3-Omni Technical Report (arXiv 2509.17765)](https://arxiv.org/abs/2509.17765)
