"""
FastAPI application: initialization, lifespan management, and HTTP routes.
"""
import asyncio
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.config import logger, executor, DATA_DIR, DONE_DIR, META_DIR, FAILED_DIR
from app.schemas import VideoPayload
from app.storage import is_failed, get_failed_info, clear_failed
from app.worker import download_and_convert, retry_failed_loop, _run_retry_batch


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(retry_failed_loop())
    yield
    task.cancel()

app = FastAPI(title="YouTube MP3 Downloader", lifespan=lifespan)


@app.post("/seen")
def on_video_seen(payload: VideoPayload):
    """Handle video seen event from browser."""
    video_id = payload.videoId.strip()
    title = payload.title.strip()
    channel = payload.channel.strip()

    logger.info(f"Received request for {video_id}: {title}")

    # Check if already processed by looking for metadata file
    meta_path = META_DIR / f"{video_id}.json"
    if meta_path.exists():
        logger.info(f"Already downloaded: {video_id}")
        return {"status": "READY", "videoId": video_id}

    if is_failed(video_id):
        info = get_failed_info(video_id)
        retry_count = info.get("retry_count", 0) if info else 0
        # Use stored title/channel if the browser didn't send useful ones
        retry_title = title or (info.get("title", video_id) if info else video_id)
        retry_channel = channel or (info.get("channel", "") if info else "")
        clear_failed(video_id)
        logger.info(f"Re-queuing previously failed download {video_id} (was failed {retry_count}x)")
        executor.submit(download_and_convert, video_id, retry_title, retry_channel)
        return {"status": "PROCESSING", "videoId": video_id}

    # Start background download
    logger.info(f"Queuing download for {video_id}")
    executor.submit(download_and_convert, video_id, title, channel)

    return {"status": "PROCESSING", "videoId": video_id}


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/retry-failed")
async def retry_failed():
    """Manually trigger a retry of all failed downloads."""
    json_markers = list(FAILED_DIR.glob("*.json"))
    legacy_markers = [p for p in FAILED_DIR.iterdir() if p.suffix != ".json"]
    total = len(json_markers) + len(legacy_markers)
    asyncio.create_task(_run_retry_batch())
    return {"status": "queued", "retrying": total}


@app.get("/stats")
def stats():
    """Get download statistics."""
    done_count = len(list(DONE_DIR.glob("*.mp3")))
    failed_files = list(FAILED_DIR.glob("*.json")) + [
        p for p in FAILED_DIR.iterdir() if p.suffix != ".json"
    ]
    failed_details = []
    for f in failed_files:
        try:
            if f.suffix == ".json":
                with open(f) as fp:
                    data = json.load(fp)
                failed_details.append({
                    "videoId": data.get("videoId"),
                    "title": data.get("title"),
                    "retry_count": data.get("retry_count", 0),
                    "last_failed_at": data.get("last_failed_at"),
                })
            else:
                failed_details.append({"videoId": f.name, "title": None, "retry_count": None})
        except Exception:
            failed_details.append({"videoId": f.stem, "title": None, "retry_count": None})

    return {
        "downloaded": done_count,
        "failed": len(failed_details),
        "failed_details": failed_details,
        "data_dir": str(DATA_DIR),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)