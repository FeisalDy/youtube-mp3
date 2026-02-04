import os
import json
import logging
import subprocess
import re
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

app = FastAPI(title="YouTube MP3 Downloader")

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
            f"https://www.youtube.com/watch?v={video_id}"
        ]
        
        logger.info(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode != 0:
            logger.error(f"Download failed for {video_id}: {result.stderr}")
            FAILED_DIR.joinpath(video_id).touch()
            return
        
        # Embed metadata using ffmpeg
        # Thumbnail might be saved with full filename or just videoId
        metadata_path = DONE_DIR / f"{safe_title}_{video_id}.webp"
        if not metadata_path.exists():
            metadata_path = DONE_DIR / f"{video_id}.webp"
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
        FAILED_DIR.joinpath(video_id).touch()
    except Exception as e:
        logger.error(f"Unexpected error for {video_id}: {e}")
        FAILED_DIR.joinpath(video_id).touch()


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
    
    if (FAILED_DIR / video_id).exists():
        logger.info(f"Previous download failed: {video_id}")
        return {"status": "FAILED", "videoId": video_id}
    
    # Start background download
    logger.info(f"Queuing download for {video_id}")
    executor.submit(download_and_convert, video_id, title, channel)
    
    return {"status": "PROCESSING", "videoId": video_id}


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/stats")
def stats():
    """Get download statistics."""
    done_count = len(list(DONE_DIR.glob("*.mp3")))
    failed_count = len(list(FAILED_DIR.iterdir()))
    
    return {
        "downloaded": done_count,
        "failed": failed_count,
        "data_dir": str(DATA_DIR)
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
