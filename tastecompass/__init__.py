"""TasteCompass package.

On import, keys are loaded from a `.env` file in the project folder (one KEY=value per line),
so QLOO_API_KEY / OPENAI_API_KEY survive closing the terminal. Variables already set in the
environment win over the file. `.env` is git-ignored: never commit it.
"""
import os
from pathlib import Path


def _load_env(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8-sig")  # -sig: Notepad may save a BOM
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and value and not os.environ.get(key):
            os.environ[key] = value


_load_env(Path(__file__).resolve().parent.parent / ".env")
