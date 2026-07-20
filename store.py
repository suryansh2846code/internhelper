"""Tiny JSON persistence so uploads and applied-history survive server restarts.

No database — just two files under data/state/. Both hold PII (résumé text,
which internships you applied to) so the directory is gitignored."""
import json
import os

STATE_DIR = "./data/state"
RESUMES_FILE = os.path.join(STATE_DIR, "resumes.json")
APPLIED_FILE = os.path.join(STATE_DIR, "applied.json")


def _load(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(path: str, data: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)  # atomic — never leave a half-written file


def load_resumes() -> dict:
    """role -> {path, filename, text, keywords, keyword_status}. Any status left
    mid-extraction by a crash is reset so the UI doesn't hang on 'extracting'."""
    resumes = _load(RESUMES_FILE)
    for data in resumes.values():
        if data.get("keyword_status") == "extracting":
            data["keyword_status"] = "ready" if data.get("keywords") else "error"
    return resumes


def save_resumes(resumes: dict) -> None:
    _save(RESUMES_FILE, resumes)


def load_applied() -> dict:
    """url -> {title, company, applied_at} for every listing already applied to."""
    return _load(APPLIED_FILE)


def save_applied(applied: dict) -> None:
    _save(APPLIED_FILE, applied)
