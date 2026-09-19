# Novel Translator

Windows desktop app. Double-click **Start Novel Translator.bat**. The easy installer looks for Python, tkinter, pip, and the packages in `requirements.txt`. If something is missing it installs the right one (winget or the official Python installer, then pip), then prints **READY TO GO: YES** and opens the app.

**Check Everything.bat** runs the same checks and stops so you can read the results.

Paste either:

- the novel page, e.g. `https://ncode.syosetu.com/n4830bu/`
- or the PDF page, e.g. `https://ncode.syosetu.com/novelpdf/creatingpdf/ncode/n4830bu/`

You do not need a direct PDF link. **Official vertical PDF** downloads Syosetu’s generated file. **Novel chapters** is usually better for translation because those PDFs often have little selectable text.

Then: **Download** → **Translate and fix grammar** → **Save EPUB**.

Python 3 must be installed once, with “Add python.exe to PATH” checked: https://www.python.org/downloads/

Personal reading only. Do not redistribute translations.
