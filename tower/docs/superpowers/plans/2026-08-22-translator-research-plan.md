# Translator — research plan

**Status: PLAN ONLY. DO NOT IMPLEMENT.**

Written 2026-08-22 during the sequential cartridge run, which explicitly
scoped Translator to planning. Nothing here authorises code. The plan
exists so that whoever does build it starts from measured constraints
rather than from an architecture diagram.

Companion: `guidelines/docs/modules/TRANSLATOR.md` (the module concept).

---

## 1. The one ruling that shapes everything

**Prototype on the Tower, with a Tower microphone and Tower speakers,
entirely outside the glasses path. Only after a winning pipeline is
established does Ray-Ban microphone / iPhone / Bluetooth speaker
integration begin.**

That sequencing was given, and the platform's own state independently
justifies it: **there is no audio path anywhere in this system.** Not a
partial one — none.

- No microphone transport. `tower/frames.py` carries `seq`, `width`,
  `height`, `format`, `data` and nothing else; the WebSocket protocol has
  no audio message type.
- No audio recorder. `tower/capture.py` records JPEG frames.
- No streaming primitive, no output routing, no playback path.
- `07-PLATFORM-CONSTRAINTS.md` Limitation 13 already names audio as a
  separate sensor path whose availability through DAT is unestablished.

Translator is the first planned cartridge whose primary input is **not a
camera frame**. Everything the platform has built — frame quality,
keyframes, page detection, detection thresholds — is frame-shaped and
none of it transfers. Attempting the glasses path first would mean
building an audio transport, an audio recorder, a DAT audio integration
and a translation pipeline simultaneously, with no way to tell which one
was wrong when the latency came out bad.

---

## 2. Measured host reality (2026-08-22)

Probed, not assumed. **Nothing exists:**

| Component | Status |
|---|---|
| `sounddevice`, `pyaudio`, `soundfile`, `librosa`, `torchaudio` | all MISSING |
| `webrtcvad`, `silero_vad` | MISSING |
| `faster_whisper`, `whisper`, `transformers`, `ctranslate2`, `sentencepiece` | MISSING |
| `piper`, `pyttsx3`, `TTS` | MISSING |
| `ffmpeg` | not on PATH |
| `winsound` | available (Windows built-in, WAV playback only) |
| `torch` | 2.13.0 **+cpu** |

**And a blocker worth finding before anyone starts.** Enumerating audio
devices on this host:

```
Win32_SoundDevice:      NVIDIA High Definition Audio (OK)
                        NVIDIA Virtual Audio Device (OK)
                        Realtek High Definition Audio (OK)
AudioEndpoint (PnP):    Dell AW2720HF (NVIDIA High Definition Audio)
```

The only enumerated endpoint is a **monitor** — an output. **No capture
endpoint is listed, which means there is very likely no microphone
attached to this machine.**

This mirrors the earlier finding that no webcam exists here and every
`cv2.VideoCapture` index fails, which shaped the entire World Builder
run. **Verify with a plugged-in microphone before writing a line of
code**; the plan's own first stage is otherwise untestable, exactly as
World Builder's was.

CPU-only torch is also relevant: streaming ASR is the one stage in this
pipeline where GPU matters most, and the CUDA build must be restored
(`scripts/world_builder_env_check.py` reports the truth) before any
latency number is worth recording.

---

## 3. The architecture to research

```
Tower microphone
   |
VAD / phrase segmentation        when has someone finished a thought?
   |
streaming ASR                    partial hypotheses, not just finals
   |
source-language transcript
   |
translation
   |
streaming TTS
   |
Tower speakers
```

**Streamable and in-memory throughout. No intermediate files.** Writing a
WAV between stages is the single easiest way to add hundreds of
milliseconds and never notice, because each stage still looks fast in
isolation.

---

## 4. The four candidates to benchmark

They are not variations on a theme; they differ in where the latency
lives and in what can go wrong.

| # | Pipeline | The bet it makes | The risk it takes |
|---|---|---|---|
| 1 | **Direct speech-to-speech / speech translation** | One model beats a chain, because no stage waits for the previous one to finalise | Fewest models, least inspectable. When it is wrong there is no transcript to look at |
| 2 | **Streaming ASR + dedicated NMT** | Two specialised models each doing one thing well | Two model loads, two failure modes, and the NMT waits on ASR finalisation |
| 3 | **Streaming ASR + small (~3B) local LLM** | An LLM handles idiom and context an NMT model misses | Latency, and an LLM's willingness to produce fluent text for audio it did not actually hear |
| 4 | **Hybrid: fast dedicated path + LLM contextual correction** | Speak the fast translation immediately, correct it as context arrives | The hardest to evaluate honestly — see §5.3 |

**Do not pre-select.** The readiness discipline this project already uses
applies: the survey narrows, the measurement decides.

---

## 5. Metrics, defined precisely enough to be comparable

Vague latency numbers are worse than none. Each of these needs an
unambiguous start and stop point.

### 5.1 The three latencies

- **Time to first translated audio** — from the instant the *speaker
  stops making the sound that carries the meaning* to the instant the
  first translated audio sample leaves the output device. This is the
  number a conversation actually feels.
- **End-to-end microphone-to-ear latency** — from a sound entering the
  microphone to the corresponding translated sound leaving the speaker,
  for a complete utterance.
- **Per-stage attribution** — VAD, ASR, translation, TTS, and, crucially,
  **the buffering between them**.

Report **p50 and p95**, never a mean. A translator that is usually fast
and occasionally three seconds late is a translator nobody trusts, and a
mean hides exactly that.

### 5.2 Measure end-to-end by loopback, not by addition

**Summing per-stage timings will produce a wrong, flattering number.** It
misses device buffer latency, queue waits, and the time a stage spends
holding a partial hypothesis before it commits.

Measure it the only honest way: play a known source utterance into the
microphone path, record the speaker output, and **cross-correlate** the
two recordings to recover the true offset. Per-stage timings then explain
the total rather than constituting it — and any gap between the sum and
the measured total is real latency the instrumentation cannot see, which
is precisely the thing worth finding.

This mirrors what `01-SYSTEM-ARCHITECTURE.md` already asks for: a
translation pipeline with an unmeasured, unattributed latency budget
cannot be tuned.

### 5.3 Translation quality, and the trap in candidate 4

Quality needs a **fixed evaluation set decided before any pipeline runs**
— utterances with reference translations — and a stated metric. Whatever
is chosen, apply it identically to all four.

Candidate 4 needs one extra rule, because it can cheat by construction:
**score what the wearer HEARD, not the final corrected text.** A hybrid
that speaks a poor translation and silently fixes the transcript
afterwards has not helped the conversation. Measure the spoken output,
and measure how often a correction *contradicts* something already
spoken — a correction the listener has to un-hear is worse than a
consistent imperfect translation.

### 5.4 Report the failure modes, not only the averages

- Behaviour on **overlapping speech** — two people talking at once is the
  normal case in the conversation this feature exists for.
- Behaviour on an **unknown or mixed source language**.
- Behaviour on **background noise** and on a **far speaker**.
- What happens when ASR emits nothing: silence, or a fabricated
  translation? Rule 16 applies to audio exactly as it does to pixels — a
  translation of audio the system did not resolve is a fabrication, and
  the pipeline must say "I did not catch that" rather than produce fluent
  output.

---

## 6. Component survey — a starting list, not a selection

None of these is installed. Each needs its licence, footprint and
Windows/CPU viability checked at the time, exactly as the OCR decision in
Document Memory was.

- **Capture:** `sounddevice` (PortAudio) is the usual low-friction
  choice on Windows and streams in-memory blocks, which the no-files rule
  requires.
- **VAD:** WebRTC VAD is cheap and crude; Silero VAD is a small neural
  model with better behaviour on noise. Phrase segmentation is a
  *different* problem from voice activity and may need its own logic.
- **ASR:** the `faster-whisper` / CTranslate2 family is the obvious
  starting point for streaming with partial hypotheses on modest
  hardware. Whisper-family models are multilingual, which also addresses
  source-language detection.
- **NMT:** small dedicated translation models exist in the same
  CTranslate2 ecosystem, which keeps the runtime shared with ASR — a real
  operational advantage worth weighing.
- **LLM:** a ~3B local model. Note the standing project rule: **do not
  force every problem through an LLM.** Candidate 3 exists to be
  *measured against* the dedicated path, not to be assumed better.
- **TTS:** streaming matters more than voice quality here. A TTS that
  will not emit audio until a whole sentence is synthesised destroys the
  metric in §5.1 no matter how good the rest is.

**Check the cv2 conflict.** Document Memory's OCR choice was decided by a
`pip install --dry-run` showing that one candidate would install
`opencv-python` alongside this project's `opencv-python-headless`. Run
the same dry-run for every audio candidate before installing anything.

---

## 7. What must not be assumed

- **That DAT exposes microphone audio at all**, or at what quality, or
  with what latency. Rule 4: query current Meta documentation before
  designing against it. Limitation 13 says this is unestablished.
- **That the Bluetooth speaker path is low-latency.** Bluetooth audio
  output adds latency that can dwarf the entire Tower pipeline, and it is
  outside the Tower's control. Measure it separately and early; it may
  reframe the whole budget.
- **That a conversation is two people taking clean turns.**
- **That the glasses can indicate to a bystander that they are being
  recorded and translated.** That is a privacy question this plan does
  not answer, and `06-PRIVACY-DATA.md`'s Real-World Capture rules apply
  with more force to audio than to video in many jurisdictions.

---

## 8. Privacy, stated now rather than later

Conversational audio is at least as sensitive as document text, and it
carries **other people's** speech by default — the wearer cannot consent
on their behalf.

- Local-first is not optional here. A cloud translation API would send a
  bystander's voice to a third party, which `06-PRIVACY-DATA.md` treats
  as an explicit, documented, opt-in exception and never a default.
- Persist nothing by default. A translator needs a rolling in-memory
  buffer, not a transcript store. If a transcript is ever kept, it is a
  separate feature with its own retention, purge and justification.
- No speaker identification. The same rule that keeps Document Memory and
  Scene Understanding away from identity applies to voices.

---

## 9. Sequencing gate

Do not begin Ray-Ban microphone, iPhone or Bluetooth speaker integration
until **all** of these hold:

1. A microphone is verified present and working on the Tower (§2).
2. All four candidates have run against the same evaluation set.
3. End-to-end latency is measured by loopback (§5.2), not by summation.
4. p50 **and** p95 are recorded for the winner.
5. The failure modes in §5.4 are documented, including what the pipeline
   does when it did not understand.
6. A winner is chosen **on the measurements**, with the rejected options
   and their numbers recorded — the same way the OCR and optical-flow
   decisions were.

Only then does the question "can DAT give us this audio?" become worth
the effort of answering.
