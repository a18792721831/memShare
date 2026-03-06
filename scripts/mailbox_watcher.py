#!/usr/bin/env python3
"""
memShare Mailbox Watcher

Watches agent mailboxes for new messages and triggers actions:
- Notifies the user via pluggable channels (Fly Pigeon / macOS / custom)
- Auto-processes `request` type messages via configurable task handlers

Supports two run modes:
- Daemon: Long-running process with configurable poll interval
- Oneshot: Single check (for crontab)

Usage:
    python mailbox_watcher.py daemon              # Run as daemon
    python mailbox_watcher.py oneshot              # Single check (crontab)
    python mailbox_watcher.py daemon --interval 30 # Custom poll interval (seconds)

Environment:
    MEMSHARE_DATA_DIR       Data directory (default: ~/memshare-data)
    WATCHER_POLL_INTERVAL   Poll interval in seconds (default: 60)
    WATCHER_AGENTS          Comma-separated agent names to watch (default: all)
    WATCHER_NOTIFY_CHANNELS Comma-separated notify channels (default: log)
    PIGEON_API_URL          Fly Pigeon API URL (for wecom notifications)
    PIGEON_SEND_TO          Comma-separated RTX names for Fly Pigeon
    PIGEON_SEND_FROM        Sender name for Fly Pigeon (default: memShare)
"""

import os
import re
import sys
import json
import time
import signal
import logging
import argparse
import importlib
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime
from typing import Optional

# Add parent directory for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("memshare.watcher")

# Load env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass


# ============================================================
# Data Models
# ============================================================

class MailMessage:
    """Parsed mailbox message."""

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.filename = filepath.name
        self.from_agent = ""
        self.to_agent = ""
        self.timestamp = ""
        self.msg_type = "message"
        self.status = "unread"
        self.subject = ""
        self.body = ""
        self.raw_content = ""
        self._parse()

    def _parse(self):
        """Parse message file (YAML frontmatter + markdown body)."""
        self.raw_content = self.filepath.read_text(encoding="utf-8")
        content = self.raw_content

        # Parse YAML frontmatter
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                frontmatter = parts[1].strip()
                self.body = parts[2].strip()

                for line in frontmatter.split("\n"):
                    line = line.strip()
                    if ":" in line:
                        key, val = line.split(":", 1)
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if key == "from":
                            self.from_agent = val
                        elif key == "to":
                            self.to_agent = val
                        elif key == "timestamp":
                            self.timestamp = val
                        elif key == "type":
                            self.msg_type = val
                        elif key == "status":
                            self.status = val

        # Extract subject from body
        for line in self.body.split("\n"):
            line = line.strip()
            if line.startswith("## "):
                self.subject = line[3:].strip()
                break

    @property
    def is_unread(self) -> bool:
        return self.status in ("unread", "sent")

    @property
    def is_request(self) -> bool:
        return self.msg_type == "request"

    def __repr__(self):
        return (
            f"MailMessage(from={self.from_agent}, to={self.to_agent}, "
            f"type={self.msg_type}, status={self.status}, subject={self.subject!r})"
        )


# ============================================================
# Notification Channel Interface (Plugin System)
# ============================================================

class NotifyChannel(ABC):
    """Abstract notification channel."""

    @abstractmethod
    def name(self) -> str:
        """Channel identifier."""
        pass

    @abstractmethod
    def send(self, title: str, body: str, messages: list[MailMessage]) -> bool:
        """
        Send a notification.

        Args:
            title: Notification title
            body: Notification body text
            messages: List of MailMessage objects that triggered this notification

        Returns:
            True if sent successfully
        """
        pass


class LogChannel(NotifyChannel):
    """Log-based notification (always enabled, for debugging)."""

    def name(self) -> str:
        return "log"

    def send(self, title: str, body: str, messages: list[MailMessage]) -> bool:
        logger.info(f"📬 {title}: {body}")
        return True


class FlyPigeonChannel(NotifyChannel):
    """
    Fly Pigeon (飞鸽传书) — WeChat Work notification.

    Env:
        PIGEON_API_URL   API endpoint (default: dev env, no HMAC needed)
        PIGEON_SEND_TO   Comma-separated RTX names
        PIGEON_SEND_FROM Sender name (default: memShare)
    """

    def __init__(self):
        self.api_url = os.environ.get(
            "PIGEON_API_URL",
            "http://dev.ngate.tencent-cloud.com/pigeon/v1/wecom/notify",
        )
        self.send_to = [
            s.strip()
            for s in os.environ.get("PIGEON_SEND_TO", "").split(",")
            if s.strip()
        ]
        self.send_from = os.environ.get("PIGEON_SEND_FROM", "memShare")

    def name(self) -> str:
        return "pigeon"

    def send(self, title: str, body: str, messages: list[MailMessage]) -> bool:
        if not self.api_url:
            logger.warning("FlyPigeon: PIGEON_API_URL not configured, skipping")
            return False
        if not self.send_to:
            logger.warning("FlyPigeon: PIGEON_SEND_TO not configured, skipping")
            return False

        try:
            import urllib.request
            import urllib.error

            payload = json.dumps({
                "sendFrom": self.send_from,
                "sendTo": self.send_to,
                "msgTitle": title,
                "msgContent": body,
            }).encode("utf-8")

            req = urllib.request.Request(
                self.api_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                logger.info(f"FlyPigeon sent: {result}")
                return True
        except Exception as e:
            logger.error(f"FlyPigeon failed: {e}")
            return False


class MacOSNotifyChannel(NotifyChannel):
    """macOS Notification Center via osascript."""

    def name(self) -> str:
        return "macos"

    def send(self, title: str, body: str, messages: list[MailMessage]) -> bool:
        if sys.platform != "darwin":
            logger.warning("macOS notification only works on macOS")
            return False

        try:
            import subprocess
            # Escape for AppleScript
            title_esc = title.replace('"', '\\"')
            body_esc = body.replace('"', '\\"')
            script = (
                f'display notification "{body_esc}" '
                f'with title "{title_esc}" sound name "default"'
            )
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=5,
            )
            return True
        except Exception as e:
            logger.error(f"macOS notification failed: {e}")
            return False


class OpenClawWeComChannel(NotifyChannel):
    """
    WeChat Work notification via OpenClaw relay.

    Instead of calling the WeChat Work API directly, this channel writes a
    `type: request, action: wecom_notify` message into OpenClaw's mailbox.
    OpenClaw picks it up on its next cron pull and forwards to the user
    via its built-in WeChat Work application message API.

    Config (env or config file):
        OPENCLAW_MAILBOX_DIR  Path to OpenClaw mailbox (auto-detected from data_dir)
        OPENCLAW_NOTIFY_TO    RTX name of the user to notify (required, no default)
    """

    def __init__(self, data_dir: Path = None):
        self._data_dir = data_dir
        self.notify_to = os.environ.get("OPENCLAW_NOTIFY_TO", "")

    def _get_mailbox_dir(self) -> Path:
        """Resolve OpenClaw's mailbox directory."""
        if self._data_dir:
            return self._data_dir / "mailbox" / "to-openclaw"
        # Fallback: standard memshare-data location
        return Path(os.path.expanduser(
            os.environ.get(
                "OPENCLAW_MAILBOX_DIR",
                "~/memshare-data/mailbox/to-openclaw",
            )
        ))

    def name(self) -> str:
        return "openclaw_wecom"

    def send(self, title: str, body: str, messages: list[MailMessage]) -> bool:
        if not self.notify_to:
            logger.warning("OpenClawWecom: OPENCLAW_NOTIFY_TO not configured, skipping")
            return False
        mailbox = self._get_mailbox_dir()
        mailbox.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        filename = f"{now.strftime('%Y%m%d_%H%M%S')}_watcher.md"
        filepath = mailbox / filename

        # Build concise notification body for WeChat Work
        msg_lines = []
        for msg in messages:
            type_emoji = {
                "message": "💬", "request": "📋",
                "response": "↩️", "notification": "🔔",
            }.get(msg.msg_type, "📧")
            preview = msg.body[:80].replace("\n", " ").strip()
            if len(msg.body) > 80:
                preview += "..."
            msg_lines.append(
                f"{type_emoji} {msg.from_agent} → {msg.to_agent}: "
                f"{msg.subject or '(no subject)'}\n{preview}"
            )

        wecom_body = "\n\n".join(msg_lines)

        content = f"""---
from: watcher
to: openclaw
timestamp: "{now.isoformat()}"
type: request
action: wecom_notify
status: unread
---

## 企微通知转发请求

请帮忙通过企微推送以下通知给用户 **{self.notify_to}**：

**标题**: {title}

**内容**:
{wecom_body}

---
*Auto-generated by memShare mailbox watcher*
"""
        try:
            filepath.write_text(content, encoding="utf-8")
            logger.info(
                f"OpenClaw WeChat relay: wrote request to {filepath.name} "
                f"({len(messages)} msg(s))"
            )
            return True
        except Exception as e:
            logger.error(f"OpenClaw WeChat relay failed: {e}")
            return False


# Channel registry
BUILTIN_CHANNELS = {
    "log": LogChannel,
    "pigeon": FlyPigeonChannel,
    "macos": MacOSNotifyChannel,
    "openclaw_wecom": OpenClawWeComChannel,
}


# ============================================================
# Task Handler Interface (for request-type messages)
# ============================================================

class TaskHandler(ABC):
    """Abstract handler for request-type messages."""

    @abstractmethod
    def can_handle(self, message: MailMessage) -> bool:
        """Check if this handler can process the message."""
        pass

    @abstractmethod
    def handle(self, message: MailMessage, data_dir: Path) -> Optional[str]:
        """
        Process the message.

        Args:
            message: The request message to process
            data_dir: memShare data directory

        Returns:
            Response text if handled, None if skipped
        """
        pass


class SyncRequestHandler(TaskHandler):
    """Handle sync requests — triggers a pull+push cycle."""

    def can_handle(self, message: MailMessage) -> bool:
        keywords = ["sync", "同步", "pull", "push"]
        text = (message.subject + " " + message.body).lower()
        return message.is_request and any(kw in text for kw in keywords)

    def handle(self, message: MailMessage, data_dir: Path) -> Optional[str]:
        logger.info(f"Handling sync request from {message.from_agent}")
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from storage_backend import create_backend

            backend = create_backend()
            prefix = os.environ.get("MEMSHARE_REMOTE_PREFIX", "memshare")

            # Pull first, then push
            pull_result = backend.pull(prefix, str(data_dir))
            push_result = backend.push(str(data_dir), prefix)

            return (
                f"Sync complete: pulled {pull_result['downloaded']}, "
                f"pushed {push_result['uploaded']}"
            )
        except Exception as e:
            logger.error(f"Sync request failed: {e}")
            return f"Sync failed: {e}"


class MemoryQueryHandler(TaskHandler):
    """Handle memory query requests — looks up info and replies."""

    def can_handle(self, message: MailMessage) -> bool:
        keywords = ["查询", "query", "lookup", "查找", "记忆", "memory"]
        text = (message.subject + " " + message.body).lower()
        return message.is_request and any(kw in text for kw in keywords)

    def handle(self, message: MailMessage, data_dir: Path) -> Optional[str]:
        logger.info(f"Handling memory query from {message.from_agent}")

        # Extract search terms from body
        search_text = message.body.lower()

        results = []

        # Search in MEMORY.md
        memory_file = data_dir / "MEMORY.md"
        if memory_file.exists():
            content = memory_file.read_text(encoding="utf-8")
            # Simple keyword matching
            for line in content.split("\n"):
                if any(word in line.lower() for word in search_text.split()[:5]):
                    results.append(line.strip())
                    if len(results) >= 10:
                        break

        # Search in recent daily memories
        daily_dir = data_dir / "daily-memories"
        if daily_dir.exists():
            for f in sorted(daily_dir.glob("*.md"), reverse=True)[:7]:
                content = f.read_text(encoding="utf-8")
                for line in content.split("\n"):
                    if any(word in line.lower() for word in search_text.split()[:5]):
                        results.append(f"[{f.stem}] {line.strip()}")
                        if len(results) >= 20:
                            break

        if results:
            return "Found relevant memories:\n" + "\n".join(results[:20])
        return "No matching memories found."


# Handler registry
BUILTIN_HANDLERS = [
    SyncRequestHandler(),
    MemoryQueryHandler(),
]


# ============================================================
# Mailbox Watcher Core
# ============================================================

class MailboxWatcher:
    """
    Core watcher engine.

    Scans mailbox directories for unread messages, dispatches notifications
    and handles request-type messages.
    """

    def __init__(
        self,
        data_dir: Path,
        agents: list[str] = None,
        notify_channels: list[NotifyChannel] = None,
        task_handlers: list[TaskHandler] = None,
        state_file: Path = None,
    ):
        self.data_dir = data_dir
        self.mailbox_dir = data_dir / "mailbox"
        self.agents = agents  # None = watch all
        self.channels = notify_channels or [LogChannel()]
        self.handlers = task_handlers or BUILTIN_HANDLERS
        self.state_file = state_file or (data_dir / ".watcher_state.json")
        self.state = self._load_state()

    def _load_state(self) -> dict:
        """Load watcher state (tracks processed messages)."""
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                pass
        return {"processed": {}, "last_check": None}

    def _save_state(self):
        """Save watcher state."""
        self.state["last_check"] = datetime.now().isoformat()
        self.state_file.write_text(
            json.dumps(self.state, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _get_watched_inboxes(self) -> list[Path]:
        """Get list of inbox directories to watch."""
        if not self.mailbox_dir.exists():
            return []

        inboxes = []
        for d in self.mailbox_dir.iterdir():
            if not d.is_dir() or not d.name.startswith("to-"):
                continue
            agent_name = d.name[3:]  # Remove "to-" prefix
            if self.agents is None or agent_name in self.agents:
                inboxes.append(d)
        return inboxes

    def scan(self) -> list[MailMessage]:
        """
        Scan all watched inboxes for unread messages.

        Returns:
            List of unread MailMessage objects
        """
        unread = []
        for inbox in self._get_watched_inboxes():
            for f in sorted(inbox.glob("*.md")):
                if f.name.lower() == "protocol.md":
                    continue

                # Skip already-processed files (by filename)
                if f.name in self.state.get("processed", {}):
                    continue

                try:
                    msg = MailMessage(f)
                    if msg.is_unread and msg.from_agent != "watcher":
                        unread.append(msg)
                except Exception as e:
                    logger.warning(f"Failed to parse {f}: {e}")

        return unread

    def notify(self, messages: list[MailMessage]):
        """Send notifications for new messages via all configured channels."""
        if not messages:
            return

        # Group by recipient
        by_recipient = {}
        for msg in messages:
            by_recipient.setdefault(msg.to_agent, []).append(msg)

        for recipient, msgs in by_recipient.items():
            # Build notification content
            title = f"📬 memShare: {len(msgs)} new message(s) for {recipient}"

            lines = []
            for msg in msgs:
                type_emoji = {
                    "message": "💬",
                    "request": "📋",
                    "response": "↩️",
                    "notification": "🔔",
                }.get(msg.msg_type, "📧")

                preview = msg.body[:100].replace("\n", " ").strip()
                if len(msg.body) > 100:
                    preview += "..."

                lines.append(
                    f"{type_emoji} [{msg.msg_type}] from {msg.from_agent}: "
                    f"{msg.subject or '(no subject)'}\n   {preview}"
                )

            body = "\n\n".join(lines)

            # Send via all channels
            for channel in self.channels:
                try:
                    channel.send(title, body, msgs)
                except Exception as e:
                    logger.error(f"Channel {channel.name()} failed: {e}")

    def process_requests(self, messages: list[MailMessage]):
        """
        Auto-process request-type messages.

        For each request message, try all handlers. If a handler succeeds,
        write a response message back to the sender's inbox.
        """
        for msg in messages:
            if not msg.is_request:
                continue

            logger.info(f"Processing request: {msg.subject} from {msg.from_agent}")

            for handler in self.handlers:
                if handler.can_handle(msg):
                    try:
                        result = handler.handle(msg, self.data_dir)
                        if result:
                            self._send_response(msg, result)
                            logger.info(
                                f"Request handled by {type(handler).__name__}: "
                                f"{result[:100]}"
                            )
                            break
                    except Exception as e:
                        logger.error(
                            f"Handler {type(handler).__name__} failed: {e}"
                        )

    def _send_response(self, original: MailMessage, response_text: str):
        """Send an auto-response to the original sender."""
        sender_inbox = self.mailbox_dir / f"to-{original.from_agent}"
        sender_inbox.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        responder = original.to_agent or "watcher"
        filename = f"{now.strftime('%Y%m%d_%H%M%S')}_{responder}.md"
        filepath = sender_inbox / filename

        content = f"""---
from: {responder}
to: {original.from_agent}
timestamp: "{now.isoformat()}"
type: response
status: unread
ref: {original.filename}
---

## Re: {original.subject}

{response_text}

---
*Auto-processed by memShare mailbox watcher*
"""
        filepath.write_text(content, encoding="utf-8")
        logger.info(f"Response sent to {original.from_agent}: {filename}")

    def mark_processed(self, messages: list[MailMessage]):
        """Mark messages as processed in watcher state."""
        for msg in messages:
            self.state.setdefault("processed", {})[msg.filename] = {
                "from": msg.from_agent,
                "type": msg.msg_type,
                "processed_at": datetime.now().isoformat(),
            }
        self._save_state()

    def run_once(self) -> int:
        """
        Run a single check cycle.

        Returns:
            Number of new messages found
        """
        messages = self.scan()
        if not messages:
            logger.debug("No new messages")
            return 0

        logger.info(f"Found {len(messages)} new message(s)")

        # Step 1: Notify
        self.notify(messages)

        # Step 2: Auto-process requests
        self.process_requests(messages)

        # Step 3: Mark as processed
        self.mark_processed(messages)

        return len(messages)

    def run_daemon(self, interval: int = 60):
        """
        Run as a daemon with periodic polling.

        Args:
            interval: Seconds between checks
        """
        logger.info(
            f"Mailbox watcher daemon started (interval={interval}s, "
            f"agents={self.agents or 'all'})"
        )

        # Graceful shutdown
        running = True

        def _signal_handler(sig, frame):
            nonlocal running
            logger.info("Shutdown signal received, stopping...")
            running = False

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        while running:
            try:
                self.run_once()
            except Exception as e:
                logger.error(f"Check cycle failed: {e}")

            # Interruptible sleep
            for _ in range(interval):
                if not running:
                    break
                time.sleep(1)

        logger.info("Mailbox watcher daemon stopped")


# ============================================================
# State Cleanup
# ============================================================

def cleanup_state(data_dir: Path, max_age_days: int = 7):
    """Remove old entries from watcher state to prevent unbounded growth."""
    state_file = data_dir / ".watcher_state.json"
    if not state_file.exists():
        return

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        processed = state.get("processed", {})
        cutoff = datetime.now().timestamp() - (max_age_days * 86400)

        cleaned = {}
        for filename, info in processed.items():
            try:
                ts = datetime.fromisoformat(info.get("processed_at", "")).timestamp()
                if ts > cutoff:
                    cleaned[filename] = info
            except (ValueError, TypeError):
                # Keep entries with unparseable timestamps
                cleaned[filename] = info

        state["processed"] = cleaned
        state_file.write_text(
            json.dumps(state, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        removed = len(processed) - len(cleaned)
        if removed:
            logger.info(f"Cleaned {removed} old entries from watcher state")
    except Exception as e:
        logger.warning(f"State cleanup failed: {e}")


# ============================================================
# Configuration
# ============================================================

def load_config(config_file: Path = None) -> dict:
    """
    Load watcher configuration.

    Priority: config file → environment variables → defaults.
    """
    config = {
        "data_dir": os.environ.get("MEMSHARE_DATA_DIR", "~/memshare-data"),
        "poll_interval": int(os.environ.get("WATCHER_POLL_INTERVAL", "60")),
        "agents": None,  # None = all
        "notify_channels": os.environ.get("WATCHER_NOTIFY_CHANNELS", "log").split(","),
        "auto_process_requests": True,
        "state_cleanup_days": 7,
    }

    # Agent filter
    agents_env = os.environ.get("WATCHER_AGENTS", "").strip()
    if agents_env:
        config["agents"] = [a.strip() for a in agents_env.split(",") if a.strip()]

    # Config file override
    if config_file and config_file.exists():
        try:
            file_config = json.loads(config_file.read_text(encoding="utf-8"))
            config.update(file_config)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to load config file {config_file}: {e}")

    return config


def build_channels(channel_names: list[str], data_dir: Path = None) -> list[NotifyChannel]:
    """Build notification channel instances from names."""
    channels = []
    for name in channel_names:
        name = name.strip().lower()
        if name in BUILTIN_CHANNELS:
            cls = BUILTIN_CHANNELS[name]
            # Pass data_dir to channels that accept it
            if cls is OpenClawWeComChannel and data_dir:
                channels.append(cls(data_dir=data_dir))
            else:
                channels.append(cls())
        else:
            logger.warning(f"Unknown notification channel: {name}")

    # Always include log channel
    if not any(isinstance(c, LogChannel) for c in channels):
        channels.insert(0, LogChannel())

    return channels


# ============================================================
# CLI Entry Point
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="memShare Mailbox Watcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s daemon                     Run as daemon (default interval: 60s)
  %(prog)s daemon --interval 30       Custom poll interval
  %(prog)s oneshot                    Single check (for crontab)
  %(prog)s oneshot --channels pigeon  Single check with Fly Pigeon notification
  %(prog)s cleanup                    Clean old watcher state entries
        """,
    )
    parser.add_argument(
        "mode",
        choices=["daemon", "oneshot", "cleanup"],
        help="Run mode: daemon (long-running), oneshot (single check), cleanup (state maintenance)",
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=None,
        help="Poll interval in seconds (daemon mode only, default: 60)",
    )
    parser.add_argument(
        "--agents", "-a",
        type=str,
        default=None,
        help="Comma-separated agent names to watch (default: all)",
    )
    parser.add_argument(
        "--channels", "-c",
        type=str,
        default=None,
        help="Comma-separated notification channels (default: log)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to JSON config file",
    )
    parser.add_argument(
        "--no-auto-process",
        action="store_true",
        help="Disable auto-processing of request messages",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load config
    config_file = Path(args.config) if args.config else None
    config = load_config(config_file)

    # CLI overrides
    if args.interval is not None:
        config["poll_interval"] = args.interval
    if args.agents:
        config["agents"] = [a.strip() for a in args.agents.split(",")]
    if args.channels:
        config["notify_channels"] = [c.strip() for c in args.channels.split(",")]
    if args.no_auto_process:
        config["auto_process_requests"] = False

    data_dir = Path(os.path.expanduser(config["data_dir"]))

    if args.mode == "cleanup":
        cleanup_state(data_dir, config.get("state_cleanup_days", 7))
        return

    # Build watcher
    channels = build_channels(config["notify_channels"], data_dir=data_dir)
    handlers = BUILTIN_HANDLERS if config.get("auto_process_requests", True) else []

    watcher = MailboxWatcher(
        data_dir=data_dir,
        agents=config.get("agents"),
        notify_channels=channels,
        task_handlers=handlers,
    )

    if args.mode == "daemon":
        watcher.run_daemon(config["poll_interval"])
    elif args.mode == "oneshot":
        count = watcher.run_once()
        if count:
            logger.info(f"Processed {count} new message(s)")
        else:
            logger.info("No new messages")


if __name__ == "__main__":
    main()
