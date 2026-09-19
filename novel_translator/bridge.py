from __future__ import annotations

import json
import threading
import traceback
from pathlib import Path
import subprocess
import sys

from novel_translator.config import load_config, save_config
from novel_translator.epub_export import english_filename, export_epub
from novel_translator.google_draft import google_translate
from novel_translator.library import (
    apply_official_names,
    chapter_entry,
    expand_glossary_aliases,
    fill_english_chapter_titles,
    _has_japanese,
    display_author,
    display_book_title,
    existing_novel,
    load_index,
    load_novel,
    merge_existing_work,
    plan_range,
    save_novel,
    translated_count,
    union_chapters,
)
from novel_translator.models import Novel
from novel_translator.pdf_download import download_official_pdf
from novel_translator.pdf_import import import_pdf
from novel_translator.providers import OLLAMA_OPENAI, list_ollama_models
from novel_translator.syosetu import fetch_novel, novel_page_url, parse_ncode, series_info
from novel_translator.translate import translate_novel
from novel_translator.headset_send import discover_headset, probe_headset, send_epub_file
from novel_translator.recommendations import list_upcoming, peek_cache, recommend_for_title
from novel_translator.wiki_lookup import (
    describe_official,
    enrich_official_names,
    lookup_official,
    official_glossary,
)


class Bridge:
    def __init__(self) -> None:
        self._ui = None
        self.cfg = load_config()
        self.novel: Novel | None = None
        self.busy = False
        self._events: list[dict] = []
        self._lock = threading.Lock()
        self.wallpaper = ""
        self.system_glass = False
        self.official: dict = {}
        self._progress_value = 0.0
        self._rec_busy = False
        self._recommendations: dict = {}

    def _status(self, text: str, value: float | None = None, log: bool = False) -> None:
        if value is None:
            value = self._progress_value
        self._progress_value = max(0.0, min(1.0, float(value)))
        self._emit("progress", {"text": text, "value": self._progress_value})
        if log:
            self._emit("log", text)

    def _emit(self, name: str, payload) -> None:
        with self._lock:
            self._events.append({"name": name, "payload": payload})

    def pull_events(self) -> list[dict]:
        with self._lock:
            batch = list(self._events)
            self._events.clear()
        return batch

    def _out_dir(self) -> Path:
        return Path(self.cfg.get("output_dir") or Path.home() / "Documents" / "NovelTranslator")

    def _library_payload(self) -> dict:
        glossary = self.cfg.get("glossary") or ""
        books = []
        for book in load_index(self._out_dir()):
            original_author = book.get("original_author") or ""
            original_title = book.get("original_title") or ""
            path = book.get("book_json") or ""
            if path and Path(path).exists() and (not original_author or not original_title):
                try:
                    stored = load_novel(path)
                    original_author = original_author or stored.original_author or (
                        stored.author if any("\u3040" <= ch <= "\u9fff" for ch in stored.author) else ""
                    )
                    original_title = original_title or stored.original_title
                except Exception:
                    pass
            author = book.get("author") or ""
            official_file = self._official_path(book.get("ncode") or "")
            extra_glossary = glossary
            if official_file.exists():
                try:
                    official = json.loads(official_file.read_text(encoding="utf-8"))
                    extra_glossary = glossary + "\n" + official_glossary(official, original_author)
                    if official.get("author_english") and not _has_japanese(official["author_english"]):
                        author = official["author_english"]
                    if official.get("official_title"):
                        book = {**book, "title": official["official_title"]}
                except Exception:
                    pass
            ncode = book.get("ncode") or ""
            source_url = book.get("source_url") or ""
            if path and Path(path).exists() and not source_url:
                try:
                    stored = load_novel(path)
                    source_url = stored.source_url
                except Exception:
                    source_url = ""
            books.append(
                {
                    **book,
                    "source_url": novel_page_url(ncode, source_url),
                    "display_title": display_book_title(
                        book.get("title") or "",
                        book.get("ncode") or "",
                        extra_glossary,
                        original_title,
                    ),
                    "display_author": display_author(
                        author,
                        extra_glossary,
                        original_author,
                        book.get("ncode") or "",
                    ),
                }
            )
        chapters = []
        if self.novel:
            ch_gloss = glossary + "\n" + official_glossary(
                self.official, self.novel.original_author or ""
            )
            for ch in self.novel.chapters:
                chapters.append(
                    chapter_entry(
                        ch.number,
                        ch.title,
                        bool(ch.translated_text.strip()),
                        ch.original_title,
                        ch_gloss,
                    )
                )
        selected = ""
        selected_url = ""
        resume_start = ""
        if self.novel:
            selected = display_book_title(
                self.novel.title, self.novel.ncode, glossary, self.novel.original_title
            )
            selected_url = novel_page_url(self.novel.ncode, self.novel.source_url)
            last = max(
                (ch.number for ch in self.novel.chapters if (ch.source_text or "").strip()),
                default=0,
            )
            resume_start = str(last + 1 if last else 1)
        return {
            "books": books,
            "chapters": chapters,
            "selected": selected,
            "url": selected_url,
            "resume_start": resume_start,
        }

    def state(self) -> dict:
        models = list_ollama_models() if self.cfg.get("provider", "ollama") == "ollama" else []
        self._seed_url_history_from_library()
        return {
            "config": {
                "url": "https://ncode.syosetu.com/n4830bu/",
                "mode": "chapters",
                "start": "1",
                "end": "3",
                "target_language": self.cfg.get("target_language", "English"),
                "provider": self.cfg.get("provider", "ollama"),
                "model": self.cfg.get("model") or (models[0] if models else ""),
                "api_key": self.cfg.get("api_key", ""),
                "api_base": self.cfg.get("api_base", OLLAMA_OPENAI),
                "output_dir": self.cfg.get("output_dir", str(self._out_dir())),
                "glossary": self.cfg.get("glossary") or "",
                "headset_host": self.cfg.get("headset_host") or "",
                "headset_port": int(self.cfg.get("headset_port") or 8765),
                "headset_token": self.cfg.get("headset_token") or "",
            },
            "models": models,
            "library": self._library_payload(),
            "wallpaper": self.wallpaper,
            "system_glass": self.system_glass,
            "official": self.official,
            "series": self._series_payload(),
            "url_history": self._url_history(),
            "recommendations": self._recommendations_payload(force=False),
        }

    def _url_history(self) -> list[dict]:
        rows = self.cfg.get("url_history") or []
        return [row for row in rows if isinstance(row, dict) and row.get("url")][:10]

    def _seed_url_history_from_library(self) -> None:
        if self._url_history():
            return
        seeded = []
        for book in load_index(self._out_dir())[:10]:
            ncode = book.get("ncode") or ""
            if not ncode:
                continue
            english = book.get("title") or ""
            if _has_japanese(english):
                english = ""
            japanese = book.get("original_title") or ""
            official_file = self._official_path(ncode)
            if official_file.exists():
                try:
                    official = json.loads(official_file.read_text(encoding="utf-8"))
                    english = official.get("official_title") or english
                except Exception:
                    pass
            seeded.append(
                {
                    "ncode": ncode,
                    "url": novel_page_url(ncode, book.get("source_url") or ""),
                    "english_title": english or japanese or ncode,
                    "title": japanese,
                    "series_chapters": int(book.get("total") or 0),
                }
            )
        if seeded:
            self.cfg["url_history"] = seeded
            save_config(self.cfg)

    def _remember_url(
        self,
        ncode: str,
        url: str = "",
        english_title: str = "",
        title: str = "",
        series_chapters: int = 0,
    ) -> list[dict]:
        code = (ncode or "").strip().lower()
        if not code:
            return self._url_history()
        page = novel_page_url(code, url)
        entry = {
            "ncode": code,
            "url": page,
            "english_title": (english_title or "").strip(),
            "title": (title or "").strip(),
            "series_chapters": int(series_chapters or 0),
        }
        history = [entry]
        for row in self._url_history():
            same = (row.get("ncode") or "").lower() == code or (row.get("url") or "") == page
            if same:
                if not entry["english_title"]:
                    entry["english_title"] = (row.get("english_title") or "").strip()
                if not entry["title"]:
                    entry["title"] = (row.get("title") or "").strip()
                if not entry["series_chapters"]:
                    entry["series_chapters"] = int(row.get("series_chapters") or 0)
                continue
            history.append(row)
        if not entry["english_title"]:
            entry["english_title"] = entry["title"] or code
        self.cfg["url_history"] = history[:10]
        save_config(self.cfg)
        saved = self._url_history()
        self._emit("history", saved)
        return saved

    def remember_url(self, data: dict | None = None) -> dict:
        payload = data or {}
        try:
            ncode, _host = parse_ncode((payload.get("url") or payload.get("ncode") or "").strip())
        except Exception:
            return {"ok": False, "url_history": self._url_history()}
        history = self._remember_url(
            ncode,
            payload.get("url") or "",
            payload.get("english_title") or "",
            payload.get("title") or "",
            int(payload.get("series_chapters") or 0),
        )
        return {"ok": True, "ncode": ncode, "url_history": history}

    def series_status(self, data: dict | None = None) -> dict:
        payload = data or {}
        info = self._series_payload(payload, lookup=bool(payload.get("lookup")))
        info["url_history"] = self._url_history()
        self._emit("series", info)
        self._emit("history", info["url_history"])
        return info

    def _series_payload(self, data: dict | None = None, lookup: bool = False) -> dict:
        data = data or {}
        url_ncode = ""
        try:
            url_ncode, _host = parse_ncode((data.get("url") or "").strip())
        except Exception:
            url_ncode = ""
        ncode = url_ncode or (data.get("ncode") or "").strip().lower()
        if not ncode:
            ncode = (self.novel.ncode if self.novel else "") or ""
        # Save the entered URL immediately, even before title lookup finishes.
        if ncode:
            self._remember_url(ncode, (data.get("url") or "").strip())
        stored = existing_novel(self._out_dir(), ncode) if ncode else None
        if self.novel and (self.novel.ncode or "").lower() == ncode:
            stored = self.novel
        downloaded = 0
        translated = 0
        local_last = 0
        japanese = ""
        english = ""
        if stored:
            downloaded = sum(1 for ch in stored.chapters if (ch.source_text or "").strip())
            translated = sum(1 for ch in stored.chapters if (ch.translated_text or "").strip())
            local_last = max((ch.number for ch in stored.chapters), default=0)
            japanese = stored.original_title or (stored.title if _has_japanese(stored.title) else "")
            if stored.title and not _has_japanese(stored.title):
                english = stored.title
        remote_total = 0
        if ncode:
            try:
                remote = series_info(ncode)
                remote_total = int(remote.get("series_chapters") or 0)
                japanese = remote.get("title") or japanese
            except Exception:
                remote_total = 0
        official_file = self._official_path(ncode) if ncode else None
        if official_file and official_file.exists():
            try:
                official = json.loads(official_file.read_text(encoding="utf-8"))
                english = official.get("official_title") or english
            except Exception:
                pass
        if lookup and ncode:
            try:
                info = lookup_official(japanese or ncode, english, stored.original_author if stored else "")
                if info.get("official_title"):
                    english = info["official_title"]
                official_file.parent.mkdir(parents=True, exist_ok=True)
                official_file.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
                if stored and (not self.novel or (self.novel.ncode or "").lower() != ncode):
                    self.official = info
                elif self.novel and (self.novel.ncode or "").lower() == ncode:
                    self.official = info
                    self._emit("official", info)
            except Exception:
                pass
        if not english and japanese:
            try:
                guess = google_translate(japanese, "English")
                if guess and not _has_japanese(guess):
                    english = guess
            except Exception:
                english = display_book_title(japanese, ncode, self.cfg.get("glossary") or "", japanese)
        total = max(remote_total, local_last)
        info = {
            "ncode": ncode,
            "title": japanese or ncode,
            "english_title": english,
            "series_chapters": total,
            "downloaded": downloaded,
            "translated": translated,
            "missing": max(0, total - downloaded),
            "url": novel_page_url(ncode, (data.get("url") or "") if ncode else ""),
        }
        if ncode:
            self._remember_url(
                ncode,
                info["url"],
                english,
                japanese,
                total,
            )
        return info

    def save_settings(self, data: dict) -> dict:
        self.cfg.update(
            {
                "provider": data.get("provider") or "ollama",
                "api_key": data.get("api_key") or "",
                "api_base": data.get("api_base") or OLLAMA_OPENAI,
                "model": data.get("model") or "",
                "target_language": data.get("target_language") or "English",
                "output_dir": data.get("output_dir") or str(self._out_dir()),
                "glossary": data.get("glossary") or "",
                "headset_host": (data.get("headset_host") or "").strip(),
                "headset_port": int(data.get("headset_port") or 8765),
                "headset_token": (data.get("headset_token") or "").strip(),
            }
        )
        if self.cfg["provider"] == "ollama":
            self.cfg["api_base"] = OLLAMA_OPENAI
        save_config(self.cfg)
        self._status("Settings saved.", 1.0, log=True)
        return {"ok": True, "config": self.state()["config"]}

    def refresh_models(self) -> dict:
        models = list_ollama_models()
        self._status(
            "Ollama models: " + (", ".join(models) if models else "none found"),
            1.0,
            log=True,
        )
        return {"models": models}

    def _recommendations_payload(self, force: bool = False) -> dict:
        if self._recommendations and not force:
            return self._recommendations
        result = peek_cache(limit=12)
        self._recommendations = result
        return result

    def recommendations(self) -> dict:
        result = self._recommendations_payload(force=False)
        self._emit("recommendations", result)
        return result

    def refresh_recommendations(self) -> dict:
        if self._rec_busy:
            return {"ok": False, "message": "Already refreshing recommendations."}
        threading.Thread(target=self._refresh_recommendations, daemon=True).start()
        return {"ok": True, "message": "Refreshing recommendations…"}

    def _refresh_recommendations(self) -> None:
        self._rec_busy = True
        try:
            self._status("Loading upcoming anime…", 0.1, log=True)

            def progress(msg: str) -> None:
                self._status(msg, None, log=True)

            result = list_upcoming(limit=12, force=True, progress=progress)
            self._recommendations = result
            self._emit("recommendations", result)
            self._status(result.get("message") or "Recommendations ready", 1.0, log=True)
        except Exception as exc:
            self._emit("log", traceback.format_exc())
            self._status(f"Recommendations failed: {exc}", 0, log=True)
        finally:
            self._rec_busy = False

    def recommend_for_book(self, data: dict | None = None) -> dict:
        data = data or {}
        title = (data.get("title") or "").strip()
        ncode = (data.get("ncode") or "").strip().lower()
        if not title and self.novel:
            title = self.novel.title or self.novel.original_title or ""
            ncode = ncode or self.novel.ncode
        return recommend_for_title(title, ncode, books_root=self._out_dir() / "books")

    def browse_folder(self) -> dict:
        import webview

        chosen = self._ui.create_file_dialog(webview.FOLDER_DIALOG) if self._ui else None
        path = chosen[0] if chosen else ""
        if path:
            self.cfg["output_dir"] = path
            save_config(self.cfg)
        return {"path": path or self.cfg.get("output_dir", "")}

    def open_epub(self) -> dict:
        import webview

        chosen = (
            self._ui.create_file_dialog(webview.OPEN_DIALOG, file_types=("EPUB Files (*.epub)",))
            if self._ui
            else None
        )
        path = chosen[0] if chosen else ""
        if path:
            self._open_reader(Path(path))
            return {"ok": True}
        return {"ok": False}

    def _open_reader(self, path: Path) -> None:
        root = Path(__file__).resolve().parents[1]
        reader = root / "open_reader.py"
        exe = Path(sys.executable)
        pythonw = exe.with_name("pythonw.exe")
        cmd = str(pythonw if pythonw.exists() else exe)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen([cmd, str(reader), str(path)], cwd=str(root), creationflags=flags)

    def select_book(self, ncode: str) -> dict:
        for book in load_index(self._out_dir()):
            if book.get("ncode") == ncode and book.get("book_json") and Path(book["book_json"]).exists():
                self.novel = load_novel(book["book_json"])
                self._status(f"Opening {self.novel.title or ncode}…", 0.2)
                self._load_official(ncode)
                self._status("Filling English chapter titles…", 0.45)
                self._ensure_chapter_titles()
                self._status("Cleaning pages: official names and extra readings…", 0.7)
                self._rewrite_official_names()
                self._status(f"Ready: {self.novel.title or ncode}", 1.0)
                self._emit("series", self._series_payload({"ncode": ncode}))
                break
        return self._library_payload()

    def _ensure_chapter_titles(self) -> None:
        if not self.novel:
            return
        glossary = (self.cfg.get("glossary") or "") + "\n" + official_glossary(
            self.official, self.novel.original_author or ""
        )
        if fill_english_chapter_titles(self.novel, glossary):
            save_novel(self._out_dir(), self.novel)

    def _official_path(self, ncode: str) -> Path:
        return self._out_dir() / "books" / (ncode or "book") / "official.json"

    def _load_official(self, ncode: str) -> None:
        path = self._official_path(ncode)
        if path.exists():
            self.official = json.loads(path.read_text(encoding="utf-8"))
            self._emit("official", self.official)
        else:
            self.official = {}

    def _refresh_official(self) -> dict:
        if not self.novel:
            return {}
        self._status("Looking up official title, publishers, and adaptations…", 0.55, log=True)
        if self.cfg.get("model"):
            self._status("Ollama web lookup for official releases…", 0.6, log=True)
        info = lookup_official(
            self.novel.original_title or self.novel.title,
            self.novel.title,
            self.novel.original_author or self.novel.author,
            model=self.cfg.get("model") or "",
            ollama_key=self.cfg.get("api_key") or "",
        )
        self.official = info
        if self.novel.ncode:
            path = self._official_path(self.novel.ncode)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        if info.get("official_title"):
            self.novel.title = info["official_title"]
        listed = info.get("author_english") or ""
        if listed and not _has_japanese(listed):
            self.novel.author = listed
        self._rewrite_official_names()
        self._emit("official", info)
        self._status("Official listing: " + describe_official(info), log=True)
        return info

    def _rewrite_official_names(self) -> None:
        if not self.novel:
            return
        if self.official:
            before = len(self.official.get("names") or [])
            self.official = enrich_official_names(self.official)
            if self.novel.ncode and len(self.official.get("names") or []) != before:
                path = self._official_path(self.novel.ncode)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(self.official, ensure_ascii=False, indent=2), encoding="utf-8")
                self._emit("official", self.official)
        self._status("Applying official names and removing extra readings…", log=True)
        gloss = (self.cfg.get("glossary") or "") + "\n" + official_glossary(
            self.official, self.novel.original_author or ""
        )
        if not apply_official_names(self.novel, gloss):
            return
        self._status("Inserted official names into the translated pages.", log=True)
        save_novel(self._out_dir(), self.novel)
        for book in load_index(self._out_dir()):
            if book.get("ncode") != self.novel.ncode:
                continue
            epub_path = book.get("epub")
            if epub_path:
                path = Path(epub_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                export_epub(self.novel, path)
                save_novel(self._out_dir(), self.novel, epub_path=path)
            break

    def open_selected(self, ncode: str) -> dict:
        for book in load_index(self._out_dir()):
            if book.get("ncode") != ncode:
                continue
            epub_path = book.get("epub")
            if epub_path and Path(epub_path).exists():
                if book.get("book_json") and Path(book["book_json"]).exists():
                    self.novel = load_novel(book["book_json"])
                    self._status("Cleaning pages before opening the reader…", 0.4)
                    self._load_official(ncode)
                    self._rewrite_official_names()
                self._status("Opening reader…", 1.0)
                self._open_reader(Path(epub_path))
                return {"ok": True}
            if book.get("book_json"):
                self.novel = load_novel(book["book_json"])
                return {"ok": False, "message": "Downloaded only. Hit Translate to make an EPUB."}
        return {"ok": False, "message": "Book not found."}

    def probe_headset(self, data: dict | None = None) -> dict:
        data = data or {}
        host = (data.get("headset_host") or self.cfg.get("headset_host") or "").strip()
        port = int(data.get("headset_port") or self.cfg.get("headset_port") or 8765)
        if not host:
            return self.discover_headset(data)
        result = probe_headset(host, port)
        if result.get("ok"):
            self._apply_headset_discovery(result)
        self._status(result.get("message") or "Headset probe finished", 1.0 if result.get("ok") else 0)
        return result

    def discover_headset(self, data: dict | None = None) -> dict:
        data = data or {}
        port = int(data.get("headset_port") or self.cfg.get("headset_port") or 8765)
        self._status("Looking for SpatialLauncher on Wi‑Fi…", 0.2, log=True)
        result = discover_headset(timeout=4.0, port=port)
        if result.get("ok"):
            self._apply_headset_discovery(result)
        self._status(result.get("message") or "Headset search finished", 1.0 if result.get("ok") else 0, log=True)
        return result

    def _apply_headset_discovery(self, result: dict) -> None:
        host = (result.get("host") or "").strip()
        if not host:
            return
        self.cfg["headset_host"] = host
        self.cfg["headset_port"] = int(result.get("port") or 8765)
        token = (result.get("token") or "").strip()
        if token:
            self.cfg["headset_token"] = token
        save_config(self.cfg)

    def send_selected(self, ncode: str = "") -> dict:
        code = (ncode or "").strip().lower()
        if not code and self.novel:
            code = (self.novel.ncode or "").lower()
        if not code:
            return {"ok": False, "message": "Select a book in the library first."}
        for book in load_index(self._out_dir()):
            if (book.get("ncode") or "").lower() != code:
                continue
            epub_path = book.get("epub")
            if epub_path and Path(epub_path).exists():
                return self.send_epub(str(epub_path))
            return {"ok": False, "message": "Downloaded only. Hit Translate to make an EPUB first."}
        return {"ok": False, "message": "Book not found."}

    def send_epub(self, path: str = "") -> dict:
        file_path = Path(path or "")
        if not file_path.exists():
            return {"ok": False, "message": "EPUB path missing."}
        host = (self.cfg.get("headset_host") or "").strip()
        port = int(self.cfg.get("headset_port") or 8765)
        token = (self.cfg.get("headset_token") or "").strip()
        self._status(f"Sending {file_path.name} to headset…", 0.35, log=True)
        result = send_epub_file(file_path, host, port, token)
        self._status(result.get("message") or "Send finished", 1.0 if result.get("ok") else 0, log=True)
        return result

    def download(self, data: dict) -> dict:
        if self.busy:
            return {"ok": False, "message": "Busy"}
        try:
            ncode, _host = parse_ncode((data.get("url") or "").strip())
        except Exception:
            ncode = ""
        existing = existing_novel(self._out_dir(), ncode) if ncode else None
        start = int(data.get("start") or 1)
        end_raw = (data.get("end") or "").strip()
        end = int(end_raw) if end_raw else None
        plan = plan_range(existing, start, end)
        if (plan["downloaded"] or plan["translated"]) and not data.get("confirmed"):
            down = plan["downloaded"]
            tr = plan["translated"]
            span = f"{start}–{end}" if end else f"{start}+"
            return {
                "needs_confirm": True,
                "already": len(down),
                "message": (
                    f"Chapters {span}: {len(down)} already downloaded"
                    + (f", {len(tr)} already translated" if tr else "")
                    + ". Keep existing (only fetch missing), or update (download again)?"
                ),
            }
        threading.Thread(target=self._download, args=(data,), daemon=True).start()
        return {"ok": True}

    def _download(self, data: dict) -> None:
        self.busy = True
        self._emit("busy", True)
        self._status("Downloading Japanese chapters…", 0.12, log=True)

        def note(msg: str, value: float | None = None) -> None:
            self._status(msg, value, log=True)

        try:
            url = (data.get("url") or "").strip()
            start = int(data.get("start") or 1)
            end_raw = (data.get("end") or "").strip()
            end = int(end_raw) if end_raw else None
            ncode, _host = parse_ncode(url)
            mode = data.get("mode") or "chapters"
            out_dir = Path(data.get("output_dir") or self._out_dir())
            self.cfg["output_dir"] = str(out_dir)
            previous = existing_novel(out_dir, ncode)
            replace = bool(data.get("overwrite"))
            plan = plan_range(previous, start, end)
            skip = set() if replace else set(plan["downloaded"])
            if mode == "pdf":
                try:
                    note("Downloading official vertical PDF…", 0.18)
                    pdf_path = download_official_pdf(url, out_dir / "pdfs", progress=note)
                    self.novel = import_pdf(pdf_path)
                except Exception as exc:
                    note(f"Official PDF failed: {exc}. Falling back to chapters…", 0.2)
                    self.novel = fetch_novel(
                        url,
                        start=start,
                        end=end,
                        delay=float(self.cfg.get("chapter_delay", 0.8)),
                        progress=note,
                        existing=previous,
                        skip_download=skip,
                    )
            else:
                note(f"Fetching Syosetu chapters {start}–{end or 'end'}…", 0.2)
                self.novel = fetch_novel(
                    url,
                    start=start,
                    end=end,
                    delay=float(self.cfg.get("chapter_delay", 0.8)),
                    progress=note,
                    existing=previous,
                    skip_download=skip,
                )
            self.novel = union_chapters(previous, self.novel)
            self.novel, kept = merge_existing_work(self.novel, previous, replace)
            lang = data.get("target_language") or "English"
            if _has_japanese(self.novel.original_title or self.novel.title):
                if not self.novel.original_title:
                    self.novel.original_title = self.novel.title
                try:
                    self.novel.title = google_translate(self.novel.original_title, lang)
                    note(f"Google title: {self.novel.title}", 0.42)
                except Exception as exc:
                    note(f"Google title skipped: {exc}", 0.42)
            if _has_japanese(self.novel.original_author or self.novel.author):
                if not self.novel.original_author:
                    self.novel.original_author = self.novel.author
                try:
                    self.novel.author = google_translate(self.novel.original_author, lang)
                    note(f"Google author: {self.novel.author}", 0.46)
                except Exception as exc:
                    note(f"Google author skipped: {exc}", 0.46)
            if kept:
                note(f"Kept {kept} already-translated chapter(s).", 0.48)
            elif previous and replace:
                note("Replacing previous translations as requested.", 0.48)
            try:
                self._refresh_official()
            except Exception as exc:
                note(f"Wiki lookup skipped: {exc}", 0.7)
            note("Filling English chapter titles…", 0.85)
            self._ensure_chapter_titles()
            save_novel(out_dir, self.novel)
            title = display_book_title(
                self.novel.title, self.novel.ncode, data.get("glossary") or "", self.novel.original_title
            )
            note(f"Download finished: {title} — {len(self.novel.chapters)} chapter(s).", 1.0)
            self._emit("library", self._library_payload())
            self._emit("series", self._series_payload({"ncode": ncode}))
        except Exception:
            self._emit("log", traceback.format_exc())
            self._status("Download failed", 0)
        finally:
            self.busy = False
            self._emit("busy", False)

    def _book_from_request(self, data: dict) -> Novel | None:
        ncode = (data.get("ncode") or "").strip().lower()
        if not ncode:
            try:
                ncode, _host = parse_ncode((data.get("url") or "").strip())
            except Exception:
                ncode = ""
        if self.novel and (not ncode or (self.novel.ncode or "").lower() == ncode):
            return self.novel
        if ncode:
            found = existing_novel(self._out_dir(), ncode)
            if found:
                self.novel = found
                self._load_official(ncode)
                return found
        return self.novel

    def translate(self, data: dict) -> dict:
        if self.busy:
            return {"ok": False, "message": "Busy"}
        novel = self._book_from_request(data)
        if not novel:
            return {
                "ok": False,
                "message": "Select a book under All novels, or download that URL first.",
            }
        start = int(data.get("start") or 1)
        end_raw = (data.get("end") or "").strip()
        end = int(end_raw) if end_raw else None
        plan = plan_range(novel, start, end)
        down, tr = plan["downloaded"], plan["translated"]
        if not down and not novel.chapters:
            return {
                "ok": False,
                "message": "Nothing is downloaded for this book yet. Use Download chapters first.",
            }
        if not data.get("confirmed"):
            span = f"{start}–{end}" if end else f"{start}+"
            if tr or down:
                extra = ""
                if tr:
                    extra = (
                        f"{len(tr)} already translated. "
                        "Keep existing skips those. Update translates them again."
                    )
                else:
                    extra = f"{len(down)} downloaded and not translated yet. Keep starts the translation. Update still translates them all."
                return {
                    "needs_confirm": True,
                    "already": len(tr) or len(down),
                    "message": f"{novel.title or novel.ncode} chapters {span}: {len(down)} on disk. {extra}",
                }
        self.save_settings(data)
        threading.Thread(target=self._translate, args=(data,), daemon=True).start()
        return {"ok": True}

    def _translate(self, data: dict) -> None:
        self.busy = True
        self._emit("busy", True)
        self._status("Preparing translation…", 0.28, log=True)
        try:
            self._refresh_official()
        except Exception as exc:
            self._status(f"Wiki lookup skipped: {exc}", 0.32, log=True)
        self._status("Building official-name glossary…", 0.36, log=True)
        glossary = expand_glossary_aliases(
            (data.get("glossary") or "")
            + "\n"
            + official_glossary(self.official, self.novel.original_author or "")
        )
        name = display_book_title(
            self.novel.title, self.novel.ncode, glossary, self.novel.original_title
        )
        self._status(f"Translating {name}…", 0.4, log=True)
        try:
            def progress(msg: str) -> None:
                done = sum(1 for ch in self.novel.chapters if ch.translated_text.strip())
                total = max(1, len(self.novel.chapters))
                self._status(msg, 0.4 + 0.5 * (done / total), log=True)

            self.novel = translate_novel(
                self.novel,
                api_key=(data.get("api_key") or "ollama"),
                api_base=(data.get("api_base") or OLLAMA_OPENAI),
                model=(data.get("model") or ""),
                language=(data.get("target_language") or "English"),
                glossary=glossary,
                progress=progress,
                redo_translated=bool(data.get("overwrite")),
            )
            folder = self._out_dir() / "books" / (self.novel.ncode or "book")
            folder.mkdir(parents=True, exist_ok=True)
            epub_path = folder / f"{english_filename(self.novel.title, self.novel.ncode)}.epub"
            self._status("Writing EPUB…", 0.92, log=True)
            export_epub(self.novel, epub_path)
            save_novel(self._out_dir(), self.novel, epub_path=epub_path)
            self._status(f"Translation finished. Opening {epub_path.name}", 1.0, log=True)
            self._emit("library", self._library_payload())
            self._emit("series", self._series_payload({"ncode": self.novel.ncode}))
            self._open_reader(epub_path)
        except Exception:
            self._emit("log", traceback.format_exc())
            self._status("Translation failed", 0)
        finally:
            self.busy = False
            self._emit("busy", False)
