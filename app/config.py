"""
Central configuration: logging setup, directory paths, global constants,
and shared executor used across the app.
"""
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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

# ---------------------------------------------------------------------------
# Failed-download retry timing
# ---------------------------------------------------------------------------

RETRY_INTERVAL_SECONDS = 24 * 60 * 60  # 24 hours
RETRY_STARTUP_DELAY_SECONDS = 30       # wait after service starts before first retry