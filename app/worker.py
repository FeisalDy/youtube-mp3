"""
Heavy processing logic: downloading/converting videos via yt-dlp + ffmpeg,
and the background retry loop for previously-failed downloads.
"""
import asyncio
import json
import subprocess
from datetime import datetime

from app.config import (
    logger,
    executor,
    DONE_DIR,
    META_DIR,
    FAILED_DIR,
    RETRY_INTERVAL_SECONDS,
    RETRY_STARTUP_DELAY_SECONDS,
)
from app.storage import sanitize_filename, mark_failed


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