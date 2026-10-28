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

# Keys pasted into a hosting dashboard often carry a trailing newline or space, which makes
# every HTTP request fail ("Invalid header value"). Normalise them once, here.
SECRET_VARS = ("QLOO_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
for _k in SECRET_VARS + ("QLOO_BASE_URL", "OPENAI_BASE_URL", "OPENAI_MODEL"):
    if os.environ.get(_k):
        os.environ[_k] = os.environ[_k].strip().strip('"').strip("'")


def redact(text: str) -> str:
    """Remove any configured secret from a message before it can reach a browser or log."""
    text = str(text)
    for k in SECRET_VARS:
        v = os.environ.get(k)
        if v and len(v) >= 6:
            text = text.replace(v, "[redacted]")
    return text
