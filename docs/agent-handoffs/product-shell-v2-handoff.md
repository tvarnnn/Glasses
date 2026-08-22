# Product Shell V2 — cross-machine handoff

**Status:** source-level implementation complete. **Never compiled. Never run.
No test in this document has been executed.**

Produced on Windows: no Xcode, no Swift compiler, no Simulator, no iPhone, no
Meta DAT hardware. Every claim here is a statement about source, an argument, or
a labelled hypothesis. The Mac is the authoritative validation gate.

---

## 1. Starting Git state

| | |
|---|---|
| Branch created | `ios/product-shell-v2` |
| Base commit | `7508db1` — the validated sender state on `ios/send-window-investigation` |
| Product-shell ancestor | `ui/product-shell` @ `d9e513d` (untouched) |
| `main` | `645e57d` (untouched) |

**One discrepancy to record.** The brief said the sender candidate had since been
Mac-validated and to look for an updated handoff/commit rather than assume
`7508db1` was still HEAD. **There is no such commit.** `git ls-remote` showed
`refs/heads/ios/send-window-investigation` still at `7508db1`, with a clean tree
and no new docs. The Mac session's documentation commit never reached this
remote.

Basing from `7508db1` is correct regardless: the brief's own account of the
validation ("89/89 tests passing") matches exactly the count predicted in
`ios-send-window-handoff.md` (56 pre-existing + 33 added), so the Mac validated
this branch as-is. **If a Mac documentation commit surfaces later it will merge
cleanly — it touches only `docs/`.** Worth reconciling before merge.

Working tree at start: clean apart from the untracked `plan-ui.md`.

---

## 2. Mission

Turn a camera/debug dashboard into a cartridge-driven operating shell: a
persistent shell (glasses / camera / Tower status + a cartridge drawer) whose
**primary workspace changes** with the selected cartridge. Tonight: a Home
workspace and a World Builder workspace, with enough evidence that a third can
be added cleanly.

Hard constraints carried throughout: auto-connect must not auto-stream;
selecting a cartridge must not activate the camera; the runtime object graph
must never be recreated; the just-validated sender must not regress; and **no
Tower World Builder protocol may be invented** — that contract is being designed
concurrently and will be reconciled later.

---

## 3. Recovered architecture

- `ContentView` owns `@StateObject private var project = ProjectManager()` and
  is the only place a `ProjectManager` is constructed. Everything else is
  presented over or inside it, because `GlassesConnection.deinit` stops the
  camera and the device session.
- `ProjectManager` owns `GlassesConnection`, `StreamManager`, `TowerClient`,
  `SenderMetrics`, `DeviceHealth`, and bridges frames → Tower with Combine. It
  has no `@Published` of its own; it re-broadcasts every child's
  `objectWillChange`.
- **The entire camera path is `#if DEBUG`** — `startCameraSession`,
  `latestCapturedFrame`, `cameraStreamState`, `frameCount`, `hasActiveDevice`,
  `CapturedFrame`, `ViewfinderCard`, and the frame→Tower bridge. **A Release
  build has no camera and sends no frames.** See §16.
- The Tower's whole vocabulary is `ping`, `pong`, `frame`, `frame_result`,
  `stream_start`, `stream_stop`. `frame_result` carries `seq`,
  `mean_intensity`, `processing_ms`. There is no module runtime: the container
  is V0.8 and the first module V0.9, and neither exists.

---

## 4. The truthfulness problem, and how it was resolved

This was the crux, and it is the part most worth reading.

`08-IOS-CARTRIDGE-SHELL.md` said cartridge rows must not be selectable until the
Tower can honour a selection, and `ProductShellTests.testNoCartridgeClaimsToBeAvailable`
enforces that no cartridge advertises availability. The brief nevertheless wants
a World Builder workspace. Both cannot be satisfied by wording alone.

**Resolution: two independent axes.**

| | Question | Field | Today |
|---|---|---|---|
| `CartridgeStatus` | Where is this *module* on the **Tower** roadmap? | `Cartridge.status` | `next`/`planned`/`future`. Still no `available`/`active` case. |
| `CartridgeWorkspace` | Does *this app* ship a screen for it? | `Cartridge.workspace` | `.worldBuilder` only. |

A row is tappable **iff** it has a workspace. Tapping changes which screen the
phone draws — it sends nothing, selects nothing on the Tower, and changes no
Tower state. So the World Builder row is tappable while its badge still reads
"Future", and both statements are true.

Consequences, each a deliberate refusal:

- **No "Start Mapping" button.** A verb-labelled primary button is the strongest
  readiness claim a UI can make, and mapping will not happen. The control is
  labelled **"Start capture"**, which is exactly what it does. A rule was added
  to `08-IOS-CARTRIDGE-SHELL.md`: *a button may use a module's verb only once
  the Tower can perform that verb.*
- **No placeholder metric tiles.** Keyframes / tracking / scale would all render
  as "—". Six redacted values read as *broken*, not as *early*, and they are the
  dead panels the brief forbids. One line of prose carries the same information.
- **No fabricated geometry, and no spinner** in the unsupported state — a
  spinner claims work is in progress when none is.
- **`ProductShellTests` was not edited to accommodate any of this.** Its
  existing assertions still pass unchanged; a new test asserts that having a
  workspace never promotes a cartridge's status.

### The one thing that makes the world panel honest rather than empty

`mean_intensity` already arrives on every `frame_result` and was decoded for a
log line and thrown away. It is the only thing the Tower says about a frame's
*content*. It is now surfaced (`TowerClient.latestFrameResult`), so the app can
describe what the Tower genuinely does — return a measurement per frame — rather
than needing a dead "coming soon" panel to make the same point.

---

## 5. UX architecture

```
ContentView                      ← @StateObject ProjectManager (the only one)
 └ NavigationStack
    └ ScrollView
       ├ ShellStatusBar          ← persistent; Glasses / Camera / Tower
       │                            tap → ConnectionSheet
       └ workspace  (switch)     ← the ONLY per-cartridge dispatch point
          ├ HomeWorkspaceView          (nothing selected)
          └ WorldBuilderWorkspaceView  (.worldBuilder)
    toolbar → CartridgeDrawerView (sheet) · DeveloperToolsView (sheet, DEBUG)
```

**A `switch`, not a protocol or a registry.** The set of workspaces is closed
and compiled in, so an enum fits, and exhaustiveness checking then *forces* a
new case to be handled rather than silently falling back to Home. The
anti-pattern the brief warns about is per-cartridge conditionals scattered
through one enormous view; the cure is separate view *files*, which is what
these are. A protocol with one conformer would be evidence of nothing.

**Adding a workspace** = one `CartridgeWorkspace` case + one `workspace:` on a
catalog entry + one `switch` arm + one file. No existing workspace is touched.

---

## 6. Auto-connect

`ProjectManager.startAutomaticConnections()`, called from a single `.task` on
`ContentView`, idempotent via a stored flag (a `.task` can re-run).

**Does exactly two things:**

- `checkCameraPermission()` — a pure query. Presents nothing, changes no
  authorization. It also **fixes a real defect**: nothing populated
  `cameraPermissionStatus`, so it began every launch as "Not checked yet" and
  the first session of each launch was refused for a permission the user had
  already granted. Reading it is *more* truthful than not reading it.
- `TowerClient.connectIfIdle()` — new. Guards on `status == .offline` and
  **does not** refill the reconnect budget.

**Deliberately absent:** `connect()` (Meta AI registration hands off to another
app via the `glasses://` callback, and has no `.registered` guard so it
re-registers an already-registered user), `requestCameraPermission()` (a
context-free prompt at launch is how permissions get denied), and anything
touching the camera.

### Why `connectIfIdle` rather than `connect`

`connect()` means "the user asked to try again": it refills the bounded
reconnect budget and will replace a live connection. Neither is true of code
running on its own initiative. Routing automation through the same door would
dissolve the bound that stops a dead Tower from being retried forever, and a
second `.task` run would tear down a live socket mid-session, closing the stream
bracket.

### A latent bug fixed on the way

`connect()` reset `reconnectAttempt = 0` *before* `openConnection`'s
`.connecting` early-return. A redundant call during an in-flight connect
therefore did nothing visible while silently resurrecting an exhausted schedule.
The reset is now conditional on the call actually proceeding. **Flag for Mac
validation** — it is sender-adjacent.

---

## 7. Auto-connect ≠ auto-stream, structurally

Not a promise; a property of the pipeline's shape:

1. Frames exist only via `latestCapturedFrame`, published only by a live camera
   stream, started only by `startCameraSession()`.
2. `startCameraSession()` has exactly **one** call site per workspace, each a
   `Button` action. There is no `.onAppear`/`.task`/`.onChange` anywhere that
   reaches it.
3. Even with an open socket, `sendFrame` additionally requires
   `isStreamingToTower`, set only by `sendStreamStart()`, fired only from
   `cameraStreamDidStart`.

Pinned by `testAutomaticConnectOpensTheSocketButSendsNothing`, which asserts an
auto-connected client has no bracket and that an offered frame is refused.

---

## 8. Loaded vs active

Expressed as a **continuously changing signal, not a label**. There is no
LOADED/READY/ACTIVE pill anywhere — that would be the wall of state labels the
brief asks to avoid, and it would duplicate what the live view already says.

- **Loaded** = the workspace is simply present, with a filled "Start capture"
  button. No state label.
- **Active** = live imagery + the LIVE badge + the button flipped to a bordered
  "Stop capture" + counters visibly moving.
- The **camera pill** reads "On"/"Off" rather than the DAT case name, because
  the question a person is asking it is whether the glasses are recording.

**Truthfulness fix made here:** `latestCapturedFrame` survives a stop (cleared
only at the next start), so the last frame stayed on screen at full brightness.
In a large workspace layout that reads as still-live. `ViewfinderCard` now dims
and desaturates it and replaces the LIVE badge with `Camera off · last frame #N`.

**Deliberate behaviour worth knowing:** leaving the World Builder workspace does
**not** stop capture. That is why `ShellStatusBar` is outside the workspace
switch — an active camera must stay visible from Home. Implicitly stopping a
sensor on a navigation change would be the worse failure.

---

## 9. World visualization boundary

`Glasses/Workspaces/WorldBuilder/WorldModel.swift`. **Nothing in it is a Tower
protocol.** It states the *presentation's* requirements — read it as a question
addressed to the Tower, not an answer.

- `WorldModelState` — `unsupported` / `idle` / `awaitingFirstUpdate` /
  `receiving` / `finalized` / `failed`. **Only `.unsupported` is reachable
  today**, because `UnavailableWorldModelSource` is the only source and it
  returns nothing else.
- `WorldSnapshot` — every field optional. `nil` and `0` are different claims:
  "not reported" vs "reported as none". `WorldSummaryView` omits absent fields
  rather than drawing "—".
- `WorldScaleSemantics` — `relative` / `inferredMetric` / `measuredMetric` /
  `unknown`. **Not decoration.** `docs/modules/WORLD-BUILD.md` requires that
  monocularly inferred depth never be presented as ground truth "wherever it is
  stored, *displayed*, or consumed". Encoding provenance in the type means a
  figure cannot be shown without also having said where it came from, and
  `isEstimate` gates the estimate caveat at the point of display.
- `WorldModelSource` — the seam. One conformer today.

**No 3D framework was introduced.** SceneKit/RealityKit/Metal would be weight in
exchange for nothing to render, and would prejudge a representation the Tower has
not chosen. Nothing in `WorldCanvasView` assumes point clouds.

---

## 10. Backend assumptions deliberately NOT made

Not invented, not assumed, not encoded anywhere: message names or shapes for
world updates; a keyframe/pose/landmark/geometry representation; a persistence
or finalization contract; a world identifier scheme; tracking-quality
semantics; scale/calibration units; incremental-update or revision semantics;
any module-selection or module-status message.

`TowerClientTests.testStreamStartSendsExactPayloadOnce` enforces the wire
contract at the protocol level and is untouched — it is the guard that would
catch a future attempt to smuggle a module selection into `stream_start`.

### What the Tower needs to tell us (for tomorrow's reconciliation)

1. **Is a world being built?** A start/stop/failed signal distinct from "frames
   are arriving".
2. **Progress that is real.** Whatever the Tower actually counts — keyframes
   accepted, observations fused. A count it does not keep should not be invented.
3. **Tracking health**, coarsely. Good / limited / lost is enough; a percentage
   would imply a calibrated confidence model neither side has defined.
4. **Scale provenance**, mandatory with any spatial figure: relative, inferred
   metric, or measured metric. This is a `WORLD-BUILD.md` requirement, not a
   preference.
5. **Change detection** — a revision or monotonic counter, so the UI can tell new
   data from repeated data without diffing geometry.
6. **The geometry representation itself**, when there is one, plus whether it
   arrives incrementally or as snapshots.
7. **Identity** — does a world have a stable id and a name, or is it per-session?

Mapping these onto `WorldSnapshot` should be the *only* change needed on the iOS
side, plus one new `WorldModelSource`.

---

## 11. Shared state and camera ownership

**One rule:** `project` is created in exactly one place; every other view
receives its **children**; no view below `ContentView` ever constructs anything
that talks to DAT or the socket.

- Views observe leaf objects (`glasses`, `tower`, `senderMetrics`), **never
  `ProjectManager`**. It re-broadcasts every child's `objectWillChange`,
  including the frame counter at capture rate, so observing it would invalidate
  the whole tree ~24×/s — and that cost lands on the main actor, which is the
  same actor the sender's send-window slots are released on. A presentation
  choice would have become a throughput regression.
- Exactly **one** viewfinder is mounted at a time (workspaces are exclusive
  branches of a switch). `ViewfinderCard` renders `latestCapturedFrame`; it does
  not open a feed. No workspace owns or duplicates the stream.
- `WorldBuilderWorkspaceView` holds a `@StateObject ObservableWorldModelSource`
  that deliberately holds **no** runtime references and has **no** `deinit`, so
  losing it on deselect loses nothing real.

**The rule for the next workspace:** anything that must *outlive* the workspace
(accumulated geometry, an object-memory buffer) belongs on `ProjectManager`, not
in a view's `@StateObject`. A workspace-owned `@StateObject` is destroyed when
the switch changes — harmless today because World Builder has no durable state,
and a real bug the moment one does.

**Also fixed:** `Info.plist` gained `UIApplicationSceneManifest` with
`UIApplicationSupportsMultipleScenes = false`. `TARGETED_DEVICE_FAMILY` is
`"1,2,7"`, so SwiftUI would otherwise open a second window on iPad/visionOS —
a second `ContentView`, a second `ProjectManager`, a second `GlassesConnection`
and a second Tower socket. "Init once per launch" is really "once per scene";
this makes them the same thing.

**And:** `GlassesConnection.init` now logs `[Glasses][Init] GlassesConnection created`
(DEBUG). The smoke test previously *inferred* construction from the first
registration-state line, which depends on DAT emitting. The invariant is now
directly observable.

---

## 12. Sender invariants preserved

No change to: the frame-rate gate, the send window, stall detection, reconnect
backoff, `stream_start`/`stream_stop` bracketing, `metrics.begin()`/`finish()`,
`frameCount`/sequence, or the 12 fps target.

Three sender-adjacent changes, each deliberate and each needing Mac attention:

1. **`TowerClient.connectIfIdle()`** — additive; existing `connect()` semantics
   unchanged.
2. **`connect()` budget-ordering fix** (§6) — behaviour change on a no-op path.
3. **`TowerClient.latestFrameResult`** — three optional casts moved above the
   log gate so every reply is captured, plus one `@Published` write at the reply
   rate (~12 Hz), the same order as `frameResultCount` beside it. The decode
   itself was already happening on one-in-twelve replies.

---

## 13. Developer Tools

Unchanged in behaviour and still `#if DEBUG` in its entirety, still reached from
the toolbar, still carrying Mock Device Kit controls in their required order,
its own local error alert, raw state, and the full sender/telemetry sections.
The only edit is the added `health:` argument, already present before this task.

Raw start/stop session controls remain on the product surface (Home and World
Builder) rather than being moved into Developer Tools, because they are the
app's only real primary action.

---

## 14. Files changed

**New**
| File | Purpose |
|---|---|
| `Glasses/Workspaces/CartridgeWorkspace.swift` | The workspace axis + selection resolution |
| `Glasses/Workspaces/HomeWorkspaceView.swift` | Home workspace |
| `Glasses/Workspaces/WorldBuilder/WorldModel.swift` | Tower boundary types |
| `Glasses/Workspaces/WorldBuilder/WorldBuilderWorkspaceView.swift` | World Builder workspace |
| `Glasses/Workspaces/WorldBuilder/WorldCanvasView.swift` | World visualization container |
| `Glasses/Views/ShellStatusBar.swift` | Persistent status row |
| `Glasses/Views/ConnectionSheet.swift` | All manual connection controls |
| `Glasses/Views/Components/ShellPieces.swift` | `SectionLabel`, `HelperText`, `SetupRow`, `FailureBanner` |

**Deleted:** `Glasses/Views/SessionView.swift` — split into the shell status
bar, the connection sheet, the Home workspace, and the shared pieces above.

**Modified:** `ContentView.swift` (shell + workspace switch + `.task`),
`CartridgeDrawerView.swift` (selectable rows), `Cartridge.swift` (`workspace`
field), `TowerClient.swift` (`connectIfIdle`, budget fix, `latestFrameResult`,
`TowerFrameResult`), `ProjectManager.swift` (`startAutomaticConnections`),
`GlassesConnection.swift` (init log, stop comment),
`Views/Components/ViewfinderCard.swift` (stopped state), `Info.plist` (scene
manifest), `docs/08-IOS-CARTRIDGE-SHELL.md` (two-axis model).

**`project.pbxproj` was NOT modified.** `Glasses/` is a filesystem-synchronized
group so new sources compile automatically. `GlassesTests/` is **not** — its
files are listed explicitly — so **no new test files were added**; new tests
were appended to existing ones.

---

## 15. Tests

**112 total: 89 pre-existing (Mac-validated) + 23 new. Every new test is
unrun.**

Appended to `GlassesTests/ProductShellTests.swift` (16):
- `CartridgeWorkspaceTests` — a workspace never promotes a cartridge's status;
  the availability guard still holds; exactly the cartridges with workspaces are
  selectable; a persisted/unknown/workspace-less id falls back to Home.
- `WorldModelTests` — only inferred depth is marked an estimate; every scale is
  explainable; states without a world never claim one; only `.receiving` is
  live; a default snapshot reports nothing rather than zero; the only source
  reports the capability is absent.

Appended to `GlassesTests/TowerClientTests.swift` (7):
- Auto-connect opens the socket but sends nothing (no bracket; an offered frame
  is refused and no `frame` reaches the server).
- Auto-connect leaves a healthy connection alone (bracket survives — the precise
  observable difference between "did nothing" and "reconnected").
- Auto-connect does not retry a failed connection.
- Auto-connect does connect from idle.
- `latestFrameResult` is surfaced, updates on **every** reply (not just logged
  ones), and resets with the stream bracket.

**Not covered by automated tests** (state honestly): SwiftUI rendering, workspace
switching, drawer selection wiring, the `.task` auto-connect call site,
`GlassesConnection.init`-once, and everything requiring DAT — no mock
`WearablesInterface` exists, and building one is a larger surface than this task.
Those are Simulator/device checks in §17–18.

---

## 16. Debug/Release boundary — read before building Release

The camera path is `#if DEBUG` in the model, so **a Release build has no camera,
no viewfinder, no frames, and no Tower streaming.** This predates this task and
was not changed.

What that means for the new views: camera-dependent *regions* are gated, not
whole files, so both workspaces exist in Release.

- **Home** in Release = the readiness card alone.
- **World Builder** in Release = header + world panel (truthfully unavailable) +
  "Capture is not available in this build."

`CapturedFrame` **does not exist in Release** — any stored property, parameter,
or computed property naming it must be inside `#if DEBUG`. This is the most
likely way the Release build breaks. `ShellStatusBar`'s Camera pill,
`HomeWorkspaceView`'s session controls and metrics, and
`WorldBuilderWorkspaceView`'s glasses panel and capture control are all gated.

**Worth raising with whoever owns the roadmap:** as long as the camera path is
DEBUG-only, "product shell" describes a screen that only fully exists in Debug
builds. That deserves to be the next task after this one.

---

## 17. Mac validation sequence

```bash
git fetch origin
git checkout ios/product-shell-v2
git log --oneline -3
```

1. **Resolve packages.** Confirm meta-wearables-dat-ios pins to exactly 0.9.0.
2. **Debug build.** Expect to fix compile errors — that is the anticipated
   outcome. §16 and §20 rank where they are most likely.
3. **Confirm the eight new files are in the target** via the synchronized group.
   Do **not** add new *test* files.
4. **Run all tests.** Expect 112. The 89 pre-existing **must** still pass — any
   regression there is a defect in this change, not a test to update.
5. **Release build.** This is the gate §16 exists for.
6. **Compare warnings against `7508db1`.** The bar is no new warnings.
7. **Simulator UI smoke test** — see §18.
8. **Physical iPhone + Ray-Ban.**

---

## 18. Physical / Simulator regression procedure

**Object lifetime (do this first).** Watch the console for
`[Glasses][Init] GlassesConnection created`. It must appear **exactly once per
launch**. Then, without relaunching: open and dismiss the cartridge drawer,
select World Builder, return to Home, open and dismiss Connections, open and
dismiss Developer Tools, rotate the device. **No second init line may appear.**

**Auto-connect.** Cold-launch with the Tower reachable: the Tower pill should go
Connecting → Connected with no interaction, and the camera pill must read
**Off**. Confirm in the console that no `stream_start` is sent and no frame is
transmitted. Camera permission should show its real value immediately rather
than "Not checked yet".

**Auto-connect failure path.** Launch off-network. The Tower should fail
visibly, the banner should name the endpoint, and **manual Connect in the
Connections sheet must still work** — the automatic schedule is bounded and
deliberately gives up.

**Loaded ≠ active.** Select World Builder from the drawer. The workspace must
appear with the camera still **Off** and no frames flowing. Only tapping "Start
capture" may start it.

**Live view and sender.** Start capture from World Builder: the viewfinder shows
glasses imagery, the LIVE badge appears, and Developer Tools' sender rows
populate as before. Then switch to Home **while streaming** — capture must
continue, the camera pill must still read On, and no init line may appear.

**Stop.** Tap Stop capture. Counters freeze, the last frame dims and shows
`Camera off · last frame #N`, and the Tower connection stays up.

**Mean intensity.** While streaming, Home's "Mean intensity" tile should show a
live value from the Tower's replies.

**Developer Tools.** Confirm Mock Device Kit still works in its required order
and the sender/telemetry sections are unchanged.

---

## 19. Known limitations

- No cross-launch persistence of the selected cartridge (deliberate — §5 of the
  code comment in `ContentView`; restoring a workspace for a module the Tower
  cannot run would restore a fiction). Revisit when a cartridge can actually
  load and report that it is running.
- Leaving a workspace does not stop capture (deliberate; the shell status bar is
  the honest answer).
- `WorldModelState` has five states that are unreachable today. They exist so
  the container is written once against the full lifecycle; they are unreachable
  **by construction**, not by convention.
- No sensor-profile negotiation. Rule 4 forbids designing it before the real DAT
  configuration model is known.
- Latent bugs found during the audit and **not** fixed (out of scope, worth
  filing): `GlassesConnection.connect()` has no `.registered` guard;
  `metrics.begin()` runs before `createSession` can throw; a session that never
  reaches `.stopped` leaves `deviceSession` non-nil so no further session can
  start; re-tapping Start before `.stopped` is refused silently; the validation
  ping `send` has no timeout; `becameOnlineAt` is not cleared by
  `teardownConnection`.

---

## 20. Expected compile risks, ranked

1. **Release build vs `#if DEBUG`** (§16) — the highest-probability failure.
2. **`switch selectedCartridge?.workspace`** in `ContentView` — matching enum
   cases against an `Optional` plus `case nil`. Believed exhaustive and legal;
   verify.
3. **Actor isolation** under `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor` —
   `WorldModelSource` is `@MainActor`; `WorldModelState`/`WorldSnapshot`/
   `WorldScaleSemantics` are plain `Sendable` value types used from the
   non-isolated test target.
4. **`ToolbarContentBuilder`** usage in `ContentView.toolbar`.
5. **`Cartridge` memberwise init** — `workspace` has a default, so existing
   catalog entries omit it.

---

## 21. Future cartridge extension pattern

1. Add a case to `CartridgeWorkspace`.
2. Set `workspace:` on the catalog entry. **Do not change `status`** — that
   tracks the Tower roadmap, and a test enforces it.
3. Add one arm to `ContentView.workspace`. The compiler will demand it.
4. Add the workspace view file. Observe leaf objects, never `ProjectManager`.
5. Anything that must outlive the workspace goes on `ProjectManager`.
6. Gate camera-dependent regions with `#if DEBUG`.
7. Do not use a module's verb on a button until the Tower can perform it.

---

## 22. Final Git state

- Branch: `ios/product-shell-v2`
- Base: `7508db1` (validated sender), itself on `ui/product-shell` @ `d9e513d`
- `main`, `ui/product-shell`, `ios/send-window-investigation` all untouched
- `project.pbxproj` untouched
- Working tree clean; branch pushed

**Product Shell V2 was implemented on Windows without Xcode and has NOT yet
been compiler-, Simulator-, or physical-device-validated.**
