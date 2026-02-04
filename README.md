# YouTube MP3 Downloader

A **personal-use** Dockerized service that automatically downloads YouTube videos as MP3 when played in your browser.

## Overview

- **Browser-side**: Tampermonkey script detects when you play a YouTube video and sends the video ID to the backend.
- **Server-side**: FastAPI service downloads audio via yt-dlp, converts to MP3 via ffmpeg, embeds metadata and thumbnail.
- **Storage**: All MP3 files are saved to a host directory and persisted via Docker volumes.
- **Auto-start**: Service automatically starts on system reboot.

## Requirements

- **Docker** and **Docker Compose** installed on Linux
- **Firefox** or **Chrome** with **Tampermonkey** extension

## Files

| File                             | Purpose                      |
| -------------------------------- | ---------------------------- |
| `main.py`                        | FastAPI backend service      |
| `requirements.txt`               | Python dependencies          |
| `Dockerfile`                     | Docker image definition      |
| `docker compose.yml`             | Docker Compose configuration |
| `youtube-mp3-downloader.user.js` | Tampermonkey script          |
| `README.md`                      | This file                    |

## Setup & Installation

### 1. Clone or Download This Project

```bash
git clone <repo-url> ~/youtube-mp3-downloader
cd ~/youtube-mp3-downloader
```

### 2. Build and Start Docker Service

```bash
cd ~/youtube-mp3-downloader
docker compose up -d --build
```

Verify the service is running:

```bash
docker compose ps
docker logs youtube-mp3-downloader
```

You should see logs indicating the service is listening on `127.0.0.1:8000`.

### 3. Install Tampermonkey Script

1. Install **Tampermonkey** extension for your browser

   - [Firefox](https://addons.mozilla.org/en-US/firefox/addon/tampermonkey/)
   - [Chrome](https://chrome.google.com/webstore/detail/tampermonkey/dhdgffkkebhmkfjojejmpbldmpobp55f)

2. Open the Tampermonkey dashboard and click **Create a new script**
3. Copy the entire contents of `youtube-mp3-downloader.user.js` and paste it
4. Save (Ctrl+S)
5. Enable the script in the Tampermonkey dashboard

### 4. Test

1. Open `https://youtube.com` in your browser
2. Search for and play any video
3. Open the browser console (F12) and look for logs starting with `[YT-MP3]`
4. You should see a POST request to `http://127.0.0.1:8000/seen` with status `PROCESSING`
5. Check the backend logs:
   ```bash
   docker logs -f youtube-mp3-downloader
   ```

Once the download completes (usually within 30 seconds), the log will show `Successfully downloaded and processed`.

## Usage

### Normal Operation

1. Browse YouTube as usual
2. When you play a video, the script automatically sends it to the backend
3. The backend downloads and converts in the background—**no blocking**
4. MP3 files are saved inside the Docker volume at `/data/done/`

### Check Downloads

Access files using Docker commands:

```bash
# List downloaded MP3 files
docker compose exec youtube-mp3 ls /data/done/

# Copy a file to host
docker cp youtube-mp3-downloader:/data/done/<videoId>.mp3 ~/Downloads/

# Copy all files to host
docker cp youtube-mp3-downloader:/data/done/. ~/Downloads/youtube-mp3/
```

Files are named by sanitized video title, e.g., `Rick_Astley_Never_Gonna_Give_You_Up.mp3`. Invalid filesystem characters are replaced with underscores.

### View Metadata

```bash
# View metadata JSON
docker compose exec youtube-mp3 cat /data/meta/<videoId>.json

# Copy metadata to host
docker cp youtube-mp3-downloader:/data/meta/<videoId>.json ~/Downloads/
```

### View Failed Downloads

```bash
docker compose exec youtube-mp3 ls /data/failed/
```

If a video ID appears here, the download failed.

### Backend Statistics

```bash
curl http://127.0.0.1:8000/stats
```

Returns:

```json
{
  "downloaded": 42,
  "failed": 2,
  "data_dir": "/data"
}
```

### Health Check

```bash
curl http://127.0.0.1:8000/health
```

## Management

### Stop the Service

```bash
docker compose down
```

### Restart the Service

```bash
docker compose restart
```

### View Logs

```bash
docker logs youtube-mp3-downloader
docker logs -f youtube-mp3-downloader  # Follow logs
```

### Remove All Data

```bash
docker compose down -v
```

This removes the container and the named volume containing all downloaded files.

### Update the Service

```bash
docker compose down
docker compose up -d --build
```

## Filesystem Layout

Inside the Docker container:

```
/data/
├── done/
│   ├── Rick_Astley_Never_Gonna_Give_You_Up.mp3
│   ├── Some_Other_Video_Title.mp3
│   └── ...
├── meta/
│   ├── dQw4w9WgXcQ.json
│   ├── anotherVideoId.json
│   └── ...
└── failed/
    ├── VIDEO_ID_BAD
    └── ...
```

This directory is backed by a Docker named volume (`youtube-mp3-data`). Files are **not** directly accessible via the host filesystem. Use `docker cp` or `docker compose exec` to access files.

**Note**: MP3 files are named using sanitized video titles for readability. Metadata files use video IDs to track which videos have been downloaded and prevent duplicates.

## API Endpoints

### POST /seen

Send video metadata when a video is played.

**Request:**

```json
{
  "videoId": "dQw4w9WgXcQ",
  "title": "Rick Astley - Never Gonna Give You Up",
  "channel": "Rick Astley"
}
```

**Responses:**

- **READY**: `{"status": "READY", "videoId": "..."}`MP3 already exists in `/data/done/`
- **PROCESSING**: `{"status": "PROCESSING", "videoId": "..."}`Download queued or in progress
- **FAILED**: `{"status": "FAILED", "videoId": "..."}`
  Previous attempt failed; marked in `/data/failed/`

### GET /health

Health check endpoint.

**Response:**

```json
{ "status": "ok" }
```

### GET /stats

Download statistics.

**Response:**

```json
{
  "downloaded": 10,
  "failed": 2,
  "data_dir": "/data"
}
```

## Automatic Start on Boot

Docker Compose with `restart: unless-stopped` ensures the service restarts automatically after a system reboot. Verify Docker daemon is configured to start on boot:

```bash
systemctl is-enabled docker
```

If not enabled:

```bash
sudo systemctl enable docker
```

## Known Limitations & Assumptions

1. **YouTube Compatibility**: yt-dlp depends on YouTube's API and UI. If YouTube significantly changes, this may break. Keep yt-dlp updated.
2. **Video ID Uniqueness**: The system assumes `videoId` is unique and permanent. It is.
3. **No Authentication**: The backend is open to any caller on localhost. This is intentional for a personal service. Do **not** expose port 8000 to the internet.
4. **Concurrency**: Limited to 2 concurrent downloads via `ThreadPoolExecutor`. Increase `max_workers` in `main.py` if needed.
5. **Metadata Extraction**: The Tampermonkey script attempts to extract channel name and title from the page DOM. If YouTube changes its structure, the script may need updates. Browser console will log what it extracted.
6. **Thumbnail Embedding**: ffmpeg attempts to embed the thumbnail as cover art. If this fails, the file is still created with basic ID3 metadata.
7. **Storage**: No cleanup happens. Downloaded files persist in the Docker volume indefinitely. To free space, either delete specific files using `docker compose exec youtube-mp3 rm "/data/done/<title>.mp3"` or remove the entire volume with `docker compose down -v`.
8. **No Database**: Filesystem replaces database. Scaling to multiple machines would require a real database.
9. **Browser Availability**: The script only works while you have a browser open. It does **not** download from external sources or scheduled tasks.
10. **URL Parsing**: The Tampermonkey script only detects classic YouTube watch URLs (`youtube.com?v=...`). YouTube Shorts and embedded players may not trigger.

## Troubleshooting

### Docker Service Won't Start

1. Check Docker daemon:

   ```bash
   systemctl status docker
   sudo systemctl start docker
   ```

2. Check for port conflicts:

   ```bash
   netstat -tlnp | grep 8000
   ```

3. View container logs:

   ```bash
   docker logs youtube-mp3-downloader
   ```

### Script Not Detecting Videos

1. Verify Tampermonkey is enabled in the extension menu
2. Open browser console (F12) and check for `[YT-MP3]` logs
3. Try reloading the page (`Ctrl+R`)
4. Check that the script matches `@match https://www.youtube.com/*`

### Downloads Failing

1. Check container logs:

   ```bash
   docker logs youtube-mp3-downloader
   ```

2. Verify yt-dlp is installed and working:

   ```bash
   docker compose exec youtube-mp3 yt-dlp --version
   ```

3. Test with a specific URL:

   ```bash
   docker compose exec youtube-mp3 yt-dlp --extract-audio --audio-format mp3 "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
   ```

### Disk Space Issues

Check Docker volume usage:

```bash
docker system df -v
```

Look for the `youtube-mp3-downloader_youtube-mp3-data` volume in the output. Downloaded files can be several MB each. Plan storage accordingly.

## Security Notes

- **Localhost only**: Bound to `127.0.0.1:8000` by default
- **No auth**: Acceptable for local use only
- **Do not expose**: Never port-forward port 8000 to the internet
- **Trusted browser**: Tampermonkey scripts can access all visited sites; only run scripts you trust

## Performance Notes

- Typical download/convert time: 20–60 seconds depending on video length
- yt-dlp and ffmpeg are CPU-intensive; expect high CPU usage during conversion
- Network bandwidth: Depends on video bitrate (typically 50–500 kB/s)
- Storage: A 10-minute 128 kbps MP3 is roughly 10 MB

## License

This is a personal tool. Use at your own discretion and respect copyright laws in your jurisdiction.

## Contributing / Feedback

Improvements welcome! Feel free to submit issues or PRs.
