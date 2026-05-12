# build.ps1 — build HistorianCareer for The Sims 4 end-to-end.
#
# Produces:
#   Build/out/HistorianCareer_Tuning.package    (XML tuning + STBL, built by @s4tk/models)
#   Build/out/HistorianCareer.ts4script         (compiled Python, zipped, folders preserved)
#
# Usage (from the project root):
#   pwsh -File Build/build.ps1
#   pwsh -File Build/build.ps1 -InstallToMods    # also copies both artifacts to your Mods folder
#   pwsh -File Build/build.ps1 -PackageOnly      # skips the Python step (useful before Python 3.7 install)
#   pwsh -File Build/build.ps1 -ScriptOnly       # skips the .package step

[CmdletBinding()]
param(
    [switch]$InstallToMods,
    [switch]$PackageOnly,
    [switch]$ScriptOnly,
    [switch]$LayerB,           # Include the full Career/Aspiration set with auto-generated SimData
    [string]$ModsFolder        # If unset, auto-detected from the localized game folder
)

# Auto-detect the game's user-data folder. The Sims 4 localizes the folder name
# based on game language (Die Sims 4 / Les Sims 4 / Los Sims 4 / etc.). Prefer
# whichever sibling under "Documents\Electronic Arts\" contains an Options.ini
# (the marker that the game has been launched and configured there).
if (-not $ModsFolder) {
    $eaDocs = Join-Path $HOME 'Documents\Electronic Arts'
    $candidate = $null
    if (Test-Path $eaDocs) {
        $simsFolders = Get-ChildItem $eaDocs -Directory |
            Where-Object { $_.Name -match '^(The|Die|Les|Los) Sims 4$' -or $_.Name -eq 'The Sims 4' }
        # Prefer the one with Options.ini; fall back to the English name.
        $candidate = $simsFolders | Where-Object { Test-Path (Join-Path $_.FullName 'Options.ini') } | Select-Object -First 1
        if (-not $candidate) { $candidate = $simsFolders | Select-Object -First 1 }
    }
    if ($candidate) {
        $ModsFolder = Join-Path $candidate.FullName 'Mods\HistorianCareer'
    } else {
        # Last-resort default: English. The game will create the localized one on first launch.
        $ModsFolder = "$HOME\Documents\Electronic Arts\The Sims 4\Mods\HistorianCareer"
    }
}

$ErrorActionPreference = 'Stop'
$root      = Split-Path -Parent $PSScriptRoot
$scripts   = Join-Path $root 'Scripts'
$outDir    = Join-Path $PSScriptRoot 'out'
$pkgName   = 'HistorianCareer'
$ts4script = Join-Path $outDir "$pkgName.ts4script"
$packageOut = Join-Path $outDir "$pkgName`_Tuning.package"
$s4tkBuilder = Join-Path $PSScriptRoot 's4tk-builder'
$simdataDir  = Join-Path $PSScriptRoot 'simdata'

New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# -----------------------------------------------------------------------------
# 1. Build the .package via @s4tk/models (Node.js)
# -----------------------------------------------------------------------------
if (-not $ScriptOnly) {
    Write-Host "==> Building $packageOut (s4tk)" -ForegroundColor Cyan
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        throw "node not found on PATH. Install Node 16+ from https://nodejs.org or pass -ScriptOnly to skip."
    }

    # 1a. Ensure simdata is installed and compiled. Required when -LayerB so the
    #     s4tk-builder can import the SimData generator.
    if (Test-Path $simdataDir) {
        if (-not (Test-Path (Join-Path $simdataDir 'node_modules'))) {
            Write-Host "    installing simdata dependencies..." -ForegroundColor DarkGray
            Push-Location $simdataDir
            npm install --silent
            if ($LASTEXITCODE -ne 0) { Pop-Location; throw "npm install failed in simdata" }
            Pop-Location
        }
        if (-not (Test-Path (Join-Path $simdataDir 'dist/index.js'))) {
            Write-Host "    compiling simdata (tsc)..." -ForegroundColor DarkGray
            Push-Location $simdataDir
            & npx tsc
            if ($LASTEXITCODE -ne 0) { Pop-Location; throw "tsc failed in simdata" }
            Pop-Location
        }
    }

    if (-not (Test-Path (Join-Path $s4tkBuilder 'node_modules'))) {
        Write-Host "    installing s4tk-builder dependencies..." -ForegroundColor DarkGray
        Push-Location $s4tkBuilder
        npm install --silent
        if ($LASTEXITCODE -ne 0) { Pop-Location; throw "npm install failed" }
        Pop-Location
    }

    $builderArgs = @()
    if ($LayerB) { $builderArgs += '--include-layer-b' }

    Push-Location $s4tkBuilder
    & node build-package.mjs @builderArgs
    $rc = $LASTEXITCODE
    Pop-Location
    if ($rc -ne 0) { throw "s4tk builder failed (exit $rc)" }
}

# -----------------------------------------------------------------------------
# 2. Build the .ts4script via compileall + Compress-Archive
# -----------------------------------------------------------------------------
if (-not $PackageOnly) {
    # The Sims 4 ships Python 3.7. If your default `python` is newer, install 3.7
    # and point $env:PY_SIMS at its executable.
    $py = $env:PY_SIMS
    if (-not $py) { $py = 'python' }

    Write-Host "==> Compiling Python with $py" -ForegroundColor Cyan
    # Diagnostic version check. Use --version (Python prints "Python 3.7.9" to stderr
    # historically, stdout in 3.4+). We accept any 3.7.x.
    $pyVerRaw = (& $py --version 2>&1 | Out-String).Trim()
    if ($pyVerRaw -notmatch 'Python 3\.7\.') {
        Write-Warning "Detected: $pyVerRaw. The Sims 4 needs 3.7 bytecode - the resulting .ts4script will fail to load. Install Python 3.7.9 and set PY_SIMS to its python.exe, or pass -PackageOnly to skip this step."
    } else {
        Write-Host "    $pyVerRaw" -ForegroundColor DarkGray
    }
    & $py -m compileall -b $scripts | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "compileall failed (exit $LASTEXITCODE)" }

    $stage = Join-Path $outDir 'stage'
    if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
    New-Item -ItemType Directory -Force -Path $stage | Out-Null

    Get-ChildItem -Path $scripts -Recurse -Filter *.pyc | ForEach-Object {
        $relative = $_.FullName.Substring($scripts.Length + 1)
        $dest = Join-Path $stage $relative
        New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $dest
    }

    if (Test-Path $ts4script) { Remove-Item -Force $ts4script }
    Write-Host "==> Writing $ts4script" -ForegroundColor Cyan
    # PowerShell 5.1's Compress-Archive only accepts a .zip destination. Write to .zip
    # then rename — the contents are identical, only the extension differs (Sims 4 looks
    # for *.ts4script in the Mods folder).
    $tmpZip = Join-Path $outDir "$pkgName.ts4script.zip"
    if (Test-Path $tmpZip) { Remove-Item -Force $tmpZip }
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $tmpZip -CompressionLevel Optimal
    Move-Item -Force $tmpZip $ts4script
}

# -----------------------------------------------------------------------------
# 3. Install
# -----------------------------------------------------------------------------
if ($InstallToMods) {
    New-Item -ItemType Directory -Force -Path $ModsFolder | Out-Null
    if (Test-Path $packageOut)   { Copy-Item -Force $packageOut (Join-Path $ModsFolder "$pkgName`_Tuning.package") }
    if (Test-Path $ts4script)    { Copy-Item -Force $ts4script  (Join-Path $ModsFolder "$pkgName.ts4script") }
    Write-Host "==> Installed to $ModsFolder" -ForegroundColor Green
}

Write-Host "==> Done." -ForegroundColor Green
