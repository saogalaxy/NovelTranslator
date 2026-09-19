from __future__ import annotations

import re
import subprocess
import threading
import time
import webbrowser
from pathlib import Path
import tkinter as tk

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

BG = "#1a2332"
PANEL = "#243044"
READ = "#1e2a3a"
FG = "#f4f6fa"
MUTED = "#c5cdd8"
ORANGE = "#ff7a18"
ORANGE_FG = "#1a1208"
FOLLOW = "#3d2a12"


def _clean_title(title: str) -> str:
    name = (title or "").strip()
    name = re.sub(r"^(chapter\s*title\s*:)\s*", "", name, flags=re.I)
    name = re.sub(r"^chapter\s+\d+\s*:\s*", "", name, flags=re.I)
    return name.strip() or title or "Chapter"


def _strip_echo(title: str, body: str) -> str:
    needle = _clean_title(title).lower()
    lines = (body or "").splitlines()
    while lines:
        raw = lines[0].strip().lower().lstrip("# ")
        if not raw or raw == needle or raw.startswith("chapter title:"):
            lines.pop(0)
            continue
        break
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [part.strip() for part in parts if part.strip()]


def split_play_units(text: str) -> list[str]:
    units: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        bits = split_sentences(line)
        units.extend(bits or [line])
    return units


def load_epub_pages(path: str | Path) -> tuple[str, list[tuple[str, str]]]:
    book = epub.read_epub(str(path), options={"ignore_ncx": True})
    title = book.get_metadata("DC", "title")
    book_title = title[0][0] if title else Path(path).stem
    pages: list[tuple[str, str]] = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        name = item.get_name().lower()
        if "nav" in name or name.endswith("toc.xhtml"):
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        heading = soup.find(["h1", "h2"])
        heading_text = _clean_title(heading.get_text(" ", strip=True) if heading else Path(item.get_name()).stem)
        for tag in soup(["script", "style", "title"]):
            tag.decompose()
        if heading:
            heading.decompose()
        body = _strip_echo(heading_text, soup.get_text("\n"))
        if body:
            pages.append((heading_text or f"Chapter {len(pages) + 1}", body))
    if not pages:
        pages.append((book_title, "This EPUB has no readable chapters."))
    return book_title, pages


def _infer_ncode(path: Path) -> str:
    parts = [p.lower() for p in Path(path).parts]
    for i, part in enumerate(parts):
        if part == "books" and i + 1 < len(parts):
            candidate = parts[i + 1]
            if re.fullmatch(r"n\d+[a-z0-9]+", candidate):
                return candidate
    match = re.search(r"(n\d+[a-z0-9]+)", Path(path).stem.lower())
    return match.group(1) if match else ""


def _speech_synth():
    try:
        import clr

        clr.AddReference("System.Speech")
        from System.Speech.Synthesis import SpeechSynthesizer

        return SpeechSynthesizer()
    except Exception:
        return None


class Voice:
    def __init__(self) -> None:
        self.synth = _speech_synth()
        self._proc: subprocess.Popen | None = None
        self.on_word = None
        self.rate = 0
        self._cancelled = False
        if self.synth is not None:
            try:
                self.synth.SpeakProgress += self._on_progress
            except Exception:
                pass

    def set_speed(self, multiplier: float) -> None:
        speed = max(0.6, min(2.0, float(multiplier)))
        if speed >= 1.0:
            raw = (speed - 1.0) * 10
        else:
            raw = (speed - 1.0) / 0.4 * 10
        self.rate = max(-10, min(10, int(round(raw))))
        if self.synth is not None:
            try:
                self.synth.Rate = self.rate
            except Exception:
                pass

    def _on_progress(self, _sender, args) -> None:
        if self.on_word:
            try:
                self.on_word(int(args.CharacterPosition), int(args.CharacterCount))
            except Exception:
                pass

    def speak(self, text: str) -> bool:
        spoken = (text or "").strip()
        self._cancelled = False
        if not spoken:
            return True
        if self.synth is not None:
            try:
                self.synth.Rate = self.rate
                self.synth.Speak(spoken)
            except Exception:
                return False
            return not self._cancelled
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        quoted = spoken.replace("'", "''")
        self._proc = subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-Command",
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$s.Rate = {int(self.rate)}; "
                f"$s.Speak('{quoted}')",
            ],
            startupinfo=info,
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._proc.wait()
        self._proc = None
        return not self._cancelled

    def cancel(self) -> None:
        self._cancelled = True
        try:
            if self.synth is not None:
                self.synth.SpeakAsyncCancelAll()
        except Exception:
            pass
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self._proc = None


class Chip(tk.Button):
    def __init__(self, master: tk.Misc, primary: bool = False, **kwargs) -> None:
        bg = ORANGE if primary else "#35465c"
        fg = ORANGE_FG if primary else FG
        super().__init__(
            master,
            bg=bg,
            fg=fg,
            activebackground="#ff9a3c" if primary else "#41536c",
            activeforeground=fg,
            relief="flat",
            bd=0,
            padx=10,
            pady=6,
            cursor="hand2",
            font=("Segoe UI", 10, "bold" if primary else "normal"),
            **kwargs,
        )


class EpubReader(tk.Toplevel):
    def __init__(self, master: tk.Misc, path: str | Path) -> None:
        super().__init__(master)
        self.path = Path(path)
        self.book_title, self.pages = load_epub_pages(self.path)
        self.index = 0
        self.font_size = 15
        self.voice = Voice()
        self.sentences: list[str] = []
        self.sent_i = 0
        self.playing = False
        self.paused = False
        self._lock = threading.Lock()
        self._setting_scrub = False
        self._replay = False
        self._discover_loaded = False
        self._ncode = _infer_ncode(self.path)
        self.configure(bg=BG)
        self.title(f"{self.book_title} — Reader")
        self.geometry("1040x740")
        self.minsize(760, 520)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build()
        self._show()

    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)

        bar = tk.Frame(self, bg=PANEL)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(12, 6))
        Chip(bar, text="Previous", command=self._prev).pack(side="left", padx=(8, 4), pady=8)
        Chip(bar, text="Next", command=self._next).pack(side="left", padx=4, pady=8)
        Chip(bar, text="A−", command=lambda: self._font(-1)).pack(side="left", padx=(16, 4), pady=8)
        Chip(bar, text="A+", command=lambda: self._font(1)).pack(side="left", padx=4, pady=8)
        self.pos = tk.Label(bar, text="", bg=PANEL, fg=MUTED, font=("Segoe UI", 10))
        self.pos.pack(side="left", padx=16)
        tk.Label(bar, text=self.book_title, bg=PANEL, fg=FG, font=("Segoe UI", 10)).pack(side="right", padx=12)

        play = tk.Frame(self, bg=PANEL)
        play.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 6))
        self.play_btn = Chip(play, primary=True, text="Play", command=self._toggle_play)
        self.play_btn.pack(side="left", padx=(8, 4), pady=8)
        Chip(play, text="Stop", command=self._stop).pack(side="left", padx=4, pady=8)
        Chip(play, text="⟵ Line", command=self._prev_sentence).pack(side="left", padx=4, pady=8)
        Chip(play, text="Line ⟶", command=self._next_sentence).pack(side="left", padx=4, pady=8)
        tk.Label(play, text="Speed", bg=PANEL, fg=MUTED, font=("Segoe UI", 10)).pack(side="left", padx=(16, 4))
        self.speed = tk.Scale(
            play,
            from_=0.6,
            to=2.0,
            resolution=0.1,
            orient="horizontal",
            length=140,
            bg=PANEL,
            fg=FG,
            highlightthickness=0,
            troughcolor=READ,
            command=self._set_speed,
        )
        self.speed.set(1.0)
        self.speed.pack(side="left")
        self.speed_lbl = tk.Label(play, text="1.0×", bg=PANEL, fg=FG, font=("Segoe UI", 10))
        self.speed_lbl.pack(side="left", padx=(4, 8))
        self.scrub = tk.Scale(
            play,
            from_=0,
            to=1,
            orient="horizontal",
            length=220,
            bg=PANEL,
            fg=FG,
            highlightthickness=0,
            troughcolor=READ,
            command=self._scrub,
        )
        self.scrub.pack(side="left", padx=12)
        self.follow = tk.Label(play, text="Click a line or drag the bar to scrub", bg=PANEL, fg=MUTED, font=("Segoe UI", 10))
        self.follow.pack(side="left", padx=8)

        side = tk.Frame(self, bg=PANEL)
        side.grid(row=2, column=0, sticky="nsw", padx=(12, 0), pady=(0, 12))
        tabs = tk.Frame(side, bg=PANEL)
        tabs.pack(fill="x", padx=8, pady=(10, 4))
        self.tab_chapters = Chip(tabs, text="Chapters", command=lambda: self._show_side("chapters"))
        self.tab_chapters.pack(side="left", padx=(0, 4))
        self.tab_discover = Chip(tabs, text="Discover", command=lambda: self._show_side("discover"))
        self.tab_discover.pack(side="left")

        self.chapters_panel = tk.Frame(side, bg=PANEL)
        self.chapters_panel.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(
            self.chapters_panel,
            width=32,
            font=("Segoe UI", 10),
            exportselection=False,
            bg=READ,
            fg=FG,
            selectbackground=ORANGE,
            selectforeground=ORANGE_FG,
            highlightthickness=0,
            bd=0,
            activestyle="none",
        )
        self.listbox.pack(fill="both", expand=True, padx=8, pady=(0, 10))
        for title, _body in self.pages:
            self.listbox.insert("end", title)
        self.listbox.bind("<<ListboxSelect>>", self._from_list)

        self.discover_panel = tk.Frame(side, bg=PANEL)
        self.discover_status = tk.Label(
            self.discover_panel,
            text="Open Discover to load official releases and similar titles.",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
            wraplength=220,
            justify="left",
        )
        self.discover_status.pack(anchor="w", padx=10, pady=(0, 6))
        wrap = tk.Frame(self.discover_panel, bg=PANEL)
        wrap.pack(fill="both", expand=True, padx=4, pady=(0, 8))
        self.discover_canvas = tk.Canvas(wrap, bg=READ, highlightthickness=0, width=250)
        scroll = tk.Scrollbar(wrap, orient="vertical", command=self.discover_canvas.yview, bg=PANEL, troughcolor=BG)
        self.discover_inner = tk.Frame(self.discover_canvas, bg=READ)
        self.discover_inner.bind(
            "<Configure>",
            lambda _e: self.discover_canvas.configure(scrollregion=self.discover_canvas.bbox("all")),
        )
        self.discover_canvas.create_window((0, 0), window=self.discover_inner, anchor="nw")
        self.discover_canvas.configure(yscrollcommand=scroll.set)
        self.discover_canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._side_mode = "chapters"
        self._style_side_tabs()

        frame = tk.Frame(self, bg=BG)
        frame.grid(row=2, column=1, sticky="nsew", padx=12, pady=(0, 12))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.text = tk.Text(
            frame,
            wrap="word",
            font=("Georgia", self.font_size),
            padx=22,
            pady=18,
            background=READ,
            foreground=FG,
            insertbackground=FG,
            relief="flat",
            highlightthickness=0,
            spacing1=2,
            spacing3=8,
        )
        scroll = tk.Scrollbar(frame, orient="vertical", command=self.text.yview, bg=PANEL, troughcolor=BG)
        self.text.configure(yscrollcommand=scroll.set, state="disabled")
        self.text.tag_configure("heading", font=("Segoe UI Semibold", self.font_size + 6), foreground=ORANGE, spacing3=14)
        self.text.tag_configure("follow", background=FOLLOW, foreground="#ffe3c2")
        self.text.tag_configure("word", background="#ff7a18", foreground="#1a1208")
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.text.bind("<Button-1>", self._click_unit)
        self.bind("<Left>", lambda _e: self._prev())
        self.bind("<Right>", lambda _e: self._next())
        self.bind("<space>", lambda _e: self._toggle_play())
        self.voice.on_word = self._word_progress
        self._setting_scrub = False

    def _font(self, delta: int) -> None:
        self.font_size = min(28, max(11, self.font_size + delta))
        self.text.configure(font=("Georgia", self.font_size))
        self.text.tag_configure("heading", font=("Segoe UI Semibold", self.font_size + 6), foreground=ORANGE, spacing3=14)

    def _style_side_tabs(self) -> None:
        chapters = self._side_mode == "chapters"
        self.tab_chapters.configure(
            bg=ORANGE if chapters else "#41536c",
            fg=ORANGE_FG if chapters else FG,
        )
        self.tab_discover.configure(
            bg=ORANGE if not chapters else "#41536c",
            fg=ORANGE_FG if not chapters else FG,
        )

    def _show_side(self, mode: str) -> None:
        self._side_mode = mode
        self._style_side_tabs()
        if mode == "discover":
            self.chapters_panel.pack_forget()
            self.discover_panel.pack(fill="both", expand=True)
            if not self._discover_loaded:
                self._load_discover()
        else:
            self.discover_panel.pack_forget()
            self.chapters_panel.pack(fill="both", expand=True)

    def _load_discover(self) -> None:
        self.discover_status.configure(text="Loading official releases and similar titles…")
        for child in self.discover_inner.winfo_children():
            child.destroy()

        def work() -> None:
            try:
                from novel_translator.recommendations import recommend_for_title

                data = recommend_for_title(self.book_title, self._ncode)
            except Exception as exc:
                data = {"error": str(exc), "official": {}, "similar": []}
            self.after(0, lambda: self._render_discover(data))

        threading.Thread(target=work, daemon=True).start()

    def _render_discover(self, data: dict) -> None:
        self._discover_loaded = True
        for child in self.discover_inner.winfo_children():
            child.destroy()
        if data.get("error"):
            self.discover_status.configure(text=f"Could not load Discover: {data['error']}")
            return
        official = data.get("official") or {}
        similar = data.get("similar") or []
        msg = data.get("message") or ""
        self.discover_status.configure(text=msg or "Official releases for this book + similar upcoming titles.")

        tk.Label(
            self.discover_inner,
            text="Official releases",
            bg=READ,
            fg=ORANGE,
            font=("Segoe UI Semibold", 10),
            anchor="w",
        ).pack(fill="x", padx=8, pady=(8, 2))
        if official.get("found"):
            bits = []
            if official.get("official_title"):
                bits.append(official["official_title"])
            if official.get("available"):
                bits.append("Available as " + ", ".join(official["available"]))
            if official.get("publishers"):
                bits.append("Publishers: " + ", ".join(official["publishers"][:4]))
            tk.Label(
                self.discover_inner,
                text=" · ".join(bits) or "Official listing found.",
                bg=READ,
                fg=FG,
                font=("Segoe UI", 9),
                wraplength=220,
                justify="left",
                anchor="w",
            ).pack(fill="x", padx=8, pady=(0, 4))
            for link in (official.get("links") or [])[:5]:
                url = link.get("url") or ""
                label = link.get("label") or url
                Chip(
                    self.discover_inner,
                    text=label[:40],
                    command=lambda u=url: webbrowser.open(u) if u else None,
                ).pack(anchor="w", padx=8, pady=2)
        else:
            tk.Label(
                self.discover_inner,
                text="No official listing cached for this book yet.",
                bg=READ,
                fg=MUTED,
                font=("Segoe UI", 9),
                wraplength=220,
                justify="left",
                anchor="w",
            ).pack(fill="x", padx=8, pady=(0, 6))

        tk.Label(
            self.discover_inner,
            text="Similar / upcoming",
            bg=READ,
            fg=ORANGE,
            font=("Segoe UI Semibold", 10),
            anchor="w",
        ).pack(fill="x", padx=8, pady=(10, 4))
        if not similar:
            tk.Label(
                self.discover_inner,
                text="No similar titles yet. Open Recommended in the main app to refresh LiveChart.",
                bg=READ,
                fg=MUTED,
                font=("Segoe UI", 9),
                wraplength=220,
                justify="left",
                anchor="w",
            ).pack(fill="x", padx=8, pady=(0, 8))
            return
        for item in similar:
            card = tk.Frame(self.discover_inner, bg=PANEL, padx=6, pady=6)
            card.pack(fill="x", padx=6, pady=4)
            title = item.get("title_en") or item.get("official_title") or "Untitled"
            jp = item.get("title_jp") or ""
            badge = "  · Syosetu" if item.get("has_webnovel") else ""
            tk.Label(card, text=title + badge, bg=PANEL, fg=FG, font=("Segoe UI Semibold", 9), wraplength=210, justify="left", anchor="w").pack(fill="x")
            if jp:
                tk.Label(card, text=jp, bg=PANEL, fg=MUTED, font=("Segoe UI", 8), wraplength=210, justify="left", anchor="w").pack(fill="x")
            ncode = item.get("ncode") or ""
            web = item.get("webnovel_url") or ""
            if ncode or web:
                tk.Label(
                    card,
                    text=web or ncode,
                    bg=PANEL,
                    fg="#9ecbff",
                    font=("Segoe UI", 8),
                    wraplength=210,
                    justify="left",
                    anchor="w",
                ).pack(fill="x", pady=(2, 0))
            row = tk.Frame(card, bg=PANEL)
            row.pack(fill="x", pady=(4, 0))
            live = item.get("livechart_url") or ""
            if live:
                Chip(row, text="LiveChart", command=lambda u=live: webbrowser.open(u)).pack(side="left", padx=(0, 4))
            if web:
                Chip(row, text="Syosetu", command=lambda u=web: webbrowser.open(u)).pack(side="left")

    def _from_list(self, _event=None) -> None:
        selection = self.listbox.curselection()
        if selection:
            self.index = int(selection[0])
            self._show()

    def _prev(self) -> None:
        if self.index > 0:
            self.index -= 1
            self._show()

    def _next(self) -> None:
        if self.index < len(self.pages) - 1:
            self.index += 1
            self._show()

    def _toggle_play(self) -> None:
        if self.playing and not self.paused:
            self.paused = True
            self.voice.cancel()
            self.play_btn.configure(text="Play")
            return
        if self.playing and self.paused:
            self.paused = False
            self.play_btn.configure(text="Pause")
            return
        self.playing = True
        self.paused = False
        self.play_btn.configure(text="Pause")
        threading.Thread(target=self._play_loop, daemon=True).start()

    def _stop(self) -> None:
        self.playing = False
        self.paused = False
        self.voice.cancel()
        self.play_btn.configure(text="Play")
        self.after(0, lambda: self._highlight(-1))

    def _set_speed(self, value) -> None:
        speed = float(value)
        self.voice.set_speed(speed)
        if getattr(self, "speed_lbl", None):
            self.speed_lbl.configure(text=f"{speed:.1f}×")
        if self.playing and not self.paused:
            self._replay = True
            self.voice.cancel()

    def _scrub(self, value) -> None:
        if self._setting_scrub or not self.sentences:
            return
        nxt = max(0, min(len(self.sentences) - 1, int(float(value))))
        if nxt == self.sent_i:
            return
        self.sent_i = nxt
        self.voice.cancel()
        self._highlight(self.sent_i)

    def _click_unit(self, event) -> None:
        index = self.text.index(f"@{event.x},{event.y}")
        for i in range(len(self.sentences)):
            ranges = self.text.tag_ranges(f"sent-{i}")
            if not ranges:
                continue
            if self.text.compare(ranges[0], "<=", index) and self.text.compare(index, "<", ranges[1]):
                self.sent_i = i
                self.voice.cancel()
                self._highlight(i)
                return

    def _word_progress(self, start: int, count: int) -> None:
        self.after(0, lambda: self._paint_word(start, count))

    def _paint_word(self, start: int, count: int) -> None:
        ranges = self.text.tag_ranges(f"sent-{self.sent_i}")
        if not ranges:
            return
        self.text.tag_remove("word", "1.0", "end")
        begin = f"{ranges[0]}+{max(start, 0)}c"
        end = f"{ranges[0]}+{max(start + max(count, 1), 1)}c"
        self.text.tag_add("word", begin, end)
        self.text.see(begin)

    def _prev_sentence(self) -> None:
        self.sent_i = max(0, self.sent_i - 1)
        self.voice.cancel()
        self._highlight(self.sent_i)

    def _next_sentence(self) -> None:
        if self.sentences:
            self.sent_i = min(len(self.sentences) - 1, self.sent_i + 1)
        self.voice.cancel()
        self._highlight(self.sent_i)

    def _play_loop(self) -> None:
        while self.playing and self.sent_i < len(self.sentences):
            if self.paused:
                time.sleep(0.15)
                continue
            idx = self.sent_i
            self.after(0, lambda i=idx: self._highlight(i))
            try:
                finished = self.voice.speak(self.sentences[idx])
            except Exception:
                self.playing = False
                break
            if not self.playing:
                break
            if self.paused:
                continue
            if self._replay:
                self._replay = False
                continue
            if not finished:
                continue
            self.sent_i += 1
        if self.playing and self.sent_i >= len(self.sentences):
            self.playing = False
            self.after(0, lambda: self.play_btn.configure(text="Play"))
            self.after(0, lambda: self._highlight(-1))

    def _highlight(self, index: int) -> None:
        self.text.tag_remove("follow", "1.0", "end")
        self.text.tag_remove("word", "1.0", "end")
        tag = f"sent-{index}"
        if index >= 0:
            ranges = self.text.tag_ranges(tag)
            if ranges:
                self.text.tag_add("follow", ranges[0], ranges[1])
                self.text.see(ranges[0])
        self._setting_scrub = True
        if self.sentences:
            self.scrub.configure(command="")
            self.scrub.configure(to=max(len(self.sentences) - 1, 1))
            self.scrub.set(max(index, 0))
            self.scrub.configure(command=self._scrub)
        self._setting_scrub = False
        self.follow.configure(text=f"Line {max(index, 0) + 1} / {max(len(self.sentences), 1)}")

    def _show(self) -> None:
        self._stop()
        title, body = self.pages[self.index]
        body = _strip_echo(title, body)
        self.sentences = split_play_units(body)
        self.sent_i = 0
        self._setting_scrub = True
        self.scrub.configure(to=max(len(self.sentences) - 1, 1))
        self.scrub.set(0)
        self._setting_scrub = False
        self.pos.config(text=f"{self.index + 1} / {len(self.pages)}")
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(self.index)
        self.listbox.see(self.index)
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", title + "\n\n", "heading")
        for i, sentence in enumerate(self.sentences):
            start = self.text.index("end-1c")
            self.text.insert("end", sentence + ("\n\n" if i < len(self.sentences) - 1 else ""))
            end = self.text.index("end-1c")
            self.text.tag_add(f"sent-{i}", start, end)
        self.text.configure(state="disabled")
        self.text.see("1.0")
        self.follow.configure(text="TTS follows the highlighted sentence")

    def _close(self) -> None:
        self._stop()
        self.destroy()
        master = self.master
        if isinstance(master, tk.Tk):
            master.quit()
