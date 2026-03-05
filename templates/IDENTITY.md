# Agent Identity

> This file defines the identity of the AI agent in a multi-agent system.
> Each agent should have its own identity to enable cross-agent communication.
> The agent-id MUST match the entry in `mailbox/agents.json`.

---

## Agent Info

- **Agent-ID**: my-agent _(unique lowercase identifier, used in mailbox and agents.json)_
- **Display Name**: My Agent
- **Type**: _(e.g., coding-assistant, code-reviewer, project-manager, general-assistant)_
- **Platform**: _(e.g., CodeBuddy, Cursor, Windsurf, Claude Desktop, WeChat Bot)_
- **Version**: 1.0

## Capabilities

- Code reading and writing
- File system operations
- Git operations
- Web search
- _(Add your agent's specific capabilities)_

## Communication

- **Mailbox**: mailbox/to-{agent-id}/
- **Registry**: mailbox/agents.json
- **Status**: active

---

_This file is used by the mailbox system for cross-agent communication.
The Agent-ID must be globally unique across all connected agents._
