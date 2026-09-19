from __future__ import annotations

import importlib
import sys
import tkinter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "bs4": "beautifulsoup4",
    "ebooklib": "ebooklib",
    "httpx": "httpx",
    "lxml": "lxml",
    "pypdf": "pypdf",
    "webview": "pywebview",
}
APP_MODULES = [
    "novel_translator.config",
    "novel_translator.syosetu",
    "novel_translator.pdf_download",
    "novel_translator.pdf_import",
    "novel_translator.translate",
    "novel_translator.epub_export",
    "novel_translator.library",
    "novel_translator.reader",
    "novel_translator.bridge",
    "novel_translator.wiki_lookup",
    "novel_translator.ollama_web",
    "novel_translator.recommendations",
    "novel_translator.headset_send",
]


def check(name: str, ok: bool, detail: str = "") -> bool:
    mark = "OK" if ok else "FAIL"
    extra = f" — {detail}" if detail else ""
    print(f"  [{mark}] {name}{extra}")
    return ok


def main() -> int:
    print("Novel Translator — ready check")
    print("-" * 40)
    failed = 0

    if not check("Python 3.10+", sys.version_info >= (3, 10), sys.version.split()[0]):
        failed += 1

    try:
        tkinter.Tk().destroy()
        tk_ok = True
        tk_detail = "tkinter window toolkit"
    except Exception as exc:
        tk_ok = False
        tk_detail = str(exc)
    if not check("Windows GUI toolkit", tk_ok, tk_detail):
        failed += 1

    if not check("app.py", (ROOT / "app.py").is_file(), str(ROOT / "app.py")):
        failed += 1
    if not check("requirements.txt", (ROOT / "requirements.txt").is_file()):
        failed += 1

    for module, package in REQUIRED.items():
        try:
            imported = importlib.import_module(module)
            detail = getattr(imported, "__version__", package)
            ok = True
        except Exception as exc:
            ok = False
            detail = str(exc)
        if not check(f"package {package}", ok, str(detail)):
            failed += 1

    sys.path.insert(0, str(ROOT))
    for module in APP_MODULES:
        try:
            importlib.import_module(module)
            ok = True
            detail = ""
        except Exception as exc:
            ok = False
            detail = str(exc)
        if not check(f"module {module}", ok, detail):
            failed += 1

    print("-" * 40)
    if failed:
        print(f"READY TO GO: NO ({failed} check(s) failed)")
        return 1
    print("READY TO GO: YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
