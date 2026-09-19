from __future__ import annotations

import ctypes
import shutil
import traceback
from pathlib import Path

import webview

from novel_translator.bridge import Bridge
from novel_translator.win_glass import enable_system_backdrop

UI = Path(__file__).resolve().parent / "ui" / "index.html"
ICON_PNG = UI.parent / "quill-icon.png"


def copy_desktop_wallpaper() -> str:
    buf = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.SystemParametersInfoW(0x0073, 512, buf, 0)
    src = Path(buf.value)
    if not src.exists():
        return ""
    dest = UI.parent / f"desktop-bg{src.suffix.lower() or '.jpg'}"
    try:
        shutil.copyfile(src, dest)
    except OSError:
        return ""
    return dest.name


def apply_window_icon(window) -> None:
    native = getattr(window, "native", None)
    if not ICON_PNG.exists() or native is None:
        return
    from System.Drawing import Bitmap, Graphics, Icon
    from System.Drawing.Drawing2D import InterpolationMode

    src = Bitmap(str(ICON_PNG))
    dest = Bitmap(32, 32)
    g = Graphics.FromImage(dest)
    g.InterpolationMode = InterpolationMode.HighQualityBicubic
    g.DrawImage(src, 0, 0, 32, 32)
    g.Dispose()
    native.Icon = Icon.FromHandle(dest.GetHicon()).Clone()


def main() -> None:
    api = Bridge()
    api.wallpaper = copy_desktop_wallpaper()
    window = webview.create_window(
        "Novel Translator",
        UI.as_uri(),
        js_api=api,
        width=1320,
        height=860,
        min_size=(1080, 700),
        background_color="#1c2028",
    )
    api._ui = window

    def on_loaded():
        api.system_glass = enable_system_backdrop(window)
        try:
            from System import Action

            window.native.BeginInvoke(Action(lambda: apply_window_icon(window)))
        except Exception:
            pass

    window.events.loaded += on_loaded
    webview.start(debug=False)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_path = Path.home() / "Documents" / "NovelTranslator" / "crash.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        raise
