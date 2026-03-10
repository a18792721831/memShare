#!/usr/bin/env python3
"""
memShare Sync Tool

Syncs memory data between local storage and remote backend.
Supports: Local copy, Tencent COS, AWS S3

Usage:
    python sync.py sync              # Bidirectional sync (pull then push)
    python sync.py push              # Push local → remote
    python sync.py pull              # Pull remote → local
    python sync.py status            # Show sync status

Environment:
    MEMSHARE_DATA_DIR    Local data directory (default: ~/memshare-data)
    MEMSHARE_STORAGE     Backend type: local/cos/s3 (default: local)
    MEMSHARE_REMOTE_PREFIX  Remote path prefix (default: memshare)
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from storage_backend import create_backend

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("memshare.sync")

# Patterns to exclude from sync
EXCLUDE_PATTERNS = [
    "*.pyc",
    "__pycache__",
    ".DS_Store",
    "*.tmp",
    "*.bak",
]

# Files that should NEVER be synced (contain secrets)
NEVER_SYNC = [
    ".env",
    ".env.local",
]


def get_data_dir() -> Path:
    """Get the local data directory."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    data_dir = os.environ.get("MEMSHARE_DATA_DIR", "~/memshare-data")
    return Path(os.path.expanduser(data_dir))


def get_remote_prefix() -> str:
    """Get the remote storage prefix."""
    return os.environ.get("MEMSHARE_REMOTE_PREFIX", "memshare")


def cmd_push():
    """Push local data to remote storage."""
    data_dir = get_data_dir()
    if not data_dir.exists():
        logger.error(f"Data directory not found: {data_dir}")
        logger.info("Run 'python setup.py' to initialize memShare first.")
        sys.exit(1)

    backend = create_backend()
    prefix = get_remote_prefix()
    exclude = EXCLUDE_PATTERNS + NEVER_SYNC

    logger.info(f"Pushing {data_dir} → {type(backend).__name__}:{prefix}")
    result = backend.push(str(data_dir), prefix, exclude=exclude)

    logger.info(
        f"Push complete: {result['uploaded']} uploaded, "
        f"{result['skipped']} skipped"
    )
    if result["errors"]:
        for err in result["errors"]:
            logger.error(f"  Error: {err}")
        sys.exit(1)


def cmd_pull():
    """Pull remote data to local storage."""
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    backend = create_backend()
    prefix = get_remote_prefix()
    exclude = EXCLUDE_PATTERNS + NEVER_SYNC

    logger.info(f"Pulling {type(backend).__name__}:{prefix} → {data_dir}")
    result = backend.pull(prefix, str(data_dir), exclude=exclude)

    logger.info(
        f"Pull complete: {result['downloaded']} downloaded, "
        f"{result['skipped']} skipped"
    )
    if result["errors"]:
        for err in result["errors"]:
            logger.error(f"  Error: {err}")
        sys.exit(1)


def cmd_status():
    """Show sync status."""
    data_dir = get_data_dir()
    backend_type = os.environ.get("MEMSHARE_STORAGE", "local")
    prefix = get_remote_prefix()

    print(f"memShare Sync Status")
    print(f"{'=' * 40}")
    print(f"Data directory : {data_dir}")
    print(f"Backend        : {backend_type}")
    print(f"Remote prefix  : {prefix}")
    print(f"Data exists    : {data_dir.exists()}")

    if data_dir.exists():
        files = list(data_dir.rglob("*"))
        file_count = sum(1 for f in files if f.is_file())
        print(f"Local files    : {file_count}")

    try:
        backend = create_backend()
        remote_files = backend.list_files(prefix)
        print(f"Remote files   : {len(remote_files)}")
    except Exception as e:
        print(f"Remote status  : Error - {e}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()
    commands = {
        "sync": cmd_sync,
        "push": cmd_push,
        "pull": cmd_pull,
        "status": cmd_status,
    }

    if cmd in commands:
        commands[cmd]()
    else:
        print(f"Unknown command: {cmd}")
        print(f"Available commands: {', '.join(commands.keys())}")
        sys.exit(1)


if __name__ == "__main__":
    main()
