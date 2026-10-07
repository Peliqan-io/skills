---
name: peliqan-help
description: "Quick-reference card for all Peliqan skills and how to call them. One-shot display. Trigger: /peliqan-help, 'peliqan help', 'what peliqan skills are there', 'how do I use the peliqan skills'."
---

# Peliqan Help

Display this reference card when invoked. One-shot: do not call any tools.

## Skills

| Skill | Call it | What it does | Writes to your account? |
|---|---|---|---|
| **peliqan-sync** | `/peliqan-sync` | **Build.** Sets up a sync worker for a system pair, or adds a sync (orders, stock, customers…) to an existing one. Tests, deploys and verifies it. | Yes, after you confirm |
| **peliqan-audit** | `/peliqan-audit` | **Audit.** Checks something that looks healthy (today: sync workers) against the framework rules and its run history. Returns a scorecard and a fix list. | No, read-only |
| **peliqan-support** | `/peliqan-support` | **Support.** Something is broken anywhere in your account (a sync, pipeline, data app, endpoint, table): finds the root cause from the logs and data and proposes a fix. | Only after your explicit go-ahead |
| **peliqan-help** | `/peliqan-help` | This card. | No |

In Claude Code, when installed as a plugin, the skills are namespaced:
`/peliqan:peliqan-sync`, `/peliqan:peliqan-support`, and so on.

You don't have to call a skill by name. Describe what you want and Claude picks
the right one:

| You say | Skill |
|---|---|
| "Build a sync between our webshop and our ERP" | peliqan-sync |
| "Add a stock sync from the ERP to the webshop" | peliqan-sync |
| "Is our order sync ready to go live?" | peliqan-audit |
| "Run a health check on our syncs" | peliqan-audit |
| "Orders stopped arriving in the ERP since Tuesday" | peliqan-support |
| "Why are there dead-letter rows?" | peliqan-support |
| "The pipeline failed last night" | peliqan-support |

## Typical lifecycle

1. **Build** the worker and its syncs with `peliqan-sync`.
2. **Audit** it with `peliqan-audit` before go-live, and again after changes.
3. **Support** with `peliqan-support` when something breaks. The fix goes
   back through `peliqan-sync`.

## Requirements

- The Peliqan MCP server connected to Claude: `https://mcp.eu.peliqan.io/mcp`.
- Install all skills together. Audit and support read the framework rules
  shipped inside `peliqan-sync`.

Audit and support cover more domains over time; each new one is a reference
file inside them, so the commands stay the same.
