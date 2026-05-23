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
- A **YouTube account** logged in to your browser (needed for cookie-based authentication)

## Files

| File                             | Purpose                                                 |
| -------------------------------- | ------------------------------------------------------- |
| `main.py`                        | FastAPI backend service                                 |
| `requirements.txt`               | Python dependencies                                     |
| `Dockerfile`                     | Docker image definition                                 |
| `docker-compose.yml`             | Docker Compose configuration                            |
| `youtube-mp3-downloader.user.js` | Tampermonkey script                                     |
| `cookies.txt`                    | YouTube session cookies (you generate this — see below) |
| `README.md`                      | This file                                               |

## Setup & Installation

### 1. Clone or Download This Project

```bash
git clone <repo-url> ~/youtube-mp3-downloader
cd ~/youtube-mp3-downloader
```

### 2. Export YouTube Cookies

YouTube requires authentication to serve video streams from server IPs. yt-dlp reads cookies directly from your browser.

Make sure you are **logged in to YouTube** in your browser, then run on the host (not inside Docker):

```bash
# Firefox (recommended)
yt-dlp --cookies-from-browser firefox --cookies cookies.txt --skip-download "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Or Chrome
yt-dlp --cookies-from-browser chrome --cookies cookies.txt --skip-download "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

This creates `cookies.txt` in the project directory — it's bind-mounted into the container automatically.

> **Note:** `cookies.txt` contains your Google session. It is listed in `.gitignore` and should never be committed to git.

**When to refresh cookies:** If downloads start failing with _"cookies are no longer valid"_ or _"Sign in to confirm you're not a bot"_, simply re-run the command above. No rebuild needed.

### 3. Build and Start Docker Service

```bash
docker compose up -d --build
```

Verify the service is running:

```bash
docker compose ps
docker logs youtube-mp3-downloader
```

You should see logs indicating the service is listening on `127.0.0.1:8000`.

### 4. Install Tampermonkey Script

1. Install **Tampermonkey** extension for your browser
   - [Firefox](https://addons.mozilla.org/en-US/firefox/addon/tampermonkey/)
   - [Chrome](https://chrome.google.com/webstore/detail/tampermonkey/dhdgffkkebhmkfjojejmpbldmpobp55f)

2. Open the Tampermonkey dashboard and click **Create a new script**
3. Copy the entire contents of `youtube-mp3-downloader.user.js` and paste it
4. Save (Ctrl+S)
5. Enable the script in the Tampermonkey dashboard

### 5. Test

1. Open `https://youtube.com` in your browser
2. Search for and play any video
3. Open the browser console (F12) and look for logs starting with `[YT-MP3]`
4. You should see a POST request to `http://127.0.0.1:8000/seen` with status `PROCESSING`
5. Check the backend logs:
   ```bash
   docker logs -f youtube-mp3-downloader
   ```

Once the download completes (usually within 30 seconds), the log will show `Successfully downloaded and processed`.

## How YouTube Authentication Works

YouTube bot-detects headless downloaders by IP. The service works around this using three layers:

| Layer                                             | What it does                                                                          |
| ------------------------------------------------- | ------------------------------------------------------------------------------------- |
| **Cookies** (`cookies.txt`)                       | Authenticates as your Google account — bypasses bot checks                            |
| **Player clients** (`web,mweb,tv`)                | Uses multiple YouTube internal clients; if one is blocked, others succeed             |
| **Deno + EJS** (`--remote-components ejs:github`) | Solves YouTube's JS signature and n-challenge — required to decrypt video stream URLs |

The Docker image includes both **Node.js** and **Deno** as JS runtimes. Deno is yt-dlp's preferred runtime for challenge solving.

## Usage

### Normal Operation

1. Browse YouTube as usual
2. When you play a video, the script automatically sends it to the backend
3. The backend downloads and converts in the background — **no blocking**
4. MP3 files are saved inside the Docker volume at `/data/done/`

### Managing Downloads (Moving/Cutting to Local Storage)

Access files using Docker commands:

```bash
# List downloaded MP3 files
docker compose exec youtube-mp3 ls /data/done/

# Copy a file to host
docker cp youtube-mp3-downloader:/data/done/<filename>.mp3 ~/Downloads/

# Copy all files to host
docker cp youtube-mp3-downloader:/data/done/. ~/Downloads/youtube-mp3/
```

**How to "Cut" (Move without Re-downloading)**
The script checks for the existence of the metadata JSON file in `/data/meta/` to prevent duplicate downloads. You can safely cut (copy then delete) the MP3 files without triggering re-downloads.

```bash
# 1. Copy all MP3s to your local machine
docker cp youtube-mp3-downloader:/data/done/. ~/Downloads/youtube-mp3/

# 2. Delete the copied MP3s from the Docker container to free up space
docker compose exec youtube-mp3 sh -c 'rm /data/done/*.mp3'
```

Files are named by sanitized video title + video ID, e.g., `Rick_Astley_Never_Gonna_Give_You_Up_dQw4w9WgXcQ.mp3`.

### Retry Failed Downloads

Failed downloads are **automatically retried every 24 hours** after service startup. No manual intervention needed.

Each failed video's state is stored as a JSON file in `/data/failed/` with `title`, `channel`, `retry_count`, and `last_error` — so retries use the correct metadata.

If a video is played again in the browser while it's in the failed list, it is **immediately requeued** rather than returning a FAILED status.

To trigger a manual retry of all failed downloads right now:

```bash
curl -X POST http://127.0.0.1:8000/retry-failed
```

To clear a specific failed video and retry it immediately, just play it in the browser again.

### View Metadata

```bash
docker compose exec youtube-mp3 cat /data/meta/<videoId>.json
```

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
/app/
├── main.py
└── cookies.txt          ← bind-mounted from host project directory

/data/
├── done/
│   ├── Rick_Astley_Never_Gonna_Give_You_Up_dQw4w9WgXcQ.mp3
│   └── ...
├── meta/
│   ├── dQw4w9WgXcQ.json
│   └── ...
└── failed/
    └── <videoId>        ← empty marker file; delete to retry
```

`/data` is backed by a Docker named volume (`youtube-mp3-data`). Use `docker cp` or `docker compose exec` to access files from the host.

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

- **READY**: MP3 already exists — `{"status": "READY", "videoId": "..."}`
- **PROCESSING**: Download queued (including immediate requeue of previously failed videos) — `{"status": "PROCESSING", "videoId": "..."}`

### GET /health

```json
{ "status": "ok" }
```

### GET /stats

```json
{
  "downloaded": 10,
  "failed": 2,
  "failed_details": [
    {
      "videoId": "LEZoOCsKdYQ",
      "title": "Energy - Ceui",
      "retry_count": 3,
      "last_failed_at": "2026-03-04T05:00:00"
    }
  ],
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

## Troubleshooting

### "Sign in to confirm you're not a bot" / "cookies are no longer valid"

Your `cookies.txt` has expired or been rotated by YouTube. Refresh it:

```bash
yt-dlp --cookies-from-browser firefox --cookies cookies.txt --skip-download "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

No rebuild needed — the file is bind-mounted. Then clear any failed markers and retrigger by playing the video again:

```bash
docker exec youtube-mp3-downloader sh -c 'rm -f /data/failed/*'
```

### "Signature solving failed" / "n challenge solving failed"

Deno may have failed to download the EJS challenge solver script (requires internet access from the container). Check:

```bash
docker exec youtube-mp3-downloader deno --version
docker logs youtube-mp3-downloader
```

### Docker Service Won't Start

```bash
systemctl status docker
sudo systemctl start docker
netstat -tlnp | grep 8000   # check for port conflicts
docker logs youtube-mp3-downloader
```

### Script Not Detecting Videos

1. Verify Tampermonkey is enabled in the extension menu
2. Open browser console (F12) and check for `[YT-MP3]` logs
3. Try reloading the page (`Ctrl+R`)
4. Check that the script matches `@match https://www.youtube.com/*`

### Downloads Failing (General)

```bash
# Check logs
docker logs youtube-mp3-downloader

# Test yt-dlp manually inside container
docker exec youtube-mp3-downloader yt-dlp --cookies /app/cookies.txt \
  --extractor-args "youtube:player_client=web,mweb,tv" \
  --remote-components ejs:github \
  --skip-download "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### Disk Space Issues

```bash
docker system df -v
```

Look for the `youtube-mp3-downloader_youtube-mp3-data` volume. A 10-minute 192 kbps MP3 is roughly 14 MB.

## Known Limitations

1. **YouTube Compatibility**: yt-dlp depends on YouTube's API. Keep yt-dlp updated if things break.
2. **Cookie Expiry**: YouTube rotates cookies periodically. Re-export when downloads start failing.
3. **No Authentication**: Backend is open to any localhost caller. Do **not** expose port 8000 to the internet.
4. **Concurrency**: Limited to 2 concurrent downloads. Increase `max_workers` in `main.py` if needed.
5. **Shorts / Embeds**: The Tampermonkey script only detects classic `youtube.com/watch?v=...` URLs.
6. **Storage**: No automatic cleanup. Files persist in the Docker volume indefinitely.
7. **Browser Required**: The script only runs while your browser is open.

## Security Notes

- **Localhost only**: Bound to `127.0.0.1:8000` — not reachable from the network
- **Do not expose**: Never port-forward port 8000 to the internet
- **cookies.txt**: Contains your Google session cookie — keep it private, never commit to git

## License

Personal tool. Use at your own discretion and respect copyright laws in your jurisdiction.
