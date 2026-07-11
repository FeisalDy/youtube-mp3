"""
OS / filesystem operations: filename sanitization and failed-download
marker management (JSON files, not empty files).
"""
import json
import re
from datetime import datetime

from app.config import FAILED_DIR


def sanitize_filename(filename: str, max_length: int = 200) -> str:
    """Sanitize filename by removing invalid characters and limiting length."""
    # Replace invalid characters with underscores
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Replace multiple spaces/underscores with single underscore
    filename = re.sub(r'[\s_]+', '_', filename)
    # Remove leading/trailing underscores and dots
    filename = filename.strip('_. ')
    # Limit length
    if len(filename) > max_length:
        filename = filename[:max_length].rstrip('_. ')
    return filename or "untitled"


def mark_failed(video_id: str, title: str, channel: str, error: str = "") -> None:
    """Write / update a JSON failed marker for a video."""
    failed_path = FAILED_DIR / f"{video_id}.json"
    existing: dict = {}
    if failed_path.exists():
        try:
            with open(failed_path) as f:
                existing = json.load(f)
        except Exception:
            pass
    existing.update({
        "videoId": video_id,
        "title": title,
        "channel": channel,
        "last_failed_at": datetime.now().isoformat(),
        "retry_count": existing.get("retry_count", 0) + 1,
        "last_error": error[:500] if error else "",
    })
    with open(failed_path, "w") as f:
        json.dump(existing, f, indent=2)


def clear_failed(video_id: str) -> None:
    """Remove the failed marker for a video (e.g. after successful retry)."""
    failed_path = FAILED_DIR / f"{video_id}.json"
    if failed_path.exists():
        failed_path.unlink()
    # Also handle legacy empty marker files from older versions
    legacy = FAILED_DIR / video_id
    if legacy.exists():
        legacy.unlink()


def get_failed_info(video_id: str) -> dict | None:
    """Return the failed marker data, or None if not failed."""
    failed_path = FAILED_DIR / f"{video_id}.json"
    if failed_path.exists():
        try:
            with open(failed_path) as f:
                return json.load(f)
        except Exception:
            return {"videoId": video_id, "title": video_id, "channel": ""}
    return None


def is_failed(video_id: str) -> bool:
    """Check if a video has a failed marker (JSON or legacy empty file)."""
    return (
        (FAILED_DIR / f"{video_id}.json").exists()
        or (FAILED_DIR / video_id).exists()
    )