# memShare Adapter: CodeBuddy (Tencent)

> Copy the content below into your CodeBuddy project's `.codebuddy/rules/` as a `.mdc` file.
> This enables CodeBuddy to use the memShare memory system.

---

## Setup

1. Create `.codebuddy/rules/memshare.mdc` in your project root
2. Paste the rule content below
3. Update `MEMSHARE_DATA_DIR` to your actual data directory path

## Rule Content

```yaml
---
description: memShare - Shared Memory System for AI Agents
alwaysApply: true
enabled: true
---
```

````markdown
# memShare Memory System

Memory base path: `{MEMSHARE_DATA_DIR}`

## Memory Layers

| Layer | File | Load Level | Update Frequency |
|-------|------|------------|------------------|
| Long-term | MEMORY.md | L0 (must read) | Daily |
| Daily | daily-memories/ | L0 (must read) | Every session |
| Learnings | .learnings/ | L0 (must read) | Every session |
| User Profile | USER.md | L1 (on demand) | Low frequency |
| Guidelines | SOUL.md | L2 (skip if in rules) | Very low |

## Session Startup — Parallel Load

On every new session, load memories in parallel:

1. Read `MEMORY.md` + today's and yesterday's `daily-memories/` → 150-word summary
2. Read `USER.md` → 50-word preference summary
3. Read `.learnings/ERRORS.md` + `.learnings/LEARNINGS.md` → active items summary
4. Check `mailbox/to-{agent-name}/` for unread messages

**Rules:**
- Internalize summaries as background knowledge, do NOT output to user
- If inbox has unread messages, report to user

## Memory Writing

After completing meaningful work, write to `daily-memories/{YYYY-MM-DD}.md`:

```markdown
### Session N: {Title}
**Agent**: {agent-name}
**Project**: {project-name}
**Task**: {brief description}

**Completed**:
1. ...

**Remaining**: (if any)
1. ...
```

## Learnings System

On error or correction, write to `.learnings/ERRORS.md` or `.learnings/LEARNINGS.md`:

- Check for duplicate Pattern-Key before writing
- If duplicate → increment Recurrence-Count
- If new → create new record
- When Recurrence-Count ≥ 3 → promote to permanent rule
````

---

## Data Directory

By default, memShare data is stored at `~/memshare-data`. Update the path in the rule above if you used a different location during setup.
