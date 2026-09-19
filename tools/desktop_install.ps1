# Novel Translator Desktop Installer (Windows, no exe build)
# Copies app files to LocalAppData, creates a per-user .venv, Start Menu
# shortcut, and a Settings > Apps entry via HKCU Uninstall key (the "reg install").
# Mirrors SpatialLauncher's install location/registry pattern, but runs the
# Python source directly so tkinter reader + headset send keep working.

param(
    [switch]$NoLaunch
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$InstallDir = Join-Path $env:LOCALAPPDATA "NovelTranslator\app"
$VenvPython = Join-Path $InstallDir ".venv\Scripts\python.exe"
$VenvPythonw = Join-Path $InstallDir ".venv\Scripts\pythonw.exe"
$AppEntry = Join-Path $InstallDir "app.py"

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

function Test-PythonAt([string]$Path, [string[]]$ExtraArgs) {
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $false }
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

Write-Host ""
Write-Host "Novel Translator Desktop Installer" -ForegroundColor White
Write-Host "Per-user install, no exe build (registry entry is the install)." -ForegroundColor DarkGray
Write-Host ""
Write-Host "STORAGE" -ForegroundColor Yellow
Write-Host "  No drive picker - installs on your Windows user-profile drive (usually C:)." -ForegroundColor DarkGray
Write-Host ("  Folder: {0}\NovelTranslator\" -f $env:LOCALAPPDATA) -ForegroundColor DarkGray
Write-Host "  Uninstall via Settings / Apps / Novel Translator (books kept by default)." -ForegroundColor DarkGray
Write-Host "  Books/config live in Documents\NovelTranslator and %USERPROFILE%\.novel_translator (kept on uninstall)." -ForegroundColor DarkGray

Write-Step "1/5 Project files"
foreach ($name in @("app.py", "open_reader.py", "requirements.txt", "novel_translator", "ui", "tools\doctor.py")) {
    if (-not (Test-Path (Join-Path $Root $name))) { Fail "Missing app file: $name. Keep this whole folder together." }
    Write-Host "  [OK] $name"
}

Write-Step "2/5 Python 3.10+ with tkinter"
$py = Get-SystemPython
if (-not $py) {
    Fail "Python 3.10+ with tkinter not found. Run Start Novel Translator.bat once first (it installs Python), then re-run this installer."
}
$pyExe = $py.Exe
Write-Host "  [OK] $pyExe"

Write-Step "3/5 Copying app files to $InstallDir"
Get-Process -Name "pythonw" -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -match "Novel Translator" } | ForEach-Object {
        Write-Host "  Stopping running instance pid=$($_.Id)"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Milliseconds 400
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
try {
    Copy-Item -LiteralPath (Join-Path $Root "app.py") -Destination $InstallDir -Force -ErrorAction Stop
    Copy-Item -LiteralPath (Join-Path $Root "open_reader.py") -Destination $InstallDir -Force -ErrorAction Stop
    Copy-Item -LiteralPath (Join-Path $Root "requirements.txt") -Destination $InstallDir -Force -ErrorAction Stop
    Copy-Item -LiteralPath (Join-Path $Root "novel_translator") -Destination (Join-Path $InstallDir "novel_translator") -Recurse -Force -ErrorAction Stop
    Copy-Item -LiteralPath (Join-Path $Root "ui") -Destination (Join-Path $InstallDir "ui") -Recurse -Force -ErrorAction Stop
    New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir "tools") | Out-Null
    Copy-Item -LiteralPath (Join-Path $Root "tools\doctor.py") -Destination (Join-Path $InstallDir "tools\doctor.py") -Force -ErrorAction Stop
} catch {
    Fail "Copy to install folder failed: $($_.Exception.Message)"
}
if (-not (Test-Path -LiteralPath $AppEntry)) { Fail "Install copy failed - missing app.py under $InstallDir" }
Write-Host "  Files OK -> $InstallDir"

Write-Step "4/5 App environment + packages"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "  Creating .venv ..."
    & $pyExe @($py.Args) -m venv (Join-Path $InstallDir ".venv")
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $VenvPython)) { Fail "Could not create .venv in $InstallDir" }
} else {
    Write-Host "  [OK] .venv already present"
}
& $VenvPython -m pip install --upgrade pip 2>$null | Out-Null
& $VenvPython -m pip install -r (Join-Path $InstallDir "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail "Could not install Python packages. Check the internet connection." }
& $VenvPython (Join-Path $InstallDir "tools\doctor.py")
if ($LASTEXITCODE -ne 0) { Fail "Doctor still found a problem. Scroll up for FAIL lines." }

Write-Step "5/5 Shortcut + Apps entry (reg install)"
$launcher = Join-Path $InstallDir "NovelTranslator.cmd"
@(
    '@echo off',
    'setlocal',
    'cd /d "%~dp0"',
    'start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py"',
    'endlocal',
    'exit /b 0'
) | Set-Content -Path $launcher -Encoding ASCII

$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
New-Item -ItemType Directory -Force -Path $startMenu | Out-Null
$lnkPath = Join-Path $startMenu "Novel Translator.lnk"
$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut($lnkPath)
$lnk.TargetPath = $VenvPythonw
$lnk.Arguments = "`"$AppEntry`""
$lnk.WorkingDirectory = $InstallDir
$lnk.Description = "Novel Translator"
$lnk.Save()
Write-Host "  Shortcut: $lnkPath"

$uninstallPs1 = Join-Path $InstallDir "uninstall.ps1"
$uninstallCmd = Join-Path $InstallDir "uninstall.cmd"
Copy-Item -LiteralPath (Join-Path $Root "tools\desktop_uninstall.ps1") -Destination $uninstallPs1 -Force
Copy-Item -LiteralPath (Join-Path $Root "tools\desktop_uninstall.cmd") -Destination $uninstallCmd -Force
@(
    '@echo off',
    'setlocal',
    'title Uninstall Novel Translator',
    'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"',
    'endlocal',
    'exit /b %ERRORLEVEL%'
) | Set-Content -Path $uninstallCmd -Encoding ASCII

$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\NovelTranslator"
New-Item -Path $uninstallKey -Force | Out-Null
$version = "0.1.0"
$estimated = 0
Get-ChildItem -Path $InstallDir -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object { $estimated += $_.Length }
$estimatedKb = [int]([math]::Max(1, [math]::Ceiling($estimated / 1KB)))

Set-ItemProperty -Path $uninstallKey -Name "DisplayName" -Value "Novel Translator"
Set-ItemProperty -Path $uninstallKey -Name "DisplayVersion" -Value $version
Set-ItemProperty -Path $uninstallKey -Name "Publisher" -Value "saogalaxy"
Set-ItemProperty -Path $uninstallKey -Name "InstallLocation" -Value $InstallDir
Set-ItemProperty -Path $uninstallKey -Name "DisplayIcon" -Value $VenvPythonw
Set-ItemProperty -Path $uninstallKey -Name "UninstallString" -Value ("powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$uninstallPs1`"")
Set-ItemProperty -Path $uninstallKey -Name "QuietUninstallString" -Value ("powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$uninstallPs1`" -Silent")
Set-ItemProperty -Path $uninstallKey -Name "NoModify" -Value 1 -Type DWord
Set-ItemProperty -Path $uninstallKey -Name "NoRepair" -Value 1 -Type DWord
Set-ItemProperty -Path $uninstallKey -Name "EstimatedSize" -Value $estimatedKb -Type DWord
Write-Host "  Listed under Settings > Apps as Novel Translator (no Setup.exe needed)"

if (-not $NoLaunch) {
    Write-Step "Launching Novel Translator"
    try {
        Start-Process -FilePath $VenvPythonw -ArgumentList "`"$AppEntry`"" -WorkingDirectory $InstallDir | Out-Null
        Write-Host "  Launched: $AppEntry"
    } catch {
        Write-Host "  Launch failed: $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "  Open from Start Menu: Novel Translator" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "READY TO GO: YES" -ForegroundColor Green
Write-Host "Installed: $InstallDir"
exit 0
