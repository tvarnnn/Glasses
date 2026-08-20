# Glasses Tower

The Windows tower transport layer for the Glasses platform. Current
milestone: V0.9.1 — Module System + Experimental CV Lab Baseline. The tower
exposes a persistent runtime with a module container that supports stateful,
model-backed computer vision experiments. The core transport layer (WebSocket
health check, frame receive, JPEG validation, per-session measurements) is
fully decoupled from module implementations; modules register CV experiments
and handle frame processing. The `baseline` experiment runs deterministic
OpenCV (grayscale + mean intensity), while the `depth` experiment uses
MiDaS-small monocular depth estimation on GPU/CPU. Both log per-session
streaming measurements (FPS, bandwidth, sequence-gap count, Tower-side drops,
processing latency, CPU/RSS), plus per-stage timing for module operations.
Frames are processed in memory only and never written to disk.

## Environment Setup

Requires Python 3.12.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

## Installing Dependencies

```powershell
pip install -e ".[dev]"
```

This installs FastAPI, Uvicorn, Pillow, OpenCV (headless), NumPy, psutil,
and the test dependencies (pytest, httpx, websockets).

## Model-Backed Experiments (Optional)

The `depth` experiment (`TOWER_CV_EXPERIMENT=depth`) requires the `ml`
extra, which includes PyTorch, torchvision, and timm (needed by MiDaS's
hubconf backbone chain):

```powershell
pip install -e ".[dev,ml]"
```

### PyTorch/CUDA Installation

On this Windows machine with CUDA 13.2 support, the verified working install
command is:

```powershell
.venv\Scripts\pip.exe install torch torchvision --index-url https://download.pytorch.org/whl/cu132
```

This uses the `cu132` index, which is the newest stable PyTorch build matching
the driver-reported CUDA 13.2 support. (Other indexes like `cu128` or `cu129`
may be stale.) This command installs as part of the broader `pip install -e
".[dev,ml]"` workflow above.

### MAX_PATH Warning (Windows)

A plain `pip install` of torch/torchvision from a path this deep (e.g., a git
worktree in `C:\Users\tvllo\Projects\...`) can fail with:

```
OSError: [WinError 206] The filename or extension is too long
```

This is Windows' MAX_PATH (260 character) limit, tripped by torch's
deeply-nested bundled third-party license file tree. **Do not attempt to
enable Windows' global `LongPathsEnabled` registry setting** as an ad-hoc fix
(it's a machine-wide policy change outside a normal install's scope). Instead,
extract the wheel manually to the target site-packages directory using the
`\\?\` Win32 extended-length path prefix, which bypasses MAX_PATH for file
APIs without requiring a registry change (always supported by NTFS/Win32).

### MiDaS-small Weight Downloads

The first time the `depth` experiment loads, it downloads MiDaS-small's weights
(and a nested `rwightman/gen-efficientnet-pytorch` backbone) via `torch.hub`
— this requires internet access once. Results are cached afterward
(`~/.cache/torch/hub`) and no further downloads occur on subsequent loads.

## Running the Tests

```powershell
pytest
```

## Starting the Server

```powershell
python -m uvicorn tower.main:app --host 0.0.0.0 --port 8000
```

Configuration is read from environment variables (all optional):

| Variable          | Default   | Purpose                                   |
|-------------------|-----------|--------------------------------------------|
| `TOWER_HOST`       | `0.0.0.0` | Interface to bind to                       |
| `TOWER_PORT`       | `8000`    | Port to listen on                          |
| `TOWER_DEV_MODE`   | `true`    | Enables debug-level logging                |
| `TOWER_CV_EXPERIMENT` | `baseline` | Active CV experiment (`baseline` or `edge_detection` or `depth`) |
| `TOWER_CV_DEVICE`   | `auto`    | Device for model-backed experiments (`auto`, `cpu`, or `cuda`) |

The server binds to `0.0.0.0` by default so it is reachable from other
devices on the LAN, not just `localhost`.

## LAN Access

For the iPhone to reach the tower, it needs the Windows machine's LAN IP
address.

Find it with:

```powershell
ipconfig
```

Look for the `IPv4 Address` under your active network adapter (Wi-Fi or
Ethernet), e.g. `192.168.1.42`.

The iPhone app should then address the tower as:

- Health check: `http://192.168.1.42:8000/health`
- WebSocket: `ws://192.168.1.42:8000/ws`

Both devices must be on the same LAN for this to work. This service is
**LAN-only for this milestone** — it must not be exposed to the public
internet, and no authentication is implemented yet.

### Firewall

Windows Firewall will likely block inbound connections to the tower by
default. This project does **not** modify firewall rules automatically.

If the iPhone cannot reach the tower, add an inbound rule allowing TCP
traffic on the configured port (default `8000`) for the Private network
profile:

```powershell
New-NetFirewallRule -DisplayName "Glasses Tower Dev" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
```

Run this yourself after reviewing it — do not run firewall changes as part
of an automated script without understanding what it opens.

## Testing the Health Endpoint

With the server running:

```powershell
curl http://127.0.0.1:8000/health
```

Expected output:

```json
{"status":"ok","service":"glasses-tower","version":"0.1.0"}
```

## Testing the WebSocket

Install the `websockets` package in the venv (`pip install websockets`),
then run a small test script:

```python
import asyncio
import json
import websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:8000/ws") as ws:
        await ws.send(json.dumps({"type": "ping"}))
        print(await ws.recv())

asyncio.run(main())
```

Expected output:

```text
{"type":"pong"}
```

## Testing a Camera Frame

Send a `frame` message with base64-encoded JPEG data and matching
`width`/`height`:

```python
import asyncio
import base64
import json
import websockets

async def main():
    with open("test.jpg", "rb") as f:
        payload = base64.b64encode(f.read()).decode("ascii")

    async with websockets.connect("ws://127.0.0.1:8000/ws") as ws:
        await ws.send(json.dumps({
            "type": "frame",
            "seq": 1,
            "width": 480,   # must match the actual JPEG dimensions
            "height": 640,
            "format": "jpeg",
            "data": payload,
        }))
        print(await ws.recv())

asyncio.run(main())
```

Expected output (values vary by image):

```text
{"type":"frame_result","seq":1,"mean_intensity":130.0,"processing_ms":4.1}
```

The tower's own log output during this should show:

```text
[Tower][Frame] #1 received: <N> bytes
[Tower][Frame] #1 decoded: 480x640
[Tower][Frame] #1 verified
[Tower][Frame] #1 processed: mean_intensity=130.00
```

## Stream Lifecycle Control Messages (V0.7)

The WebSocket connection is persistent — it stays open across the phone's
own "Start Camera Session" / "Stop Camera Session" actions, and normally
across many such cycles, so the tower needs an explicit signal for when a
streaming *measurement window* begins and ends, separate from the
connection's own lifetime. Two control messages exist for this:

```json
{"type": "stream_start"}
```
Send once, right before the app begins forwarding `frame` messages for a
streaming session.

```json
{"type": "stream_stop"}
```
Send once, when the camera session/stream stops — no more `frame`
messages should follow until the next `stream_start`.

Neither message gets a reply (unlike `ping`→`pong` or `frame`→
`frame_result`) — don't wait on a response for either.

Behavior:
- `frame` messages are always fully processed and get a `frame_result`
  regardless of whether a stream measurement window is currently open —
  `stream_start` is not required for basic frame processing to work.
- Frames received before any `stream_start` (or after a `stream_stop`)
  are processed and acknowledged normally, but are not counted in any
  measurement window.
- `stream_stop` with no window open logs a warning and is otherwise a
  no-op — the connection stays fully usable.
- A `stream_start` received while a window is already open finalizes the
  existing window first (`end_reason: "superseded_by_stream_start"`),
  then opens a fresh one — no measurement data is silently dropped.
- Multiple `stream_start` → frames → `stream_stop` cycles work on one
  persistent connection.

## Measuring a Sustained Session (V0.7)

The tower logs a `[Tower][Session] summary: {...}` line periodically
within an open streaming window (every 150 frames by default) and a
`[Tower][Session] final summary: {...}` line whenever that window closes
— on `stream_stop`, on a `stream_start` that supersedes it, or on
disconnect while it's still open (see Stream Lifecycle Control Messages
above). **A summary is only produced for frames sent between a
`stream_start` and its corresponding close** — frames sent outside any
window are still processed and acknowledged, but don't contribute to any
summary. Each final summary includes an `end_reason` (`"stream_stop"`,
`"superseded_by_stream_start"`, or `"disconnect"`) alongside effective
FPS, bandwidth, `seq_gap_total`, Tower-side backpressure drops, Tower
processing latency, and process CPU/RSS for that window — never raw
frame data.

**`seq_gap_total` is a raw, causally-neutral count — not a "frames lost"
figure.** The iOS sender currently assigns `seq` from the DAT/source
capture-frame index and only forwards roughly 1-in-30 of them by design
(a throttled capture -> transmit branch), so the tower normally receives
`seq` like 1, 30, 60, 90, ... under completely normal operation. Under
the current wire protocol there is no separate transmission-attempt
counter, so a gap in `seq` cannot currently be attributed to intentional
sender-side sampling, a sender-side drop, or genuine network/transit
loss — they look identical on the wire. Do not interpret `seq_gap_total`
as network loss. See `guidelines/docs/07-PLATFORM-CONSTRAINTS.md`
Limitation 9 for the future `source_seq`/`tx_seq` protocol split that
would be needed to actually distinguish these causes (not implemented).

For local validation without the iPhone, run the soak-test script against
a running tower:

```powershell
python scripts/soak_test_stream.py --source synthetic-script --duration-s 60
```

Use `--duration-s 1200` (20 minutes) to `1800` (30 minutes) for the full
roadmap target session length, and `--source mock-device-kit` /
`--source iphone-camera` / `--source physical-glasses` when the frames
actually come from those sources via the iOS app, so the resulting report
is never mislabeled. See `guidelines/docs/reports/V0.7-sustained-streaming-report.md`
for the report template — fill it in using this script's printed output
combined with the Tower's own `[Tower][Session] final summary` log line.

A `synthetic-script` or `mock-device-kit` run validates the Tower's
instrumentation and connection stability only; it does not establish
real-world V0.7 figures — see `07-PLATFORM-CONSTRAINTS.md` Limitation 12.

## Project Structure

```text
tower/
  main.py               FastAPI app factory + ASGI entrypoint
  config.py              Environment-based settings (host/port/dev mode)
  logging_config.py      Structured logging setup
  session.py             Minimal single-client connection tracking
  frames.py               Frame message validation/decoding (transport-level)
  frame_processing.py     Minimal deterministic OpenCV operation on decoded pixels
  metrics.py               Per-connection sustained-streaming measurements
  routes/
    health.py             GET /health
    ws.py                  WebSocket /ws (ping/pong, frame receive + processing)
scripts/
  soak_test_stream.py     Local sustained-load soak-test client (V0.7)
tests/
  test_health.py
  test_ws.py
  test_ws_frames.py
  test_frame_processing.py
  test_metrics.py
  test_ws_sustained.py
  test_soak_script_cli.py
```

`frame_processing.py` contains the only OpenCV usage in the codebase. There
is no module system, module lifecycle, or CV experiment framework yet —
that is future roadmap scope. `frames.py`/`routes/ws.py` remain transport
infrastructure; frame pixel processing is isolated to a single file so it
can be lifted behind a proper module boundary later without a rewrite.
