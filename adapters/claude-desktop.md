# memShare Adapter: Claude Desktop

> Integrate memShare with [Claude Desktop](https://claude.ai/desktop) via MCP.

---

## Setup

Claude Desktop uses MCP (Model Context Protocol) servers for tool integration.
memShare can be integrated as an MCP server that provides memory read/write tools.

### Step 1: Install memShare MCP Server

```bash
# Clone memShare
git clone https://github.com/a18792721831/memShare.git
cd memShare

# Install dependencies
pip install -r requirements.txt

# Run setup
python setup.py
```

### Step 2: Configure Claude Desktop

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "memshare": {
      "command": "python",
      "args": ["/path/to/memShare/mcp_server.py"],
      "env": {
        "MEMSHARE_DATA_DIR": "~/memshare-data"
      }
    }
  }
}
```

### Step 3: Use in Claude Desktop

Once configured, Claude Desktop will have access to these tools:
- `read_memory` — Read from any memory file
- `write_daily_memory` — Write a session record
- `read_learnings` — Check error/learning records
- `write_learning` — Record a new error or learning
- `check_mailbox` — Check for unread messages
- `send_message` — Send a message to another agent

## System Prompt Addition

Add this to your Claude Desktop system prompt:

```
You have access to a shared memory system (memShare). At the start of each conversation:
1. Use read_memory to load MEMORY.md and today's daily memories
2. Use read_learnings to check for active error patterns to avoid
3. Use check_mailbox for unread messages
4. After completing work, use write_daily_memory to record what was done
```
