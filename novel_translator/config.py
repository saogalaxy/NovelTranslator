from __future__ import annotations

import json
from pathlib import Path

APP_DIR = Path.home() / ".novel_translator"
CONFIG_PATH = APP_DIR / "config.json"

DEFAULTS = {
    "provider": "ollama",
    "api_key": "",
    "api_base": "http://127.0.0.1:11434/v1",
    "model": "",
    "target_language": "English",
    "output_dir": str(Path.home() / "Documents" / "NovelTranslator"),
    "chapter_delay": 0.8,
    "url_history": [],
    "headset_host": "",
    "headset_port": 8765,
    "headset_token": "",
}


def load_config() -> dict:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_config(DEFAULTS)
        return dict(DEFAULTS)
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    merged = dict(DEFAULTS)
    merged.update(data)
    return merged


def save_config(data: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
