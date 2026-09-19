# Novel Translator

Windows desktop app to download Syosetu novels, translate them, and save EPUBs.

## Install and run

**Option A — Quick run (dev folder, recommended to start):**

1. Clone or unzip this repo, keep the folder together.
2. Double-click **Start Novel Translator.bat**.
   - Checks Python 3.10+ with tkinter, creates `.venv/`, installs `requirements.txt`, runs `tools/doctor.py`.
   - Installs missing Python via winget or the official installer if needed.
   - Prints `READY TO GO: YES` then opens the app (`app.py` via pywebview).

**Option B — Installed app (Start Menu + Settings > Apps):**

1. Double-click **Install Novel Translator.bat**.
   - Calls `tools/desktop_install.ps1`, which builds the exe with PyInstaller to `installer/publish/`, then copies it to `%LocalAppData%\NovelTranslator\app\NovelTranslator.exe`.
   - Creates Start Menu shortcut `Novel Translator` and an uninstall entry `Novel Translator`.
2. Launch from Start Menu afterward.

**Option C — Setup.exe (Inno Setup, like SpatialLauncher):**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_exe.ps1
iscc installer\NovelTranslator.iss
```

Output: `installer\NovelTranslator-Setup.exe`. Installs per-user to `%LocalAppData%\NovelTranslator\app`.

**Manual run:**

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python tools\doctor.py
python app.py
```

**Check only:** **Check Everything.bat** runs the same checks and pauses so you can read the results.

Needs Windows 10/11 x64 + internet. Python 3 installs once with “Add python.exe to PATH” checked: https://www.python.org/downloads/ — WebView2 is used for the window (already on most Windows installs).

Paste either:

- the novel page, e.g. `https://ncode.syosetu.com/n4830bu/`
- or the PDF page, e.g. `https://ncode.syosetu.com/novelpdf/creatingpdf/ncode/n4830bu/`

You do not need a direct PDF link. **Official vertical PDF** downloads Syosetu’s generated file. **Novel chapters** is usually better for translation because those PDFs often have little selectable text.

Then: **Download** → **Translate and fix grammar** → **Save EPUB**.

Files: app install in `%LocalAppData%\NovelTranslator\app`, books in `Documents\NovelTranslator`, settings in `%USERPROFILE%\.novel_translator`. Uninstall via Settings > Apps > Novel Translator (books/settings kept unless removed with `-RemoveData`).

Python 3 must be installed once, with “Add python.exe to PATH” checked: https://www.python.org/downloads/

Personal reading only. Do not redistribute translations.
