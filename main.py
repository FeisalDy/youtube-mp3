import asyncio
import os
import json
import logging
import subprocess
import re
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from concurrent.futures import ThreadPoolExecutor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(retry_failed_loop())
    yield
    task.cancel()

app = FastAPI(title="YouTube MP3 Downloader", lifespan=lifespan)

# Thread pool for background downloads
executor = ThreadPoolExecutor(max_workers=2)

# Directories
DATA_DIR = Path("/data")
DONE_DIR = DATA_DIR / "done"
META_DIR = DATA_DIR / "meta"
FAILED_DIR = DATA_DIR / "failed"

# Ensure directories exist
for d in [DONE_DIR, META_DIR, FAILED_DIR]:
    d.mkdir(parents=True, exist_ok=True)


class VideoPayload(BaseModel):
    videoId: str
    title: str
    channel: str


# ---------------------------------------------------------------------------
# Failed-download helpers — failed markers are JSON files, not empty files
# ---------------------------------------------------------------------------

RETRY_INTERVAL_SECONDS = 24 * 60 * 60  # 24 hours
RETRY_STARTUP_DELAY_SECONDS = 30       # wait after service starts before first retry


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


async def retry_failed_loop() -> None:
    """Background task: retry all failed downloads once every 24 hours."""
    await asyncio.sleep(RETRY_STARTUP_DELAY_SECONDS)
    while True:
        await _run_retry_batch()
        await asyncio.sleep(RETRY_INTERVAL_SECONDS)


async def _run_retry_batch() -> None:
    """Queue all currently-failed videos for re-download."""
    json_markers = list(FAILED_DIR.glob("*.json"))
    # Also handle any legacy empty-file markers
    legacy_markers = [p for p in FAILED_DIR.iterdir() if p.suffix != ".json"]
    all_markers = json_markers + legacy_markers

    if not all_markers:
        logger.info("Retry batch: no failed downloads to retry")
        return

    logger.info(f"Retry batch: queuing {len(all_markers)} failed download(s)")
    for marker in all_markers:
        try:
            if marker.suffix == ".json":
                with open(marker) as f:
                    data = json.load(f)
                video_id = data["videoId"]
                title = data.get("title", video_id)
                channel = data.get("channel", "")
            else:
                video_id = marker.name
                title = video_id
                channel = ""

            # Remove marker before submitting — download_and_convert will
            # re-create it on failure, so we get an accurate retry_count.
            marker.unlink(missing_ok=True)
            logger.info(f"Retry batch: queuing {video_id} ({title})")
            executor.submit(download_and_convert, video_id, title, channel)
            await asyncio.sleep(2)  # small gap to avoid hammering YouTube
        except Exception as e:
            logger.error(f"Retry batch: error processing {marker}: {e}")


# ---------------------------------------------------------------------------

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


def download_and_convert(video_id: str, title: str, channel: str):
    """Download video and convert to MP3 in background."""
    try:
        logger.info(f"Starting download for {video_id}: {title}")
        
        # Sanitize title for filename and append video ID for uniqueness
        safe_title = sanitize_filename(title)
        output_path = DONE_DIR / f"{safe_title}_{video_id}.mp3"
        meta_path = META_DIR / f"{video_id}.json"
        
        # yt-dlp command to download audio and convert to MP3
        cmd = [
            "yt-dlp",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "192",
            "-o", str(output_path),
            "--write-thumbnail",
            "--convert-thumbnails", "jpg",
            "--cookies", "/app/cookies.txt",
            "--remote-components", "ejs:github",
            "--extractor-args", "youtube:player_client=web,mweb,tv",
            f"https://www.youtube.com/watch?v={video_id}"
        ]
        
        logger.info(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode != 0:
            logger.error(f"Download failed for {video_id}: {result.stderr}")
            mark_failed(video_id, title, channel, result.stderr)
            return
        
        # Embed metadata using ffmpeg
        # Thumbnail might be saved with full filename or just videoId
        metadata_path = DONE_DIR / f"{safe_title}_{video_id}.jpg"
        if not metadata_path.exists():
            metadata_path = DONE_DIR / f"{video_id}.jpg"
        if metadata_path.exists():
            logger.info(f"Embedding thumbnail for {video_id}")
            temp_output = DONE_DIR / f"{safe_title}_{video_id}_temp.mp3"
            
            ffmpeg_cmd = [
                "ffmpeg",
                "-i", str(output_path),
                "-i", str(metadata_path),
                "-c", "copy",
                "-metadata", f"title={title}",
                "-metadata", f"artist={channel}",
                "-map", "0:0",
                "-map", "1:0",
                "-id3v2_version", "3",
                "-disposition:v:0", "attached_pic",
                "-y",
                str(temp_output)
            ]
            
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                temp_output.replace(output_path)
                logger.info(f"Metadata embedded for {video_id}")
            else:
                logger.warning(f"Failed to embed metadata for {video_id}: {result.stderr}")
            
            # Clean up thumbnail
            try:
                metadata_path.unlink()
            except:
                pass
        else:
            # Just add basic ID3 metadata without thumbnail
            logger.info(f"Adding ID3 metadata for {video_id} (no thumbnail)")
            temp_output = DONE_DIR / f"{safe_title}_{video_id}_temp.mp3"
            
            ffmpeg_cmd = [
                "ffmpeg",
                "-i", str(output_path),
                "-c", "copy",
                "-metadata", f"title={title}",
                "-metadata", f"artist={channel}",
                "-id3v2_version", "3",
                "-y",
                str(temp_output)
            ]
            
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                temp_output.replace(output_path)
                logger.info(f"ID3 metadata added for {video_id}")
            else:
                logger.warning(f"Failed to add metadata for {video_id}: {result.stderr}")
        
        # Save metadata JSON
        meta = {
            "videoId": video_id,
            "title": title,
            "channel": channel,
            "downloaded_at": datetime.now().isoformat(),
            "filename": f"{safe_title}_{video_id}.mp3"
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
        
        logger.info(f"Successfully downloaded and processed {video_id}")
        
    except subprocess.TimeoutExpired:
        logger.error(f"Download timeout for {video_id}")
        mark_failed(video_id, title, channel, "timeout")
    except Exception as e:
        logger.error(f"Unexpected error for {video_id}: {e}")
        mark_failed(video_id, title, channel, str(e))


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
    uvicorn.run(app, host="0.0.0.0", port=8000)
