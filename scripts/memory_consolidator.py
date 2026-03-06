#!/usr/bin/env python3
"""
memShare Memory Consolidator

Consolidates daily memories into a long-term memory file (MEMORY.md).
Promotes frequently recurring learnings into permanent rules.

Usage:
    python memory_consolidator.py consolidate   # Merge daily → MEMORY.md
    python memory_consolidator.py promote        # Promote learnings (recurrence ≥ 3)
    python memory_consolidator.py all            # Both consolidate + promote
    python memory_consolidator.py cleanup        # Archive old daily memories

Schedule via crontab:
    0 23 * * * cd /path/to/memshare-data && python3 /path/to/memory_consolidator.py all
"""

import os
import re
import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("memshare.consolidator")


def get_data_dir() -> Path:
    """Get the data directory from env or default."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    data_dir = os.environ.get("MEMSHARE_DATA_DIR", "~/memshare-data")
    return Path(os.path.expanduser(data_dir))


def consolidate(data_dir: Path):
    """
    Consolidate daily memories into MEMORY.md

    Strategy:
    - Last 7 days: Keep detailed records
    - 8-30 days: Summarize to key points
    - 30+ days: Archive to monthly summaries
    """
    daily_dir = data_dir / "daily-memories"
    memory_file = data_dir / "MEMORY.md"

    if not daily_dir.exists():
        logger.info("No daily-memories directory found, skipping.")
        return

    today = datetime.now().date()
    entries = []

    # Read all daily memory files
    for f in sorted(daily_dir.glob("*.md")):
        try:
            date_str = f.stem  # e.g., "2026-03-05"
            file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            age_days = (today - file_date).days
            content = f.read_text(encoding="utf-8")
            entries.append({
                "date": date_str,
                "file_date": file_date,
                "age_days": age_days,
                "content": content,
                "path": f,
            })
        except (ValueError, UnicodeDecodeError) as e:
            logger.warning(f"Skipping {f.name}: {e}")

    if not entries:
        logger.info("No daily memories to consolidate.")
        return

    # Build consolidated memory
    sections = []
    sections.append("# Long-Term Memory\n")
    sections.append(f"*Last consolidated: {today.isoformat()}*\n")

    # Recent (last 7 days) - keep full detail
    recent = [e for e in entries if e["age_days"] <= 7]
    if recent:
        sections.append("\n## Recent (Last 7 Days)\n")
        for entry in recent:
            # Extract key points section if exists
            key_points = _extract_section(entry["content"], "今日要点")
            if key_points:
                sections.append(f"### {entry['date']}\n{key_points}\n")
            else:
                # Take first 500 chars as summary
                summary = entry["content"][:500]
                if len(entry["content"]) > 500:
                    summary += "\n...(truncated)"
                sections.append(f"### {entry['date']}\n{summary}\n")

    # Medium term (8-30 days) - key points only
    medium = [e for e in entries if 7 < e["age_days"] <= 30]
    if medium:
        sections.append("\n## This Month\n")
        for entry in medium:
            key_points = _extract_section(entry["content"], "今日要点")
            if key_points:
                sections.append(f"- **{entry['date']}**: {key_points.strip()}\n")
            else:
                first_line = entry["content"].split("\n")[0].strip("# ")
                sections.append(f"- **{entry['date']}**: {first_line}\n")

    # Long term (30+ days) - monthly grouping
    old = [e for e in entries if e["age_days"] > 30]
    if old:
        sections.append("\n## Archive\n")
        months = {}
        for entry in old:
            month_key = entry["date"][:7]  # "2026-02"
            if month_key not in months:
                months[month_key] = []
            months[month_key].append(entry["date"])
        for month, dates in sorted(months.items()):
            sections.append(f"- **{month}**: {len(dates)} days recorded\n")

    # Write consolidated memory
    memory_content = "\n".join(sections)
    memory_file.write_text(memory_content, encoding="utf-8")
    logger.info(f"Consolidated {len(entries)} daily memories into {memory_file}")


def promote(data_dir: Path):
    """
    Promote learnings with Recurrence-Count >= 3 to permanent rules.

    Reads .learnings/LEARNINGS.md and .learnings/ERRORS.md,
    finds entries with Recurrence-Count >= 3 and status=active,
    then marks them as promoted.
    """
    learnings_dir = data_dir / ".learnings"

    if not learnings_dir.exists():
        logger.info("No .learnings directory found, skipping.")
        return

    promotions_file = learnings_dir / "PROMOTIONS.md"
    promoted_count = 0

    for filename in ["LEARNINGS.md", "ERRORS.md"]:
        filepath = learnings_dir / filename
        if not filepath.exists():
            continue

        content = filepath.read_text(encoding="utf-8")
        file_promoted = 0

        # Find entries with Recurrence-Count >= 3 and status: active
        pattern = r"(### (?:LRN|ERR)-\d{4}-\d{2}-\d{2}-\d+\n.*?(?=### (?:LRN|ERR)-|\Z))"
        entries = re.findall(pattern, content, re.DOTALL)

        for entry in entries:
            # Check recurrence count
            rc_match = re.search(r"\*\*Recurrence-Count\*\*:\s*(\d+)", entry)
            status_match = re.search(r"\*\*Status\*\*:\s*(\w+)", entry)

            if not rc_match or not status_match:
                continue

            count = int(rc_match.group(1))
            status = status_match.group(1)

            if count >= 3 and status == "active":
                # Extract key info
                pk_match = re.search(r"\*\*Pattern-Key\*\*:\s*(.+)", entry)
                learning_match = re.search(
                    r"\*\*(?:Learning|Prevention)\*\*:\s*(.+)", entry
                )

                if pk_match and learning_match:
                    pattern_key = pk_match.group(1).strip()
                    learning = learning_match.group(1).strip()

                    # Write to promotions file
                    promo_entry = (
                        f"\n### Promoted: {pattern_key}\n"
                        f"- **Date**: {datetime.now().isoformat()}\n"
                        f"- **Source**: {filename}\n"
                        f"- **Recurrence-Count**: {count}\n"
                        f"- **Rule**: {learning}\n"
                    )

                    with open(promotions_file, "a", encoding="utf-8") as f:
                        f.write(promo_entry)

                    # Mark as promoted in source file
                    new_entry = entry.replace(
                        f"**Status**: active",
                        f"**Status**: promoted",
                    )
                    content = content.replace(entry, new_entry)
                    file_promoted += 1

                    logger.info(f"Promoted: {pattern_key} (count={count})")

        # Write back modified content only if this file had promotions
        if file_promoted > 0:
            filepath.write_text(content, encoding="utf-8")
        promoted_count += file_promoted

    logger.info(f"Promotion complete: {promoted_count} entries promoted")


def archive_mailbox(data_dir: Path, archive_after_days: int = 30):
    """
    Archive processed mailbox messages.

    - Moves status=done messages from inbox root to inbox/archive/
    - Deletes archived messages older than archive_after_days
    """
    mailbox_dir = data_dir / "mailbox"
    if not mailbox_dir.exists():
        return

    archived = 0
    deleted = 0
    today = datetime.now().date()

    # Process each agent's inbox
    for inbox in mailbox_dir.iterdir():
        if not inbox.is_dir() or not inbox.name.startswith("to-"):
            continue

        archive_dir = inbox / "archive"

        # Step 1: Move status=done messages to archive
        for msg_file in inbox.glob("*.md"):
            if msg_file.name == "PROTOCOL.md":
                continue

            try:
                content = msg_file.read_text(encoding="utf-8")
                if "status: done" in content:
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    msg_file.rename(archive_dir / msg_file.name)
                    archived += 1
            except Exception as e:
                logger.warning(f"Failed to archive {msg_file}: {e}")

        # Step 2: Delete old archived messages
        if archive_dir.exists():
            for old_file in archive_dir.glob("*.md"):
                try:
                    # Extract date from filename: YYYYMMDD_HHMMSS_agent.md
                    date_str = old_file.stem[:8]  # "20260305"
                    file_date = datetime.strptime(date_str, "%Y%m%d").date()
                    age = (today - file_date).days

                    if age > archive_after_days:
                        old_file.unlink()
                        deleted += 1
                except (ValueError, IndexError):
                    continue

    if archived or deleted:
        logger.info(
            f"Mailbox cleanup: {archived} messages archived, "
            f"{deleted} old archives deleted"
        )


def cleanup(data_dir: Path, archive_after_days: int = 90):
    """
    Archive old daily memories and clean up mailbox.
    Moves files older than archive_after_days to an archive directory.
    """
    daily_dir = data_dir / "daily-memories"
    archive_dir = data_dir / "daily-memories" / "archive"

    if not daily_dir.exists():
        return

    today = datetime.now().date()
    archived = 0

    for f in daily_dir.glob("*.md"):
        try:
            file_date = datetime.strptime(f.stem, "%Y-%m-%d").date()
            age = (today - file_date).days

            if age > archive_after_days:
                archive_dir.mkdir(parents=True, exist_ok=True)
                month_dir = archive_dir / f.stem[:7]  # Group by month
                month_dir.mkdir(exist_ok=True)
                f.rename(month_dir / f.name)
                archived += 1
        except ValueError:
            continue

    if archived:
        logger.info(f"Archived {archived} old daily memory files")

    # Also clean up mailbox
    archive_mailbox(data_dir)


def _extract_section(content: str, section_name: str) -> str:
    """Extract a ## section from markdown content."""
    pattern = rf"##\s*{re.escape(section_name)}\s*\n(.*?)(?=\n##\s|\Z)"
    match = re.search(pattern, content, re.DOTALL)
    return match.group(1).strip() if match else ""


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    data_dir = get_data_dir()
    cmd = sys.argv[1].lower()

    if cmd == "consolidate":
        consolidate(data_dir)
    elif cmd == "promote":
        promote(data_dir)
    elif cmd == "cleanup":
        cleanup(data_dir)
    elif cmd == "all":
        consolidate(data_dir)
        promote(data_dir)
        cleanup(data_dir)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
