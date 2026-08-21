# Mac Handoff — `source_seq` / `tx_seq` frame-protocol split

Produced by the 2026-08-20 weekend autonomous run (Windows/Tower session)
per Master Guide §24. The Tower-side half is **already implemented and
merged**; this document describes the iOS-side half, which that session
could not write (no Swift code in this repo, no DAT documentation access
from that machine).

## Objective

Make it possible to tell **intentional sender-side frame sampling** apart
from **genuine network/transit loss**. Today they are indistinguishable,
so the Tower cannot honestly report whether frames were lost in flight.

Concretely: the deployed iOS sender assigns `seq` from the DAT capture
frame index (`frameCount` of incoming `VideoFrame`s) but forwards only
roughly 1-in-30 of them, so the Tower normally receives `seq` = 1, 30, 60,
90 … **by design**. A gap in `seq` may therefore mean intentional
sampling, a sender-side drop, or real transit loss — all three look
identical on the wire. See `guidelines/docs/07-PLATFORM-CONSTRAINTS.md`
Limitation 9, which specifies this split.

## Relevant protocol

**Current `frame` message** (unchanged, still fully supported —
`tower/frames.py`, `REQUIRED_FIELDS`):

```json
{
  "type": "frame",
  "seq": 30,
  "width": 504,
  "height": 896,
  "format": "jpeg",
  "data": "<base64 JPEG>"
}
```

**What changes:** two **optional** fields are added. Nothing is removed and
nothing is renamed.

```json
{
  "type": "frame",
  "seq": 30,
  "source_seq": 30,
  "tx_seq": 2,
  "width": 504,
  "height": 896,
  "format": "jpeg",
  "data": "<base64 JPEG>"
}
```

- **`source_seq`** — the DAT/capture frame index. This is exactly what
  `seq` already carries. Sparse by design (1, 30, 60, 90 …).
- **`tx_seq`** — a **dense** counter incremented by exactly 1 for every
  frame message the iPhone actually transmits, independent of
  `source_seq`. Starts at 1 for the first frame of a connection. **Must
  never skip a value on the sender side** — that is the entire point:
  any gap the Tower observes in `tx_seq` is then attributable to transit
  loss and nothing else.

`seq` should keep being sent with its current meaning for backward
compatibility.

## Tower-side state

**Done and merged** — commit `0346c05`
("feat: accept optional source_seq/tx_seq frame fields (additive)"):

- `tower/frames.py` — `DecodedFrame` gained `source_seq` (falls back to
  `seq` when absent) and `tx_seq` (`None` when absent). `REQUIRED_FIELDS`
  is unchanged, so **an unmodified iOS client keeps working with no
  behavior change at all.**
- `tower/metrics.py` — `SessionMetrics` gained `tx_seq_gap_total`,
  counted only from frames that actually carry `tx_seq`.
- `tower/routes/ws.py` — passes `frame.tx_seq` into metrics.
- `tests/test_frames_seq_split.py` — 6 tests covering legacy messages,
  both new fields, and the sparse-source_seq/dense-tx_seq case.

**One Tower-side behavior worth knowing about:** when the sender does not
send `tx_seq`, the Tower reports `tx_seq_gap_total: null`, **not `0`**.
Zero would falsely assert "no transit loss observed"; null correctly says
"cannot determine" (`02-DEVELOPMENT-RULES.md` Rule 3 — unknown values
remain unavailable). Once the iPhone sends `tx_seq`, this becomes a real
number.

## Tower expectations

Once the iOS side is updated, per connection:

- `tx_seq` starts at 1 and increments by exactly 1 per transmitted frame
  message, monotonically, never reset mid-connection.
- A **new WebSocket connection restarts `tx_seq` at 1.** The Tower builds
  a fresh `SessionMetrics` per connection and never carries counters
  across a reconnect (a new session is a new observation stream —
  Limitation 4), so this is correct, not a problem.
- `source_seq` stays sparse; the Tower will keep reporting
  `seq_gap_total` for it and will **not** treat those gaps as loss.
- Interpretation the Tower will then support:
  `tx_seq_gap_total == 0` → nothing lost in transit;
  `tx_seq_gap_total > 0` → that many frame messages were sent by the phone
  and never arrived.

## Files/components likely involved (Swift side)

**This is a best-effort guess from `guidelines/docs/05-DAT-INTEGRATION.md`'s
documented architecture, NOT verified against actual Swift source** — the
Windows session that wrote this cannot read the iOS repository.

- **`StreamManager`** (or whichever type owns the capture→transmit
  throttle) — most likely home for the `tx_seq` counter, since it is the
  component that decides which captured frames actually get sent.
- **`TowerClient`** — builds the JSON frame message; needs the two new
  keys added.
- Wherever `frameCount` from the incoming `VideoFrame` is currently read
  to populate `seq` — that same value populates `source_seq`.
- The counter must reset when a new Tower WebSocket connection is
  established.

## DAT documentation needed

**Probably not required for this change specifically** — `tx_seq` is
purely an app-side counter, and `source_seq` reuses a value the app
already reads.

⚠️ **However:** `search_dat_docs` was **not available** in the Windows
session that wrote this, so the claim "the deployed sender uses
`frameCount` and forwards ~1-in-30" is carried from
`07-PLATFORM-CONSTRAINTS.md`'s 2026-08-19 finding, **not re-verified**.
Confirm against the actual current Swift source before implementing, per
`02-DEVELOPMENT-RULES.md` Rule 4.

**Genuinely open and worth resolving while you are in here** (Limitation
9's "Unresolved Questions"): whether `VideoFrame.sampleBuffer`'s
presentation timestamp reflects **on-glasses capture time** or **phone-side
arrival time**. That is unconfirmed in available DAT docs and needs either
a specific `search_dat_docs` answer or empirical measurement. It is not
required for this change, but it is the next thing that blocks honest
temporal reasoning, and you will be in the right code to answer it.

## Acceptance criteria

1. Every transmitted frame message includes `source_seq` and `tx_seq`.
2. `tx_seq` is dense: no gaps introduced by the sender under any
   condition, including when the throttle drops a captured frame.
3. `tx_seq` restarts at 1 on each new Tower connection.
4. `seq` continues to be sent unchanged (backward compatibility).
5. With a healthy local network, a soak run reports
   `tx_seq_gap_total: 0` while `seq_gap_total` is large — this is the
   single clearest proof the split works.

## Tests / manual validation required

**Already verified Tower-side** (no Mac needed, already passing):
- Legacy messages without the new fields parse unchanged.
- `source_seq` falls back to `seq`; `tx_seq` is `None` when absent.
- `tx_seq_gap_total` is `null` without `tx_seq`, a real count with it.
- Sparse `source_seq` + dense `tx_seq` reports `seq_gap_total: 86`,
  `tx_seq_gap_total: 0` — sampling correctly not counted as loss.

**Mac session must verify:**
- Unit-test the `tx_seq` counter, especially that a throttled/skipped
  capture does **not** advance it.
- Run `scripts/soak_test_stream.py`-equivalent traffic from the real app
  and confirm the Tower's `[Tower][Session] final summary` line shows
  `tx_seq_gap_total: 0` on a healthy link.
- Confirm reconnect resets the counter and the Tower does not report a
  spurious gap on the new session.
- Optionally, force loss (airplane-mode blip mid-stream) and confirm
  `tx_seq_gap_total` becomes non-zero — the first real transit-loss
  measurement this platform will ever have taken.

## Follow-up (not blocking this change)

Once `tx_seq` is live, `SessionMetrics`'s class docstring in
`tower/metrics.py` should be updated: it currently states the split is
"not implemented as of V0.7", which will no longer be true Tower-side once
a real sender exercises it. Left as-is deliberately for now, since the
Tower half alone does not make the capability real.
