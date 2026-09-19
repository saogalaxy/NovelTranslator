# Novel Translator — build Windows exe with PyInstaller
# Output: installer\publish\NovelTranslator.exe (one-folder, windowed)
# Run from repo root or via tools\desktop_install.ps1 (which calls this).

param(
    [switch]$Clean
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Fail([string]$Message) {
    Write-Host ""
    Write-Host "BUILD FAILED" -ForegroundColor Red
    Write-Host $Message -ForegroundColor Yellow
    exit 1
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Fail "Missing .venv. Run Start Novel Translator.bat once first so easy_install.ps1 creates it."
}

Write-Host ""
Write-Host "==> Checking PyInstaller" -ForegroundColor Cyan
& $VenvPython -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Installing pyinstaller ..."
    & $VenvPython -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) { Fail "Could not install pyinstaller." }
}
Write-Host "  [OK] pyinstaller"

$PublishDir = Join-Path $Root "installer\publish"
$BuildDir = Join-Path $Root "build"
$DistDir = Join-Path $Root "dist"

if ($Clean) {
    foreach ($d in @($PublishDir, $BuildDir, $DistDir)) {
        if (Test-Path -LiteralPath $d) {
            Write-Host "  Cleaning $d"
            Remove-Item -LiteralPath $d -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# PyInstaller needs project requirements present in .venv for analysis.
Write-Host ""
Write-Host "==> Syncing requirements" -ForegroundColor Cyan
& $VenvPython -m pip install -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail "pip install -r requirements.txt failed." }

$IconArg = @()
$PngIcon = Join-Path $Root "ui\quill-icon.png"
$IcoIcon = Join-Path $Root "ui\quill-icon.ico"
if (Test-Path -LiteralPath $IcoIcon) {
    $IconArg = @("--icon", $IcoIcon)
} elseif (Test-Path -LiteralPath $PngIcon) {
    # PyInstaller accepts PNG and converts on Windows; fall back to no icon if it fails.
    $IconArg = @("--icon", $PngIcon)
}

Write-Host ""
Write-Host "==> Running PyInstaller (one-folder, windowed)" -ForegroundColor Cyan
$pyArgs = @(
    "-m", "PyInstaller",
    "--noconfirm", "--clean",
    "--onedir", "--windowed",
    "--name", "NovelTranslator",
    "--paths", $Root,
    "--add-data", "ui;ui",
    "--collect-all", "pykakasi",
    "--collect-all", "ebooklib",
    "--collect-all", "webview",
    "--hidden-import", "webview",
    "--hidden-import", "clr",
    "--exclude-module", "tkinter",
    "--distpath", (Join-Path $Root "dist"),
    "--workpath", $BuildDir,
    "--specpath", (Join-Path $Root "installer"),
    "app.py"
)
if ($IconArg.Count -gt 0) { $pyArgs += $IconArg }

& $VenvPython @pyArgs
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller failed (exit $LASTEXITCODE)." }

$BuiltExe = Join-Path $Root "dist\NovelTranslator\NovelTranslator.exe"
if (-not (Test-Path -LiteralPath $BuiltExe)) { Fail "Expected exe missing: $BuiltExe" }

New-Item -ItemType Directory -Force -Path $PublishDir | Out-Null
Copy-Item -Path (Join-Path $Root "dist\NovelTranslator\*") -Destination $PublishDir -Recurse -Force
if ($LASTEXITCODE -ne 0) { Fail "Copy to installer\publish failed." }

Write-Host ""
Write-Host "BUILD OK" -ForegroundColor Green
Write-Host "Publish: $PublishDir\NovelTranslator.exe"
exit 0
