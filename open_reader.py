from __future__ import annotations

import sys
from pathlib import Path
from tkinter import Tk

from novel_translator.reader import EpubReader

if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if not path:
        raise SystemExit("usage: open_reader.py file.epub")
    root = Tk()
    root.withdraw()
    EpubReader(root, path)
    root.mainloop()
