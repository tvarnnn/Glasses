#Requires -Version 5.1
<#
.SYNOPSIS
    Idempotent bring-up of the Glasses Tower development environment.

.DESCRIPTION
    Everything a fresh (or half-broken) checkout needs before
    scripts/start_tower.ps1 can work, in dependency order, with an
    actionable fix printed on every failure.

    Idempotent by construction: it creates the venv only if missing, never
    overwrites .env, never deletes anything, and never mutates the
    firewall. Safe to re-run as a health check.

    Deliberately NOT done here:
      * installing the ml/ocr extras (the CUDA wheel ordering hazard in
        README.md makes an unattended install actively harmful)
      * adding a firewall rule (README.md forbids automating it)
      * GPU/OpenCV diagnostics (scripts/world_builder_env_check.py owns
        those -- this script points at it rather than reimplementing it)

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_tower.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

# The tower root, not scripts/. tower/world_builder/redaction.py resolves
# DEFAULT_MODEL_PATH ("models/face_detection_yunet_2023mar.onnx") relative to
# the process CWD, so anything run from elsewhere silently loses face
# redaction. Every step below assumes this location.
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

$venvDir    = Join-Path $root '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$venvCfg    = Join-Path $venvDir 'pyvenv.cfg'
$envFile    = Join-Path $root '.env'
$dataDir    = Join-Path $root 'data'
$yunetModel = Join-Path $root 'models\face_detection_yunet_2023mar.onnx'

$script:Failures = 0
$script:Notes = 0

function Write-Step {
    param([string]$Text)
    Write-Host ''
    Write-Host "== $Text" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Text)
    Write-Host "   ok    $Text" -ForegroundColor Green
}

function Write-Detail {
    param([string]$Text)
    Write-Host "         $Text" -ForegroundColor DarkGray
}

function Write-Note {
    param([string]$Text)
    Write-Host "   note  $Text" -ForegroundColor Yellow
    $script:Notes++
}

function Write-Fail {
    param([string]$Text, [string[]]$Fix)
    Write-Host "   FAIL  $Text" -ForegroundColor Red
    foreach ($line in $Fix) {
        Write-Host "         fix: $line" -ForegroundColor Red
    }
    $script:Failures++
}

Write-Host 'Glasses Tower setup' -ForegroundColor White
Write-Host "root: $root"

# ---------------------------------------------------------------------------
Write-Step '1/12  Python 3.12 launcher'
# ---------------------------------------------------------------------------
$py312Version = $null
if (Get-Command -Name 'py' -ErrorAction SilentlyContinue) {
    $global:LASTEXITCODE = 0
    try { $py312Version = (& py -3.12 --version) } catch { $py312Version = $null }
    if ($LASTEXITCODE -ne 0) { $py312Version = $null }
}
if ($py312Version) {
    Write-Ok "py -3.12 -> $py312Version"
    Write-Detail 'The -3.12 pin is not decoration: the bare launcher on this machine'
    Write-Detail 'resolves to Python 3.14, which would build a venv the project does'
    Write-Detail 'not support, and the failure would surface much later as import errors.'
} else {
    Write-Fail 'No Python 3.12 available through the py launcher.' @(
        'Install Python 3.12 from python.org; the py launcher then finds it.',
        'Then re-run this script. Do NOT drop the -3.12 pin as a workaround --',
        'the unpinned launcher resolves to Python 3.14 here, and a 3.14 venv is',
        'exactly the trap this pin exists to avoid.'
    )
}

# ---------------------------------------------------------------------------
Write-Step '2/12  Virtual environment (.venv)'
# ---------------------------------------------------------------------------
if (Test-Path -LiteralPath $venvPython) {
    $cfgVersion = $null
    if (Test-Path -LiteralPath $venvCfg) {
        $versionLine = Select-String -LiteralPath $venvCfg -Pattern '^\s*version\s*=\s*(.+)$' |
            Select-Object -First 1
        if ($versionLine) { $cfgVersion = $versionLine.Matches[0].Groups[1].Value.Trim() }
    }
    if (-not $cfgVersion) {
        Write-Note "Could not read a version out of $venvCfg; leaving the venv alone."
    } elseif ($cfgVersion -like '3.12.*') {
        Write-Ok ".venv already exists (Python $cfgVersion) -- left untouched."
    } else {
        Write-Fail "The existing .venv is Python $cfgVersion, not 3.12.*." @(
            "Path: $venvDir",
            'This script never deletes a venv -- that is your call, not its call.',
            'Remove it yourself and re-run:',
            "    Remove-Item -Recurse -Force `"$venvDir`""
        )
    }
} elseif ($py312Version) {
    Write-Detail "> py -3.12 -m venv `"$venvDir`""
    & py -3.12 -m venv $venvDir
    if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $venvPython)) {
        Write-Ok "Created $venvDir"
    } else {
        Write-Fail 'venv creation failed.' @(
            "Check that you can write to $root, then re-run this script."
        )
    }
} else {
    Write-Fail 'Cannot create .venv without Python 3.12 (see step 1).' @(
        'Resolve step 1 first, then re-run this script.'
    )
}

$venvUsable = Test-Path -LiteralPath $venvPython

# ---------------------------------------------------------------------------
Write-Step '3/12  Install the package and its dev extra'
# ---------------------------------------------------------------------------
if ($venvUsable) {
    # Never a bare installer invocation: the interpreter is named explicitly so
    # the install cannot land in whatever venv happens to be active in this
    # shell. No activation step is needed anywhere in this script.
    Write-Detail "> `"$venvPython`" -m pip install -e `".[dev]`""
    & $venvPython -m pip install -e ".[dev]"
    if ($LASTEXITCODE -eq 0) {
        Write-Ok 'Editable install of glasses-tower[dev] completed.'
    } else {
        Write-Fail "The installer exited $LASTEXITCODE." @(
            "`"$venvPython`" -m pip install -e `".[dev]`"",
            'Read the output above -- a network failure and a build failure need',
            'different answers.'
        )
    }
} else {
    Write-Fail 'Skipped: no usable .venv (see step 2).' @('Resolve step 2, then re-run.')
}

# ---------------------------------------------------------------------------
Write-Step '4/12  Verify the install actually landed'
# ---------------------------------------------------------------------------
# This is the step that catches the state that cost an evening: a venv that
# exists and has the package installed, but never received the [dev] extra --
# so the test runner and the websocket client are simply absent, with nothing
# announcing it until something fails much later.
if ($venvUsable) {
    $required = @('pytest', 'httpx2', 'websockets', 'cv2', 'fastapi', 'uvicorn')
    $missing = @()
    foreach ($module in $required) {
        & $venvPython -c "import $module"
        if ($LASTEXITCODE -ne 0) { $missing += $module }
    }
    if ($missing.Count -eq 0) {
        Write-Ok "Importable: $($required -join ', ')"
    } else {
        Write-Fail "Not importable: $($missing -join ', ')" @(
            "`"$venvPython`" -m pip install -e `".[dev]`"",
            'httpx2 (not httpx) is the deliberate choice -- read the comment in',
            'pyproject.toml before trying to "fix" that name.'
        )
    }
} else {
    Write-Fail 'Skipped: no usable .venv (see step 2).' @('Resolve step 2, then re-run.')
}

# ---------------------------------------------------------------------------
Write-Step '5/12  Verify the ASGI app imports'
# ---------------------------------------------------------------------------
if ($venvUsable) {
    & $venvPython -c "from tower.main import app; print(app.title)"
    if ($LASTEXITCODE -eq 0) {
        Write-Ok 'tower.main:app imports cleanly.'
        Write-Detail 'That import IS the startup: tower/main.py calls create_app() at'
        Write-Detail 'module scope, and create_app() starts the module container. It is'
        Write-Detail 'also why uvicorn must never be given --factory here -- the factory'
        Write-Detail 'form would build a second container on top of this one.'
    } else {
        Write-Fail 'tower.main:app failed to import.' @(
            "`"$venvPython`" -c `"from tower.main import app`"",
            'Read the traceback above; the server cannot start until this imports.'
        )
    }
} else {
    Write-Fail 'Skipped: no usable .venv (see step 2).' @('Resolve step 2, then re-run.')
}

# ---------------------------------------------------------------------------
Write-Step '6/12  Optional extras (not installed here, on purpose)'
# ---------------------------------------------------------------------------
Write-Detail 'The ml extra (torch/torchvision/timm) powers the depth and'
Write-Detail 'object_detection experiments. The ocr extra (easyocr) powers Document'
Write-Detail 'Memory text recognition. Neither is needed for capture, World Builder,'
Write-Detail 'or the baseline experiment, so neither is installed automatically.'
Write-Note 'Install order matters, and this script will not guess it for you.'
Write-Detail 'If you want CUDA, install the CUDA-indexed wheels FIRST, extras second:'
Write-Detail '  "<venv>\Scripts\python.exe" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu132'
Write-Detail '  "<venv>\Scripts\python.exe" -m pip install -e ".[dev,ml]"'
Write-Detail 'Reversed, the resolver takes a CPU-only torch from PyPI, that wheel then'
Write-Detail 'satisfies the unconstrained requirement forever, and TOWER_CV_DEVICE=auto'
Write-Detail 'quietly runs on CPU with no error at all. See README.md, "Model-Backed'
Write-Detail 'Experiments (Optional)".'

# ---------------------------------------------------------------------------
Write-Step '7/12  .env'
# ---------------------------------------------------------------------------
if (Test-Path -LiteralPath $envFile) {
    Write-Ok "$envFile already exists -- NOT overwritten."
} else {
    $template = @(
        '# Glasses Tower development environment.',
        '#',
        '# Loaded by uvicorn --env-file (scripts/start_tower.ps1) inside',
        '# Config.__init__, which runs BEFORE the app is imported -- so these',
        '# reach get_settings() in tower/config.py.',
        '#',
        '# Gitignored. Never commit it.',
        '',
        '# tower/capture.py appends captures/<id> to this, so the root is data,',
        '# not data/captures. Unset means no recording is possible, ever.',
        'TOWER_CAPTURE_ROOT=data',
        '',
        '# tower/world_builder/store.py appends worlds/<id> to this, and it must',
        '# equal DEFAULT_ROOT in scripts/world_build_session.py -- otherwise the',
        '# result channel reads a different tree than the builder writes.',
        'TOWER_WORLD_ROOT=data/world_builder',
        '',
        '# DEBUG-level root logging. Note it does NOT control the per-frame',
        '# [Tower][Frame] lines, which are INFO and always on.',
        'TOWER_DEV_MODE=true'
    )
    # ASCII, so there is no BOM: python-dotenv reads the file as plain utf-8.
    Set-Content -LiteralPath $envFile -Value $template -Encoding ascii
    Write-Ok "Created $envFile"
}
Write-Detail '--- .env ---'
Get-Content -LiteralPath $envFile | ForEach-Object { Write-Detail "  $_" }
Write-Detail '--- end .env ---'
Write-Detail '.env is gitignored, so it is yours to edit and it will not be committed.'
Write-Detail 'TOWER_HOST and TOWER_PORT are deliberately absent: tower/config.py reads'
Write-Detail 'them into Settings, but nothing in the codebase ever reads them back, so'
Write-Detail 'writing them here would only look like configuration. The bind address'
Write-Detail 'comes from start_tower.ps1 -BindHost / -Port.'

# ---------------------------------------------------------------------------
Write-Step '8/12  data/ directory'
# ---------------------------------------------------------------------------
if (Test-Path -LiteralPath $dataDir) {
    Write-Ok "$dataDir exists."
} else {
    New-Item -ItemType Directory -Path $dataDir | Out-Null
    Write-Ok "Created $dataDir"
}
Write-Detail 'This records nothing. Arming is not recording: TOWER_CAPTURE_ROOT only'
Write-Detail 'arms the recorder. Nothing is written until a stream_start arrives on'
Write-Detail 'the websocket, and GET /health reports which state you are actually in.'

# ---------------------------------------------------------------------------
Write-Step '9/12  Face redaction weights'
# ---------------------------------------------------------------------------
if (Test-Path -LiteralPath $yunetModel) {
    Write-Ok 'Found models\face_detection_yunet_2023mar.onnx'
    Write-Detail 'Resolved relative to the CWD, which is why both scripts move to the'
    Write-Detail 'tower root before doing anything else.'
} else {
    Write-Note 'models\face_detection_yunet_2023mar.onnx is missing.'
    Write-Detail 'World Builder will still run, but every keyframe will honestly record'
    Write-Detail 'its redaction as "none" -- faces are NOT blurred. Restore the file at:'
    Write-Detail "  $yunetModel"
}

# ---------------------------------------------------------------------------
Write-Step '10/12  Windows Firewall (reported, never changed)'
# ---------------------------------------------------------------------------
$firewallRule = $null
try {
    $firewallRule = Get-NetFirewallRule -DisplayName 'Glasses Tower Dev' -ErrorAction Stop |
        Select-Object -First 1
} catch {
    $firewallRule = $null
}
if ($firewallRule) {
    Write-Ok ("Rule 'Glasses Tower Dev' exists (Enabled={0}, Direction={1}, Action={2})." -f `
        $firewallRule.Enabled, $firewallRule.Direction, $firewallRule.Action)
} else {
    Write-Note "No inbound rule named 'Glasses Tower Dev' was found."
    Write-Detail 'If the phone cannot reach the tower but localhost can, check this first.'
}
Write-Detail 'This project does not modify firewall rules automatically (README.md).'
Write-Detail 'Review this yourself and run it from an elevated PowerShell if you need it:'
Write-Host  '         New-NetFirewallRule -DisplayName "Glasses Tower Dev" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private' -ForegroundColor DarkGray

# ---------------------------------------------------------------------------
Write-Step '11/12  LAN address for the phone'
# ---------------------------------------------------------------------------
$addresses = @()
try {
    $addresses = @(
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.IPAddress -notlike '127.*' -and
                $_.IPAddress -notlike '169.254.*' -and
                $_.InterfaceAlias -notlike '*Loopback*'
            } |
            Sort-Object -Property InterfaceMetric
    )
} catch {
    $addresses = @()
}
if ($addresses.Count -eq 0) {
    Write-Note 'No non-loopback IPv4 address found. Run ipconfig and read it yourself.'
} else {
    foreach ($addr in $addresses) {
        Write-Ok "$($addr.IPAddress)  ($($addr.InterfaceAlias))"
        Write-Detail "  health:    http://$($addr.IPAddress):8000/health"
        Write-Detail "  websocket: ws://$($addr.IPAddress):8000/ws"
    }
    Write-Detail 'Both devices must be on the same LAN. This service is LAN-only and'
    Write-Detail 'unauthenticated -- never expose it to the public internet.'
}

# ---------------------------------------------------------------------------
Write-Step '12/12  Deeper diagnostics'
# ---------------------------------------------------------------------------
Write-Detail 'GPU, driver, torch build, and OpenCV checks are not duplicated here.'
Write-Detail 'Run the diagnostic that owns them:'
Write-Detail "  `"$venvPython`" scripts\world_builder_env_check.py"
Write-Detail '  (--format json for a machine-readable report; --strict to make a'
Write-Detail '   degraded environment a non-zero exit)'

# ---------------------------------------------------------------------------
Write-Host ''
if ($script:Failures -gt 0) {
    Write-Host "SETUP INCOMPLETE: $($script:Failures) failure(s), $($script:Notes) note(s)." -ForegroundColor Red
    Write-Host 'Fix the FAIL lines above and re-run -- this script is idempotent.' -ForegroundColor Red
    exit 1
}
Write-Host "Setup OK ($($script:Notes) note(s) above)." -ForegroundColor Green
Write-Host 'Start the tower with:  powershell -NoProfile -File scripts\start_tower.ps1' -ForegroundColor Green
exit 0
