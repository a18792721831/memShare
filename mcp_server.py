#!/usr/bin/env python3
"""
memShare MCP Server

Provides memory read/write tools via MCP (Model Context Protocol).
Compatible with Claude Desktop, and any MCP-supporting AI tool.

Usage:
    python mcp_server.py                    # Start MCP server (stdio)
    MEMSHARE_DATA_DIR=~/data python mcp_server.py

Environment:
    MEMSHARE_DATA_DIR    Data directory (default: ~/memshare-data)
    AGENT_NAME           Agent identity name (default: mcp-agent)
"""

import os
import re
import sys
import json
import logging
from pathlib import Path
from datetime import datetime, date

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("memshare.mcp")

# Load env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATA_DIR = Path(os.path.expanduser(os.environ.get("MEMSHARE_DATA_DIR", "~/memshare-data")))
AGENT_NAME = os.environ.get("AGENT_NAME", "mcp-agent")


def read_memory(file_path: str = "MEMORY.md") -> str:
    """Read a memory file. Supports: MEMORY.md, SOUL.md, USER.md, IDENTITY.md, or any relative path."""
    target = DATA_DIR / file_path
    if not target.exists():
        return f"File not found: {file_path}"
    if not str(target.resolve()).startswith(str(DATA_DIR.resolve())):
        return "Error: Access denied (path traversal)"
    return target.read_text(encoding="utf-8")


def write_daily_memory(title: str, project: str, task: str,
                       completed: list, remaining: list = None) -> str:
    """Write a session record to today's daily memory file."""
    today = date.today().isoformat()
    daily_dir = DATA_DIR / "daily-memories"
    daily_dir.mkdir(parents=True, exist_ok=True)
    daily_file = daily_dir / f"{today}.md"

    # Determine session number
    session_num = 1
    if daily_file.exists():
        content = daily_file.read_text(encoding="utf-8")
        sessions = re.findall(r"### Session (\d+)", content)
        if sessions:
            session_num = max(int(s) for s in sessions) + 1
    else:
        content = f"# {today}\n"

    # Build session entry
    entry = f"\n### Session {session_num}: {title}\n"
    entry += f"**Agent**: {AGENT_NAME}\n"
    entry += f"**Project**: {project}\n"
    entry += f"**Task**: {task}\n\n"
    entry += "**Completed**:\n"
    for i, item in enumerate(completed, 1):
        entry += f"{i}. {item}\n"
    if remaining:
        entry += "\n**Remaining**:\n"
        for i, item in enumerate(remaining, 1):
            entry += f"{i}. {item}\n"
    entry += "\n---\n"

    # Append or create
    if daily_file.exists():
        # Insert before "## 今日要点" or append at end
        if "## 今日要点" in content or "## Key Points" in content:
            marker = "## 今日要点" if "## 今日要点" in content else "## Key Points"
            content = content.replace(marker, entry + "\n" + marker)
        else:
            content += entry
    else:
        content += entry

    daily_file.write_text(content, encoding="utf-8")
    return f"Session {session_num} recorded in {today}.md"


def read_learnings(status: str = "active") -> str:
    """Read learning/error records filtered by status."""
    result = []
    learnings_dir = DATA_DIR / ".learnings"

    for filename in ["ERRORS.md", "LEARNINGS.md"]:
        filepath = learnings_dir / filename
        if not filepath.exists():
            continue

        content = filepath.read_text(encoding="utf-8")
        # Filter by status
        entries = re.findall(
            r"(### (?:LRN|ERR)-\d{4}-\d{2}-\d{2}-\d+\n.*?(?=### (?:LRN|ERR)-|\Z))",
            content, re.DOTALL
        )
        for entry in entries:
            if status == "all" or f"**Status**: {status}" in entry:
                result.append(f"[{filename}]\n{entry.strip()}")

    return "\n\n".join(result) if result else f"No {status} learnings found."


def write_learning(pattern_key: str, category: str, area: str,
                   context: str, learning: str, before: str = "",
                   after: str = "") -> str:
    """Write a new learning or increment recurrence count if exists."""
    learnings_dir = DATA_DIR / ".learnings"
    learnings_dir.mkdir(parents=True, exist_ok=True)

    if category in ("correction", "knowledge_gap", "best_practice"):
        filepath = learnings_dir / "LEARNINGS.md"
        prefix = "LRN"
    else:
        filepath = learnings_dir / "ERRORS.md"
        prefix = "ERR"

    content = ""
    if filepath.exists():
        content = filepath.read_text(encoding="utf-8")

    # Check for duplicate
    if f"**Pattern-Key**: {pattern_key}" in content:
        # Increment recurrence count
        pattern = (
            rf"(\*\*Pattern-Key\*\*: {re.escape(pattern_key)}.*?"
            rf"\*\*Recurrence-Count\*\*: )(\d+)"
        )
        match = re.search(pattern, content, re.DOTALL)
        if match:
            old_count = int(match.group(2))
            new_count = old_count + 1
            content = content[:match.start(2)] + str(new_count) + content[match.end(2):]
            filepath.write_text(content, encoding="utf-8")
            return f"Updated {pattern_key}: Recurrence-Count {old_count} → {new_count}"

    # Create new entry
    today = date.today().isoformat()
    # Count existing entries for numbering
    existing = re.findall(rf"{prefix}-{today}-(\d+)", content)
    num = max((int(n) for n in existing), default=0) + 1

    entry = f"\n### {prefix}-{today}-{num:03d}\n"
    entry += f"- **Pattern-Key**: {pattern_key}\n"
    if category:
        entry += f"- **Category**: {category}\n"
    entry += f"- **Recurrence-Count**: 1\n"
    entry += f"- **Priority**: P2\n"
    entry += f"- **Area**: {area}\n"
    entry += f"- **Context**: {context}\n"
    entry += f"- **Learning**: {learning}\n"
    if before:
        entry += f"- **Before**: {before}\n"
    if after:
        entry += f"- **After**: {after}\n"
    entry += f"- **Status**: active\n"

    # Insert before marker
    marker = "<!-- 新记录追加在此处 -->"
    if marker in content:
        content = content.replace(marker, entry + "\n" + marker)
    else:
        content += entry

    filepath.write_text(content, encoding="utf-8")
    return f"Created {prefix}-{today}-{num:03d}: {pattern_key}"


def check_mailbox() -> str:
    """Check for unread messages in the agent's mailbox."""
    mailbox_dir = DATA_DIR / "mailbox" / f"to-{AGENT_NAME}"
    if not mailbox_dir.exists():
        return "No mailbox found."

    unread = []
    for f in sorted(mailbox_dir.glob("*.md")):
        content = f.read_text(encoding="utf-8")
        if "status: unread" in content.lower():
            # Extract basic info
            lines = content.split("\n")
            info = {"file": f.name}
            for line in lines:
                line = line.strip()
                if line.startswith("from:"):
                    info["from"] = line.split(":", 1)[1].strip()
                elif line.startswith("type:"):
                    info["type"] = line.split(":", 1)[1].strip()
                elif line.startswith("timestamp:"):
                    info["timestamp"] = line.split(":", 1)[1].strip()
            # Get first 100 chars of body
            body_start = content.find("---", content.find("---") + 3)
            if body_start > 0:
                body = content[body_start + 3:].strip()[:100]
                info["preview"] = body
            unread.append(info)

    if not unread:
        return "No unread messages."

    result = f"{len(unread)} unread message(s):\n"
    for msg in unread:
        result += f"\n- From: {msg.get('from', 'unknown')}"
        result += f" | Type: {msg.get('type', 'message')}"
        result += f" | {msg.get('preview', '')}"
    return result


def send_message(to_agent: str, subject: str, content: str,
                 msg_type: str = "message") -> str:
    """Send a message to another agent via mailbox."""
    mailbox_dir = DATA_DIR / "mailbox" / f"to-{to_agent}"
    mailbox_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    filename = f"{now.strftime('%Y%m%d_%H%M%S')}_{AGENT_NAME}.md"
    filepath = mailbox_dir / filename

    msg = f"---\n"
    msg += f"from: {AGENT_NAME}\n"
    msg += f"to: {to_agent}\n"
    msg += f'timestamp: "{now.isoformat()}"\n'
    msg += f"type: {msg_type}\n"
    msg += f"status: unread\n"
    msg += f"---\n\n"
    msg += f"## {subject}\n\n"
    msg += content

    filepath.write_text(msg, encoding="utf-8")
    return f"Message sent to {to_agent}: {filename}"


# ============================================================
# MCP Protocol Implementation (stdio JSON-RPC)
# ============================================================

TOOLS = {
    "read_memory": {
        "description": "Read a memory file (MEMORY.md, SOUL.md, USER.md, IDENTITY.md, or daily-memories/YYYY-MM-DD.md)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative path to memory file (e.g., 'MEMORY.md', 'daily-memories/2026-03-05.md')",
                    "default": "MEMORY.md",
                }
            },
        },
        "handler": lambda args: read_memory(args.get("file_path", "MEMORY.md")),
    },
    "write_daily_memory": {
        "description": "Write a session record to today's daily memory file",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Session title"},
                "project": {"type": "string", "description": "Project name"},
                "task": {"type": "string", "description": "Task description"},
                "completed": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of completed work items",
                },
                "remaining": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of remaining items (optional)",
                },
            },
            "required": ["title", "project", "task", "completed"],
        },
        "handler": lambda args: write_daily_memory(
            args["title"], args["project"], args["task"],
            args["completed"], args.get("remaining"),
        ),
    },
    "read_learnings": {
        "description": "Read learning/error records filtered by status (active, promoted, all)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status: active, promoted, or all",
                    "default": "active",
                }
            },
        },
        "handler": lambda args: read_learnings(args.get("status", "active")),
    },
    "write_learning": {
        "description": "Record a new error or learning pattern",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern_key": {"type": "string", "description": "Unique pattern identifier"},
                "category": {
                    "type": "string",
                    "enum": ["error", "correction", "knowledge_gap", "best_practice"],
                    "description": "Category of the learning",
                },
                "area": {"type": "string", "description": "Area/domain (e.g., git, api, database)"},
                "context": {"type": "string", "description": "What happened"},
                "learning": {"type": "string", "description": "What was learned / how to prevent"},
                "before": {"type": "string", "description": "Old/wrong approach (optional)"},
                "after": {"type": "string", "description": "New/correct approach (optional)"},
            },
            "required": ["pattern_key", "category", "area", "context", "learning"],
        },
        "handler": lambda args: write_learning(
            args["pattern_key"], args["category"], args["area"],
            args["context"], args["learning"],
            args.get("before", ""), args.get("after", ""),
        ),
    },
    "check_mailbox": {
        "description": "Check for unread messages in the agent's mailbox",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda args: check_mailbox(),
    },
    "send_message": {
        "description": "Send a message to another agent via the mailbox system",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to_agent": {"type": "string", "description": "Recipient agent name"},
                "subject": {"type": "string", "description": "Message subject"},
                "content": {"type": "string", "description": "Message content"},
                "msg_type": {
                    "type": "string",
                    "enum": ["message", "request", "response", "notification"],
                    "default": "message",
                },
            },
            "required": ["to_agent", "subject", "content"],
        },
        "handler": lambda args: send_message(
            args["to_agent"], args["subject"], args["content"],
            args.get("msg_type", "message"),
        ),
    },
}


def handle_request(request: dict) -> dict:
    """Handle a JSON-RPC request."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "memshare",
                    "version": "1.0.0",
                },
            },
        }

    elif method == "notifications/initialized":
        return None  # No response needed

    elif method == "tools/list":
        tools_list = []
        for name, tool in TOOLS.items():
            tools_list.append({
                "name": name,
                "description": tool["description"],
                "inputSchema": tool["inputSchema"],
            })
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": tools_list},
        }

    elif method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})

        if tool_name not in TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                    "isError": True,
                },
            }

        try:
            result = TOOLS[tool_name]["handler"](tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": result}],
                },
            }
        except Exception as e:
            logger.exception(f"Tool '{tool_name}' failed: {e}")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error: {e}"}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main():
    """Run MCP server on stdio."""
    logger.info(f"memShare MCP server starting (data: {DATA_DIR}, agent: {AGENT_NAME})")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
            response = handle_request(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON: {e}")
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
            sys.stdout.write(json.dumps(error_response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
