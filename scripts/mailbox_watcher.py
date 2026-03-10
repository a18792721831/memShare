#!/usr/bin/env python3
"""
信箱 Watcher — 精确渠道路由

功能：
- 监控 mailbox/to-{agent}/ 目录中的新消息
- 解析消息 frontmatter 中的 channel 字段（或从 to 字段解析）
- 根据渠道标识将消息转发到对应的通信渠道（企微/飞书等）
- 支持 agents.json 中注册的 channels 配置

渠道路由规则：
- to: openclaw       → 使用默认渠道（qiwei）
- to: openclaw-qiwei → 精确路由到企微
- to: openclaw-feishu → 精确路由到飞书

用法：
  python mailbox_watcher.py --agent openclaw           # 监控 openclaw 收件箱
  python mailbox_watcher.py --agent openclaw --once     # 只检查一次
  python mailbox_watcher.py --agent openclaw --dry-run  # 仅打印不转发
"""

import os
import re
import sys
import json
import time
import logging
from pathlib import Path
from datetime import datetime

# ============== 配置 ==============
MEMORY_BASE = "/Users/yongqijia/Library/Application Support/CodeBuddyExtension/Data/Public"
MAILBOX_DIR = os.path.join(MEMORY_BASE, "mailbox")
AGENTS_FILE = os.path.join(MAILBOX_DIR, "agents.json")
STATE_FILE = os.path.join(MEMORY_BASE, ".watcher_state.json")

POLL_INTERVAL = 30  # 秒

# ============== 日志 ==============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("mailbox_watcher")


# ============== 工具函数 ==============

def load_agents():
    """加载 agents.json 注册表"""
    if not os.path.exists(AGENTS_FILE):
        logger.error(f"agents.json 不存在: {AGENTS_FILE}")
        return {}
    with open(AGENTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("agents", {})


def parse_frontmatter(content: str) -> dict:
    """解析消息文件的 YAML frontmatter

    返回 frontmatter 字典，包含 from, to, channel, type, status 等字段
    """
    fm = {}
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return fm

    for line in match.group(1).split("\n"):
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            fm[key] = value

    return fm


def resolve_channel(to_field: str, explicit_channel: str = None,
                    agents: dict = None) -> tuple:
    """解析目标 agent-id 和渠道

    参数：
        to_field: frontmatter 中的 to 字段（如 "openclaw" 或 "openclaw-qiwei"）
        explicit_channel: frontmatter 中显式指定的 channel 字段（优先级最高）
        agents: agents.json 中的 agents 字典

    返回：
        (agent_id, channel_id, channel_info)
        - agent_id: 目标 Agent 标识
        - channel_id: 渠道标识（如 "qiwei"），None 表示无渠道路由
        - channel_info: 渠道配置字典，None 表示无渠道配置
    """
    agents = agents or {}

    # Step 1: 尝试从 to 字段解析 agent-id 和 channel
    agent_id = to_field
    parsed_channel = None

    # 检查 to 字段是否包含渠道标识（格式: agent-id-channel）
    # 需要先检查完整的 to 字段是否是一个已注册的 agent-id
    if to_field in agents:
        # 完整匹配已注册 agent，没有渠道后缀
        agent_id = to_field
    else:
        # 尝试分割：从右向左查找已注册的 agent-id 前缀
        # 例如 "openclaw-qiwei" → agent_id="openclaw", channel="qiwei"
        # 例如 "codebuddy-plugin-feishu" → agent_id="codebuddy-plugin", channel="feishu"
        parts = to_field.rsplit("-", 1)
        if len(parts) == 2 and parts[0] in agents:
            agent_id = parts[0]
            parsed_channel = parts[1]
        else:
            # 尝试更长的前缀（处理 agent-id 自身包含 - 的情况）
            # 逐步从右到左截断
            for i in range(len(to_field) - 1, 0, -1):
                if to_field[i] == "-":
                    prefix = to_field[:i]
                    suffix = to_field[i + 1:]
                    if prefix in agents:
                        agent_id = prefix
                        parsed_channel = suffix
                        break

    # Step 2: 确定最终渠道（显式 channel 字段优先）
    channel_id = explicit_channel or parsed_channel

    # Step 3: 查找渠道配置
    channel_info = None
    agent_config = agents.get(agent_id, {})
    channels = agent_config.get("channels", {})

    if channel_id and channel_id in channels:
        channel_info = channels[channel_id]
    elif not channel_id and channels:
        # 没有指定渠道，使用默认渠道
        for cid, cinfo in channels.items():
            if cinfo.get("default", False):
                channel_id = cid
                channel_info = cinfo
                break
        # 如果没有标记 default，取第一个
        if not channel_id:
            channel_id = next(iter(channels))
            channel_info = channels[channel_id]

    return agent_id, channel_id, channel_info


def load_watcher_state() -> dict:
    """加载 watcher 状态（已处理的消息）"""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"processed": {}, "last_check": None}


def save_watcher_state(state: dict):
    """保存 watcher 状态"""
    state["last_check"] = datetime.now().isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def scan_inbox(agent_id: str) -> list:
    """扫描 Agent 收件箱中的消息文件（不含 archive/）

    返回 (文件路径, frontmatter, 正文) 的列表
    """
    inbox_dir = os.path.join(MAILBOX_DIR, f"to-{agent_id}")
    if not os.path.isdir(inbox_dir):
        logger.warning(f"收件箱目录不存在: {inbox_dir}")
        return []

    messages = []
    for fname in sorted(os.listdir(inbox_dir)):
        fpath = os.path.join(inbox_dir, fname)
        if not os.path.isfile(fpath) or not fname.endswith(".md"):
            continue

        try:
            content = Path(fpath).read_text(encoding="utf-8")
            fm = parse_frontmatter(content)

            # 提取正文（去掉 frontmatter）
            body = content
            match = re.match(r"^---\s*\n.*?\n---\s*\n", content, re.DOTALL)
            if match:
                body = content[match.end():]

            messages.append({
                "path": fpath,
                "filename": fname,
                "frontmatter": fm,
                "body": body.strip(),
            })
        except Exception as e:
            logger.error(f"读取消息失败: {fpath} - {e}")

    return messages


def dispatch_to_channel(agent_id: str, channel_id: str, channel_info: dict,
                        message: dict, dry_run: bool = False) -> bool:
    """将消息转发到指定渠道

    当前为框架实现，实际转发逻辑需要对接各渠道 API。

    返回: True 成功, False 失败
    """
    channel_type = channel_info.get("type", "unknown") if channel_info else "unknown"
    channel_name = channel_info.get("name", channel_id) if channel_info else channel_id

    fm = message["frontmatter"]
    sender = fm.get("from", "unknown")
    msg_type = fm.get("type", "info")
    body_preview = message["body"][:200] if message["body"] else "(空消息)"

    if dry_run:
        logger.info(
            f"[DRY-RUN] 转发消息到 [{channel_name}]({channel_type}):\n"
            f"  文件: {message['filename']}\n"
            f"  发送方: {sender}\n"
            f"  类型: {msg_type}\n"
            f"  预览: {body_preview}"
        )
        return True

    # TODO: 实际渠道转发逻辑
    # if channel_type == "wechat-work-bot":
    #     return send_via_qiwei(message)
    # elif channel_type == "feishu-bot":
    #     return send_via_feishu(message)

    logger.info(
        f"转发消息到 [{channel_name}]({channel_type}): "
        f"{message['filename']} (from: {sender}, type: {msg_type})"
    )
    return True


def process_messages(agent_id: str, once: bool = False, dry_run: bool = False):
    """处理 Agent 收件箱中的消息

    参数：
        agent_id: 目标 Agent 标识
        once: 只检查一次（不循环）
        dry_run: 仅打印不转发
    """
    agents = load_agents()
    if agent_id not in agents:
        logger.error(f"Agent '{agent_id}' 未在 agents.json 中注册")
        return

    agent_config = agents[agent_id]
    channels = agent_config.get("channels", {})
    logger.info(
        f"启动 Watcher: agent={agent_id}, "
        f"channels={list(channels.keys()) if channels else '无'}, "
        f"once={once}, dry_run={dry_run}"
    )

    while True:
        state = load_watcher_state()
        messages = scan_inbox(agent_id)

        new_count = 0
        for msg in messages:
            fname = msg["filename"]

            # 跳过已处理的消息
            if fname in state.get("processed", {}):
                continue

            fm = msg["frontmatter"]
            status = fm.get("status", "")

            # 只处理 unread 消息
            if status != "unread":
                continue

            # 解析渠道
            to_field = fm.get("to", agent_id)
            explicit_channel = fm.get("channel")
            _, channel_id, channel_info = resolve_channel(
                to_field, explicit_channel, agents
            )

            logger.info(
                f"新消息: {fname} → "
                f"agent={agent_id}, channel={channel_id or 'default'}"
            )

            # 转发到渠道
            success = dispatch_to_channel(
                agent_id, channel_id, channel_info, msg, dry_run
            )

            if success:
                state.setdefault("processed", {})[fname] = {
                    "channel": channel_id,
                    "processed_at": datetime.now().isoformat(),
                    "from": fm.get("from", ""),
                    "type": fm.get("type", ""),
                }
                new_count += 1

        if new_count > 0:
            save_watcher_state(state)
            logger.info(f"本轮处理 {new_count} 条新消息")
        else:
            save_watcher_state(state)  # 更新 last_check

        if once:
            break

        time.sleep(POLL_INTERVAL)


# ============== 命令行入口 ==============

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="信箱 Watcher — 精确渠道路由",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python mailbox_watcher.py --agent openclaw           # 监控 openclaw 收件箱（循环）
  python mailbox_watcher.py --agent openclaw --once     # 只检查一次
  python mailbox_watcher.py --agent openclaw --dry-run  # 仅打印不转发

渠道路由:
  to: openclaw        → 默认渠道（qiwei）
  to: openclaw-qiwei  → 企微
  to: openclaw-feishu → 飞书
""",
    )
    parser.add_argument(
        "--agent", required=True,
        help="目标 Agent ID（如 openclaw）",
    )
    parser.add_argument("--once", action="store_true", help="只检查一次")
    parser.add_argument("--dry-run", action="store_true", help="仅打印不实际转发")

    args = parser.parse_args()
    process_messages(args.agent, once=args.once, dry_run=args.dry_run)
