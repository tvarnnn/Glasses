#Requires -Version 5.1
<#
.SYNOPSIS
    Start the Glasses Tower. The one command for ordinary development.

.DESCRIPTION
    Preflights the environment, diagnoses (never silently kills) whatever
    owns the port, prints the configuration that will actually be in
    effect, and then runs uvicorn against tower.main:app from the tower
    root.

    No venv activation, no second terminal, no manual environment
    variables: .env is handed to uvicorn with --env-file, which loads it in
    Config.__init__ -- before the app is imported -- so the TOWER_* values
    reach get_settings() in tower/config.py.

.PARAMETER Port
    TCP port to listen on. Default 8000.

.PARAMETER BindHost
    Interface to bind. Default 0.0.0.0, which is what the phone needs.
    Named -BindHost rather than -Host because $Host is an automatic
    PowerShell variable and a -Host parameter shadows it.

.PARAMETER Reload
    Enable uvicorn's auto-reload. Development convenience only.

.PARAMETER Force
    If the port is already held, attempt to stop the owning process.
    Off by default: killing a process you did not identify is not a thing
    a start script should do on its own.

.EXAMPLE
    powershell -NoProfile -File scripts\start_tower.ps1

.EXAMPLE
    powershell -NoProfile -File scripts\start_tower.ps1 -Port 8001 -Reload
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,

    [ValidateNotNullOrEmpty()]
    [string]$BindHost = '0.0.0.0',

    [switch]$Reload,

    [switch]$Force
)

$ErrorActionPreference = 'Stop'

# tower/world_builder/redaction.py resolves the YuNet weights
# ("models/face_detection_yunet_2023mar.onnx") relative to the process CWD.
# Launch the server from anywhere else and face redaction is silently
# disabled -- keyframes then record their redaction as "none". So: the tower
# root, always, before anything is started.
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

$venvPython = Join-Path $root '.venv\Scripts\python.exe'
$envFile    = Join-Path $root '.env'
$setupHint  = 'powershell -NoProfile -File scripts\setup_tower.ps1'

function Write-Line {
    param([string]$Text)
    Write-Host "  $Text" -ForegroundColor DarkGray
}

function Write-Problem {
    param([string]$Text)
    Write-Host "  $Text" -ForegroundColor Yellow
}

function Stop-WithFix {
    param([string]$Text, [string[]]$Fix)
    Write-Host ''
    Write-Host "ABORT: $Text" -ForegroundColor Red
    foreach ($line in $Fix) {
        Write-Host "  fix: $line" -ForegroundColor Red
    }
    exit 1
}

Write-Host 'Glasses Tower' -ForegroundColor White
Write-Host "root: $root"

# ---------------------------------------------------------------------------
# 1. Preflight: the venv and the dev extra.
# ---------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $venvPython)) {
    Stop-WithFix "No interpreter at $venvPython" @($setupHint)
}

& $venvPython -c "import uvicorn, fastapi, pytest, httpx2, websockets"
if ($LASTEXITCODE -ne 0) {
    Stop-WithFix 'The venv is missing runtime or dev dependencies (see the import error above).' @(
        $setupHint,
        "or directly: `"$venvPython`" -m pip install -e `".[dev]`""
    )
}
Write-Line 'preflight: venv and dev extra present.'

# ---------------------------------------------------------------------------
# 2. Port ownership. Diagnosed always, killed only under -Force.
# ---------------------------------------------------------------------------
$listeners = @()
try {
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop)
} catch {
    # No listener on that port: Get-NetTCPConnection throws rather than
    # returning an empty set. That is the good case.
    $listeners = @()
}

if ($listeners.Count -gt 0) {
    Write-Host ''
    Write-Host "Port $Port is already in use." -ForegroundColor Yellow

    $ownerPids = @($listeners | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique)
    foreach ($ownerPid in $ownerPids) {
        $procName = '<unknown>'
        $cmdLine = ''
        try {
            $procName = (Get-Process -Id $ownerPid -ErrorAction Stop).ProcessName
        } catch {
            $procName = '<could not read process; it may belong to another user>'
        }
        try {
            $cimProc = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $ownerPid" -ErrorAction Stop
            if ($cimProc) { $cmdLine = [string]$cimProc.CommandLine }
        } catch {
            $cmdLine = ''
        }

        Write-Problem "pid $ownerPid  ($procName)"
        if ($cmdLine) {
            Write-Line "cmdline: $cmdLine"
        } else {
            Write-Line 'cmdline: <unavailable -- usually means the process is elevated or another user owns it>'
        }

        if ($cmdLine -match 'tower\.main:app') {
            Write-Problem 'This looks like our own stale uvicorn (its command line names tower.main:app).'
        } elseif ($procName -match '^python') {
            Write-Problem 'A Python process, but its command line does not name tower.main:app.'
            Write-Line 'Check it before killing it -- it may be another tool of yours.'
        } else {
            Write-Problem 'This does not look like the tower. Something else owns the port.'
        }
        Write-Line "to stop it: Stop-Process -Id $ownerPid"

        if ($Force) {
            Write-Line "-Force given: attempting Stop-Process -Id $ownerPid"
            try {
                Stop-Process -Id $ownerPid -Force -ErrorAction Stop
                Write-Line "stopped pid $ownerPid"
            } catch {
                $reason = $_.Exception.Message
                Write-Problem "Could not stop pid ${ownerPid}: $reason"
                if ($reason -match 'denied|Access|permission') {
                    # The exact failure from the 2026-08-24 physical run: the
                    # stale server was started from a shell with different
                    # privileges, so an unelevated Stop-Process cannot touch it.
                    Write-Problem 'Access denied. That process is running with privileges this shell does not have.'
                    Write-Line 'Open an elevated PowerShell:'
                    Write-Line '    Start-Process powershell -Verb RunAs'
                    Write-Line 'and in it run:'
                    Write-Line "    Stop-Process -Id $ownerPid -Force"
                    Write-Line 'Or close the terminal window that owns it -- usually faster than elevating.'
                }
            }
        }
    }

    # Re-check: -Force may have cleared it.
    $stillHeld = @()
    try {
        $stillHeld = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop)
    } catch {
        $stillHeld = @()
    }
    if ($stillHeld.Count -gt 0) {
        if ($Force) {
            Stop-WithFix "Port $Port is still held after -Force." @(
                'Stop the owning process from an elevated PowerShell (see above),',
                "or start on a different port: scripts\start_tower.ps1 -Port 8001"
            )
        }
        Stop-WithFix "Port $Port is held and -Force was not given." @(
            'Review the process above, then either stop it yourself, re-run with',
            '-Force, or pick another port:',
            "    scripts\start_tower.ps1 -Port 8001",
            'Note that a different port also changes the ws:// URL the phone uses.'
        )
    }
    Write-Line "Port $Port is free again."
}

# ---------------------------------------------------------------------------
# 3. Resolve and echo the configuration that will actually be in effect.
# ---------------------------------------------------------------------------
$envValues = @{}
if (Test-Path -LiteralPath $envFile) {
    foreach ($line in (Get-Content -LiteralPath $envFile)) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $split = $trimmed.IndexOf('=')
        if ($split -lt 1) { continue }
        $key = $trimmed.Substring(0, $split).Trim()
        $value = $trimmed.Substring($split + 1).Trim().Trim('"').Trim("'")
        $envValues[$key] = $value
    }
} else {
    Write-Problem "No .env at $envFile -- the tower will start with defaults only."
    Write-Line "Create it with: $setupHint"
}

function Resolve-Setting {
    param([string]$Name)
    # Process environment wins: uvicorn's --env-file uses python-dotenv's
    # default, which does not override variables already set.
    $fromProcess = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if ($fromProcess) { return @{ Value = $fromProcess; Source = 'shell environment' } }
    if ($envValues.ContainsKey($Name)) { return @{ Value = $envValues[$Name]; Source = '.env' } }
    return @{ Value = $null; Source = 'unset' }
}

$captureRoot = Resolve-Setting 'TOWER_CAPTURE_ROOT'
$worldRoot   = Resolve-Setting 'TOWER_WORLD_ROOT'
$devMode     = Resolve-Setting 'TOWER_DEV_MODE'
$cvExp       = Resolve-Setting 'TOWER_CV_EXPERIMENT'
$cvDevice    = Resolve-Setting 'TOWER_CV_DEVICE'

Write-Host ''
Write-Host 'Effective configuration' -ForegroundColor Cyan
Write-Line "cwd                 $root"
Write-Line "bind                $BindHost`:$Port   (from -BindHost / -Port)"
Write-Line "env-file            $envFile"

if ($captureRoot.Value) {
    Write-Line "TOWER_CAPTURE_ROOT  $($captureRoot.Value)   [$($captureRoot.Source)]"
    Write-Line '                    Recorder ARMED. Still records nothing until a'
    Write-Line '                    stream_start arrives -- arming is not recording.'
} else {
    Write-Problem 'TOWER_CAPTURE_ROOT  <unset>'
    Write-Line '                    Cost: no frames will EVER be recorded this run, and'
    Write-Line '                    GET /health reports "capture": null.'
}

if ($worldRoot.Value) {
    Write-Line "TOWER_WORLD_ROOT    $($worldRoot.Value)   [$($worldRoot.Source)]"
    if ($worldRoot.Value -ne 'data/world_builder') {
        Write-Problem '                    Not data/world_builder. This must match DEFAULT_ROOT'
        Write-Problem '                    in scripts/world_build_session.py, or the result'
        Write-Problem '                    channel reads a different tree than the builder writes.'
    }
} else {
    Write-Problem 'TOWER_WORLD_ROOT    <unset>'
    Write-Line '                    Cost: iOS sees World Builder as unsupported -- the'
    Write-Line '                    capability is simply absent from the handshake.'
}

if ($devMode.Value) {
    Write-Line "TOWER_DEV_MODE      $($devMode.Value)   [$($devMode.Source)]"
} else {
    Write-Line 'TOWER_DEV_MODE      <unset, defaults to true>  DEBUG-level root logging.'
}
if ($cvExp.Value) {
    Write-Line "TOWER_CV_EXPERIMENT $($cvExp.Value)   [$($cvExp.Source)]"
} else {
    Write-Line 'TOWER_CV_EXPERIMENT <unset, defaults to baseline>'
}
if ($cvDevice.Value) {
    Write-Line "TOWER_CV_DEVICE     $($cvDevice.Value)   [$($cvDevice.Source)]"
} else {
    Write-Line 'TOWER_CV_DEVICE     <unset, defaults to auto>'
}

Write-Line 'TOWER_HOST / TOWER_PORT are read into Settings by tower/config.py but'
Write-Line 'nothing reads them back, so setting them binds nothing. -BindHost and'
Write-Line '-Port are the only things that decide where the server listens.'

if (-not (Test-Path -LiteralPath (Join-Path $root 'models\face_detection_yunet_2023mar.onnx'))) {
    Write-Problem 'models\face_detection_yunet_2023mar.onnx is missing: World Builder will'
    Write-Problem 'record redaction as "none". Faces are NOT blurred.'
}

if ($BindHost -eq '127.0.0.1' -or $BindHost -eq 'localhost') {
    Write-Problem "Bound to $BindHost -- reachable from this machine only. The phone"
    Write-Problem 'cannot connect. Use the default 0.0.0.0 for a physical run.'
}

# ---------------------------------------------------------------------------
# 4. Launch.
# ---------------------------------------------------------------------------
# tower.main:app, never --factory: tower/main.py already calls create_app() at
# import time, and create_app() starts the module container. The factory form
# would build a second one.
# --host is always explicit: uvicorn's own default is 127.0.0.1, not 0.0.0.0,
# so omitting it makes the tower unreachable from the phone.
$uvicornArgs = @(
    '-m', 'uvicorn', 'tower.main:app',
    '--host', $BindHost,
    '--port', "$Port"
)
if (Test-Path -LiteralPath $envFile) {
    $uvicornArgs += @('--env-file', $envFile)
}
if ($Reload) {
    $uvicornArgs += '--reload'
}

Write-Host ''
Write-Host "> `"$venvPython`" $($uvicornArgs -join ' ')" -ForegroundColor Cyan
Write-Host 'Ctrl+C to stop.' -ForegroundColor DarkGray
Write-Host ''

& $venvPython @uvicornArgs
exit $LASTEXITCODE
