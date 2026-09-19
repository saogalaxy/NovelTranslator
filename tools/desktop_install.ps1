# Novel Translator Desktop Easy Installer (Windows)
# Mirrors SpatialLauncher tools\desktop_easy_install.ps1:
# builds/publishes the app and copies it to LocalAppData + Start Menu shortcut.

param(
    [switch]$SkipBuild,
    [switch]$NoLaunch
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$PublishDir = Join-Path $Root "installer\publish"
$InstallDir = Join-Path $env:LOCALAPPDATA "NovelTranslator\app"
$ExeName = "NovelTranslator.exe"

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

Write-Host ""
Write-Host "Novel Translator Desktop Easy Installer" -ForegroundColor White
Write-Host "Build + install PC app (Syosetu download, translate, EPUB)." -ForegroundColor DarkGray
Write-Host ""
Write-Host "STORAGE" -ForegroundColor Yellow
Write-Host "  No drive picker - installs on your Windows user-profile drive (usually C:)." -ForegroundColor DarkGray
Write-Host ("  Folder: {0}\NovelTranslator\" -f $env:LOCALAPPDATA) -ForegroundColor DarkGray
Write-Host "  Expect ~120-200 MB for the app (Python runtime bundled)." -ForegroundColor DarkGray
Write-Host "  Uninstall via Settings / Apps / Novel Translator (books kept by default)." -ForegroundColor DarkGray
Write-Host "  Books/config live in Documents\NovelTranslator and %USERPROFILE%\.novel_translator (kept on uninstall)." -ForegroundColor DarkGray

if (-not $SkipBuild) {
    Write-Step "Building exe (PyInstaller)"
    $buildScript = Join-Path $PSScriptRoot "build_exe.ps1"
    if (-not (Test-Path -LiteralPath $buildScript)) { Fail "Missing tools\build_exe.ps1" }
    & powershell -NoProfile -ExecutionPolicy Bypass -File $buildScript
    if ($LASTEXITCODE -ne 0) { Fail "build_exe.ps1 failed (exit $LASTEXITCODE)." }
} else {
    Write-Step "SkipBuild - using existing publish folder"
    if (-not (Test-Path (Join-Path $PublishDir $ExeName))) {
        Fail "No published exe at $PublishDir\$ExeName. Re-run without -SkipBuild."
    }
}
Write-Host "  Publish OK -> $PublishDir"

Write-Step "Installing to $InstallDir"
Get-Process -Name "NovelTranslator" -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "  Stopping running instance pid=$($_.Id)"
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 400
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
try {
    Copy-Item -Path (Join-Path $PublishDir "*") -Destination $InstallDir -Recurse -Force -ErrorAction Stop
} catch {
    Fail "Copy to install folder failed: $($_.Exception.Message)"
}

$desktopExe = Join-Path $InstallDir $ExeName
if (-not (Test-Path -LiteralPath $desktopExe)) {
    $desktopExe = Get-ChildItem -Path $InstallDir -Filter $ExeName -File -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if ([string]::IsNullOrWhiteSpace($desktopExe) -or -not (Test-Path -LiteralPath $desktopExe)) {
    Fail "Install copy failed - missing $ExeName under $InstallDir"
}
Write-Host "  Exe: $desktopExe  ($((Get-Item -LiteralPath $desktopExe).LastWriteTime))"

Write-Step "Start Menu shortcut"
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
New-Item -ItemType Directory -Force -Path $startMenu | Out-Null
$lnkPath = Join-Path $startMenu "Novel Translator.lnk"
$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut($lnkPath)
$lnk.TargetPath = $desktopExe
$lnk.WorkingDirectory = $InstallDir
$lnk.Description = "Novel Translator"
$lnk.Save()
Write-Host "  Shortcut: $lnkPath"

Write-Step "Register Apps and Features uninstall entry"
$uninstallPs1 = Join-Path $InstallDir "uninstall.ps1"
$uninstallCmd = Join-Path $InstallDir "uninstall.cmd"
Copy-Item -Path (Join-Path $PSScriptRoot "desktop_uninstall.ps1") -Destination $uninstallPs1 -Force
Copy-Item -Path (Join-Path $PSScriptRoot "desktop_uninstall.cmd") -Destination $uninstallCmd -Force
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
$displayIcon = $desktopExe
$version = "0.1.0"
try {
    $vi = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($desktopExe)
    if ($vi.ProductVersion) { $version = $vi.ProductVersion }
} catch { }

$estimated = 0
Get-ChildItem -Path $InstallDir -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object { $estimated += $_.Length }
$estimatedKb = [int]([math]::Max(1, [math]::Ceiling($estimated / 1KB)))

Set-ItemProperty -Path $uninstallKey -Name "DisplayName" -Value "Novel Translator"
Set-ItemProperty -Path $uninstallKey -Name "DisplayVersion" -Value $version
Set-ItemProperty -Path $uninstallKey -Name "Publisher" -Value "saogalaxy"
Set-ItemProperty -Path $uninstallKey -Name "InstallLocation" -Value $InstallDir
Set-ItemProperty -Path $uninstallKey -Name "DisplayIcon" -Value $displayIcon
Set-ItemProperty -Path $uninstallKey -Name "UninstallString" -Value ("powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$uninstallPs1`"")
Set-ItemProperty -Path $uninstallKey -Name "QuietUninstallString" -Value ("powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$uninstallPs1`" -Silent")
Set-ItemProperty -Path $uninstallKey -Name "NoModify" -Value 1 -Type DWord
Set-ItemProperty -Path $uninstallKey -Name "NoRepair" -Value 1 -Type DWord
Set-ItemProperty -Path $uninstallKey -Name "EstimatedSize" -Value $estimatedKb -Type DWord
Write-Host "  Listed under Settings > Apps as Novel Translator"

if (-not $NoLaunch) {
    Write-Step "Launching Novel Translator"
    try {
        Start-Process -FilePath $desktopExe -WorkingDirectory $InstallDir | Out-Null
        Write-Host "  Launched: $desktopExe"
    } catch {
        Write-Host "  Launch failed: $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "  Open from Start Menu: Novel Translator" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "READY TO GO: YES" -ForegroundColor Green
Write-Host "Installed: $desktopExe"
$appBytes = 0L
Get-ChildItem -Path $InstallDir -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object { $appBytes += $_.Length }
$appMb = [math]::Round($appBytes / 1MB, 1)
Write-Host ("PC storage used: app {0} MB under {1}" -f $appMb, (Split-Path $InstallDir -Parent))
exit 0
