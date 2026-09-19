# Novel Translator Easy Installer
# Looks at what is missing, installs the right pieces, then re-checks until ready.

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$PythonVersion = "3.12.10"
$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Fail([string]$Message) {
    Write-Host ""
    Write-Host "READY TO GO: NO" -ForegroundColor Red
    Write-Host $Message -ForegroundColor Yellow
    exit 1
}

function Refresh-Path {
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Test-PythonAt([string]$Path, [string[]]$ExtraArgs) {
    if (-not $Path -or -not (Test-Path $Path)) { return $false }
    if ($Path -match "WindowsApps") { return $false }
    $allArgs = @()
    if ($ExtraArgs) { $allArgs += $ExtraArgs }
    $allArgs += "-c", "import sys, tkinter; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
    & $Path @allArgs 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Get-SystemPython {
    $places = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python313\python.exe",
        "$env:ProgramFiles\Python311\python.exe"
    )
    foreach ($path in $places) {
        if (Test-PythonAt $path @()) {
            return [pscustomobject]@{ Exe = $path; Args = @() }
        }
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py -and (Test-PythonAt $py.Source @("-3"))) {
        return [pscustomobject]@{ Exe = $py.Source; Args = @("-3") }
    }
    foreach ($name in @("python", "python3")) {
        $found = Get-Command $name -ErrorAction SilentlyContinue
        if ($found -and (Test-PythonAt $found.Source @())) {
            return [pscustomobject]@{ Exe = $found.Source; Args = @() }
        }
    }
    return $null
}

function Install-Python {
    Write-Host "  Python not found. Installing Python $PythonVersion ..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host "  Trying winget (Python.Python.3.12) ..."
        & winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements --disable-interactivity
        Refresh-Path
        if (Get-SystemPython) { return }
    }

    $installer = Join-Path $env:TEMP "python-$PythonVersion-amd64.exe"
    Write-Host "  Downloading official Python installer ..."
    try {
        Invoke-WebRequest -Uri $PythonUrl -OutFile $installer -UseBasicParsing
    } catch {
        Fail "Could not download Python. Check the internet connection.`n$($_.Exception.Message)"
    }
    Write-Host "  Running silent Python setup (user install, PATH, tcl/tk, pip) ..."
    $args = "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_doc=0 Include_tcltk=1 Include_pip=1 Include_launcher=1 Include_dev=0 Shortcuts=0 AssociateFiles=0"
    $proc = Start-Process -FilePath $installer -ArgumentList $args -Wait -PassThru
    if ($proc.ExitCode -ne 0 -and $proc.ExitCode -ne 3010) {
        Fail "Python installer exited with code $($proc.ExitCode)."
    }
    Refresh-Path
    Start-Sleep -Seconds 2
}

function Get-NeededPackages {
    $needed = @()
    Get-Content (Join-Path $Root "requirements.txt") | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $needed += $line
    }
    return $needed
}

function Get-MissingPackages([string]$VenvPython) {
    $map = @{
        "beautifulsoup4" = "bs4"
        "ebooklib" = "ebooklib"
        "httpx" = "httpx"
        "lxml" = "lxml"
        "pypdf" = "pypdf"
        "pywebview" = "webview"
        "pykakasi" = "pykakasi"
    }
    $missing = @()
    foreach ($spec in Get-NeededPackages) {
        $name = ($spec -split "[><= ]")[0].Trim()
        $mod = $map[$name]
        if (-not $mod) { $mod = $name }
        & $VenvPython -c "import $mod" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [MISSING] $name"
            $missing += $spec
        } else {
            Write-Host "  [OK] $name"
        }
    }
    return $missing
}

Write-Host "Novel Translator Easy Installer"
Write-Host "Looks for what is needed and installs the right files."
Write-Host ("Root: " + $Root)

Write-Step "1/6 Project files"
foreach ($name in @("app.py", "requirements.txt", "novel_translator", "tools\doctor.py")) {
    $path = Join-Path $Root $name
    if (-not (Test-Path $path)) { Fail "Missing app file: $name. Keep this whole folder together." }
    Write-Host "  [OK] $name"
}

Write-Step "2/6 Python 3.10+ with tkinter"
$py = Get-SystemPython
if (-not $py) {
    Install-Python
    $py = Get-SystemPython
}
if (-not $py) {
    Fail "Python was installed but this window cannot see it yet. Close this window and run the installer again."
}
$pyExe = $py.Exe
$pyArgs = @($py.Args)
$version = & $pyExe @pyArgs -c "import sys; print(sys.version.split()[0])"
Write-Host "  [OK] $pyExe ($version)"

Write-Step "3/6 App environment"
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
$venvPythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "  Creating .venv (missing) ..."
    & $pyExe @pyArgs -m venv (Join-Path $Root ".venv")
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) { Fail "Could not create .venv" }
} else {
    Write-Host "  [OK] .venv already present"
}
if (-not (Test-Path $venvPythonw)) { Fail "pythonw.exe is missing from .venv after setup." }

Write-Step "4/6 pip"
& $venvPython -m pip --version 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  pip missing. Bootstrapping ..."
    & $venvPython -m ensurepip --upgrade
}
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Fail "Could not install pip. Check the internet connection." }
Write-Host "  [OK] pip"

Write-Step "5/6 Packages the app needs"
$missing = @(Get-MissingPackages $venvPython)
if ($missing.Count -gt 0) {
    Write-Host "  Installing missing packages: $($missing -join ', ')"
    & $venvPython -m pip install @missing
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Named install failed; installing full requirements.txt ..."
        & $venvPython -m pip install -r (Join-Path $Root "requirements.txt")
        if ($LASTEXITCODE -ne 0) { Fail "Could not install Python packages. Check the internet connection." }
    }
} else {
    Write-Host "  All packages already present. Syncing versions from requirements.txt ..."
    & $venvPython -m pip install -r (Join-Path $Root "requirements.txt")
    if ($LASTEXITCODE -ne 0) { Fail "Could not sync packages from requirements.txt." }
}
$still = @(Get-MissingPackages $venvPython)
if ($still.Count -gt 0) { Fail "Still missing after install: $($still -join ', ')" }

Write-Step "6/6 Final ready check"
& $venvPython (Join-Path $Root "tools\doctor.py")
if ($LASTEXITCODE -ne 0) { Fail "Doctor still found a problem. Scroll up for FAIL lines." }

Write-Host ""
Write-Host "READY TO GO: YES" -ForegroundColor Green
exit 0
