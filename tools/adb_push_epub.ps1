# Push EPUB to Quest via adb (fallback when LAN import is down)
# Usage: .\tools\adb_push_epub.ps1 -Epub "C:\path\to\book.epub"
param(
  [Parameter(Mandatory = $true)]
  [string]$Epub
)

if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
  Write-Error "adb not on PATH. Install Android platform-tools."
  exit 1
}
if (-not (Test-Path $Epub)) {
  Write-Error "File not found: $Epub"
  exit 1
}

$name = Split-Path $Epub -Leaf
$remote = "/sdcard/Download/$name"
adb push $Epub $remote
Write-Host "Pushed to $remote"
Write-Host "On the headset, open SpatialLauncher → EPUB button → pick this file (or Files app → Download)."
