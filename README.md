# memShare 🧠

**Shared Memory System for AI Agents** | **AI 代理共享记忆系统**

[English](#english) | [中文](#中文)

---

<a name="english"></a>

## What is memShare?

memShare is an open-source shared memory system that gives AI coding assistants **persistent, cross-session memory**. It works with any AI tool that supports file reading/writing or MCP protocol.

### The Problem

AI coding assistants forget everything between sessions. Every new conversation starts from zero — no context about your projects, preferences, past mistakes, or ongoing work.

### The Solution

memShare provides a structured memory layer that any AI agent can read and write:

- **Daily Memories** — Automatic session journals that track what was done
- **Long-term Memory** — Consolidated summaries for quick context loading
- **Self-Improvement** — Error and learning tracking that prevents repeated mistakes
- **Cross-Agent Messaging** — Mailbox system for multi-agent collaboration
- **Cloud Sync** — Share memories across devices via COS, S3, or any storage backend

### Architecture

```
┌─────────────────────────────────────────────┐
│              Your AI Agents                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐    │
│  │ CodeBuddy│ │  Cursor  │ │  Claude  │    │
│  │  Agent   │ │  Agent   │ │ Desktop  │    │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘    │
│       │             │            │           │
│  ┌────▼─────────────▼────────────▼─────┐    │
│  │         memShare Data Layer          │    │
│  │  ┌──────────┐ ┌──────────────────┐  │    │
│  │  │ Memories │ │    Learnings     │  │    │
│  │  │ MEMORY   │ │  ERRORS.md       │  │    │
│  │  │ daily/   │ │  LEARNINGS.md    │  │    │
│  │  │ USER     │ │  PROMOTIONS.md   │  │    │
│  │  │ SOUL     │ │                  │  │    │
│  │  └──────────┘ └──────────────────┘  │    │
│  │  ┌──────────┐ ┌──────────────────┐  │    │
│  │  │ Mailbox  │ │  Storage Backend │  │    │
│  │  │ to-xxx/  │ │  Local/COS/S3   │  │    │
│  │  └──────────┘ └──────────────────┘  │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

## Quick Start

### 1. Clone & Setup

```bash
git clone https://github.com/a18792721831/memShare.git
cd memShare
pip install -r requirements.txt
python setup.py
```

The interactive setup wizard will guide you through:
- Choosing a data directory
- Selecting a storage backend (local / COS / S3)
- Naming your agent
- Connecting to your AI tool

### 2. Connect Your AI Tool

Choose your AI tool and follow the adapter guide:

| AI Tool | Adapter | Integration Method |
|---------|---------|-------------------|
| CodeBuddy | [adapters/codebuddy.md](adapters/codebuddy.md) | Project rules file |
| Cursor | [adapters/cursor.md](adapters/cursor.md) | Project rules file |
| Windsurf | [adapters/windsurf.md](adapters/windsurf.md) | Project rules file |
| Claude Desktop | [adapters/claude-desktop.md](adapters/claude-desktop.md) | MCP server |
| Other | [adapters/generic.md](adapters/generic.md) | Multiple options |

### 3. Start Using

Once connected, your AI agent will automatically:
1. Load memories at session start
2. Record work in daily memories
3. Track errors and learnings
4. Avoid previously-made mistakes

## Memory Layers

| Layer | File | Purpose | Update Frequency |
|-------|------|---------|-----------------|
| Long-term | `MEMORY.md` | Consolidated summaries | Daily (auto) |
| Daily | `daily-memories/` | Session-by-session records | Every session |
| Learnings | `.learnings/` | Error patterns & lessons | On occurrence |
| User Profile | `USER.md` | Preferences & habits | Low frequency |
| Guidelines | `SOUL.md` | Behavioral rules | Rarely |
| Identity | `IDENTITY.md` | Agent identification | Once |

## Self-Improvement System

memShare tracks errors and learnings automatically:

1. **Detect** — Agent encounters an error or learns something new
2. **Record** — Written to `.learnings/ERRORS.md` or `LEARNINGS.md`
3. **Deduplicate** — Same pattern → increment counter
4. **Promote** — Counter ≥ 3 → promote to permanent rule
5. **Apply** — Agent checks learnings at session start, avoids known patterns

## Cross-Agent Messaging

Multiple AI agents can communicate asynchronously via the mailbox:

```
mailbox/
├── to-codebuddy/     # CodeBuddy's inbox
│   └── 20260305_143000_claude.md
└── to-claude/        # Claude's inbox
    └── 20260305_150000_codebuddy.md
```

See [templates/mailbox/PROTOCOL.md](templates/mailbox/PROTOCOL.md) for the messaging protocol.

## Cloud Sync

Share memories across devices using any supported storage backend:

```bash
# Push local → cloud
python scripts/sync.py push

# Pull cloud → local
python scripts/sync.py pull

# Check status
python scripts/sync.py status
```

### Supported Backends

| Backend | Provider | Install |
|---------|----------|---------|
| Local | File copy | Built-in |
| COS | Tencent Cloud | `pip install cos-python-sdk-v5` |
| S3 | AWS / S3-compatible | `pip install boto3` |

### Automatic Sync (crontab)

```bash
# Pull every minute, push every 5 minutes
* * * * * python3 /path/to/scripts/sync.py pull
*/5 * * * * python3 /path/to/scripts/sync.py push

# Consolidate memories nightly
0 23 * * * python3 /path/to/scripts/memory_consolidator.py all
```

## MCP Server

For AI tools that support [MCP (Model Context Protocol)](https://modelcontextprotocol.io/), memShare provides a built-in MCP server:

```bash
python mcp_server.py
```

Available tools:
- `read_memory` — Read any memory file
- `write_daily_memory` — Record a session
- `read_learnings` — Check error/learning records
- `write_learning` — Record new error or learning
- `check_mailbox` — Check for messages
- `send_message` — Send to another agent

## Project Structure

```
memShare/
├── setup.py                 # Interactive setup wizard
├── mcp_server.py            # MCP server for Claude Desktop etc.
├── requirements.txt         # Python dependencies
├── scripts/
│   ├── storage_backend.py   # Storage abstraction (Local/COS/S3)
│   ├── sync.py              # Sync tool (push/pull)
│   └── memory_consolidator.py # Daily → long-term consolidation
├── templates/               # Template files (copied during setup)
│   ├── MEMORY.md
│   ├── SOUL.md
│   ├── USER.md
│   ├── IDENTITY.md
│   ├── daily-memories/
│   ├── .learnings/
│   └── mailbox/
├── adapters/                # AI tool integration guides
│   ├── codebuddy.md
│   ├── cursor.md
│   ├── windsurf.md
│   ├── claude-desktop.md
│   └── generic.md
└── examples/                # Example configurations
```

## Contributing

Contributions are welcome! Here are some ideas:

- **New adapters** — Add support for more AI tools (GitHub Copilot, Gemini, etc.)
- **New storage backends** — Azure Blob, Google Cloud Storage, etc.
- **Better consolidation** — Smarter summarization algorithms
- **Web UI** — Dashboard for viewing/managing memories
- **Tests** — Unit and integration tests

## License

MIT License — see [LICENSE](LICENSE) for details.

---

<a name="中文"></a>

## memShare 是什么？

memShare 是一个开源的 AI 代理共享记忆系统，让 AI 编程助手拥有**持久化的跨会话记忆**。它适用于任何支持文件读写或 MCP 协议的 AI 工具。

### 痛点

AI 编程助手在每次会话之间会忘记所有内容。每次新对话都从零开始 —— 没有项目上下文、用户偏好、历史错误或进行中工作的记忆。

### 解决方案

memShare 提供了一个结构化的记忆层，任何 AI 代理都可以读写：

- **每日记忆** — 自动记录每次会话的工作内容
- **长期记忆** — 整合摘要，快速加载上下文
- **自我改进** — 错误和经验追踪，防止重复犯错
- **跨代理通信** — 信箱系统，支持多 AI 协作
- **云同步** — 通过 COS、S3 等存储后端跨设备共享

## 快速开始

```bash
git clone https://github.com/a18792721831/memShare.git
cd memShare
pip install -r requirements.txt
python setup.py        # 交互式安装向导
```

安装向导会引导你完成：
- 选择数据存储目录
- 选择存储后端（本地 / 腾讯云 COS / AWS S3）
- 设置代理名称
- 连接你的 AI 工具

## 支持的 AI 工具

| AI 工具 | 集成方式 | 适配文档 |
|---------|---------|---------|
| CodeBuddy（腾讯） | 项目规则文件 | [adapters/codebuddy.md](adapters/codebuddy.md) |
| Cursor | 项目规则文件 | [adapters/cursor.md](adapters/cursor.md) |
| Windsurf | 项目规则文件 | [adapters/windsurf.md](adapters/windsurf.md) |
| Claude Desktop | MCP 服务器 | [adapters/claude-desktop.md](adapters/claude-desktop.md) |
| 其他工具 | 多种方式 | [adapters/generic.md](adapters/generic.md) |

## 核心特性

### 记忆分层

| 层级 | 文件 | 用途 | 更新频率 |
|------|------|------|---------|
| 长期记忆 | `MEMORY.md` | 整合摘要 | 每日自动 |
| 每日记忆 | `daily-memories/` | 逐会话记录 | 每次会话 |
| 经验教训 | `.learnings/` | 错误模式和经验 | 发生时 |
| 用户画像 | `USER.md` | 偏好和习惯 | 低频 |
| 行为准则 | `SOUL.md` | 行为规则 | 极低频 |

### 自我改进

1. **检测** — 代理遇到错误或学到新知识
2. **记录** — 写入 `.learnings/ERRORS.md` 或 `LEARNINGS.md`
3. **去重** — 相同模式 → 递增计数器
4. **晋升** — 计数 ≥ 3 → 晋升为永久规则
5. **应用** — 代理在会话开始时检查经验，避免已知错误

### 跨代理通信

多个 AI 代理可以通过信箱系统异步通信。详见 [templates/mailbox/PROTOCOL.md](templates/mailbox/PROTOCOL.md)。

## 许可证

MIT License
