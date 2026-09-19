# Novel Translator uninstall (per-user)
# Removes app files, Start Menu shortcut, and Apps & Features entry.
# Books in Documents\NovelTranslator and config in %USERPROFILE%\.novel_translator are kept unless -RemoveData.

param(
    [switch]$RemoveData,
    [switch]$Silent
)

$ErrorActionPreference = "Continue"
Add-Type -AssemblyName System.Windows.Forms | Out-Null
$Root = Join-Path $env:LOCALAPPDATA "NovelTranslator"
$InstallDir = Join-Path $Root "app"
$StartMenuLnk = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Novel Translator.lnk"
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\NovelTranslator"

if (-not $Silent) {
    $msg = "Uninstall Novel Translator from:`n$InstallDir"
    if ($RemoveData) { $msg += "`n`nAlso remove books and settings." }
    $r = [System.Windows.Forms.MessageBox]::Show(
        $msg, "Uninstall Novel Translator",
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question)
    if ($r -ne [System.Windows.Forms.DialogResult]::Yes) { exit 0 }
}

Get-Process -Name "NovelTranslator" -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 500

if (Test-Path -LiteralPath $StartMenuLnk) {
    Remove-Item -LiteralPath $StartMenuLnk -Force -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $InstallDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
}

if ($RemoveData) {
    $books = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "NovelTranslator"
    if (Test-Path -LiteralPath $books) {
        Remove-Item -LiteralPath $books -Recurse -Force -ErrorAction SilentlyContinue
    }
    $cfg = Join-Path $env:USERPROFILE ".novel_translator"
    if (Test-Path -LiteralPath $cfg) {
        Remove-Item -LiteralPath $cfg -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if ((Test-Path -LiteralPath $Root) -and -not (Get-ChildItem -LiteralPath $Root -Force -ErrorAction SilentlyContinue)) {
    Remove-Item -LiteralPath $Root -Force -ErrorAction SilentlyContinue
}

Remove-Item -Path $UninstallKey -Recurse -Force -ErrorAction SilentlyContinue

if (-not $Silent) {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
    [System.Windows.Forms.MessageBox]::Show(
        "Novel Translator was removed.",
        "Uninstall complete",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
}
exit 0
