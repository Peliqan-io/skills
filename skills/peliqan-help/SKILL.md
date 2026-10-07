---
name: peliqan-help
description: "Shows which Peliqan skills exist, what each one does and whether it writes to your Peliqan account. Use when someone asks what the Peliqan skills can do, which one to use, or how to call them: 'peliqan help', 'what peliqan skills are there', 'how do I use the peliqan skills', '/peliqan-help'."
---

# Peliqan Help

Show the overview below as-is. It needs no tool calls and no account access.

## Skills

| Skill | Call it | What it does | Writes to your account? |
|---|---|---|---|
| **peliqan-sync** | `/peliqan-sync` | **Build.** Sets up a sync worker for a system pair, or adds a sync (orders, stock, customers…) to an existing one. Tests, deploys and verifies it. | Yes, after you confirm |
| **peliqan-dashboard** | `/peliqan-dashboard` | **Build.** Builds a dashboard on your warehouse: rebuilding a report from any BI tool (Power BI, Tableau, Excel…), from scratch, or on existing tables. Sets up the data model it needs and verifies every number before building. | Yes, after you confirm |
| **peliqan-audit** | `/peliqan-audit` | **Audit.** Checks something that looks healthy (sync workers, dashboards) against the framework rules and its run history. Returns a scorecard and a fix list. | No, read-only |
| **peliqan-support** | `/peliqan-support` | **Support.** Something is broken anywhere in your account (a sync, pipeline, data app, endpoint, table): finds the root cause from the logs and data and proposes a fix. | Only after your explicit go-ahead |
| **peliqan-help** | `/peliqan-help` | This card. | No |

Installed as the plugin (the recommended way), the commands carry the plugin name:
`/peliqan:peliqan-sync`, `/peliqan:peliqan-support`, and so on.

You don't have to call a skill by name. Describe what you want and the AI picks
the right one:

| You say | Skill |
|---|---|
| "Build a sync between our webshop and our ERP" | peliqan-sync |
| "Add a stock sync from the ERP to the webshop" | peliqan-sync |
| "Rebuild this Power BI report as a dashboard" | peliqan-dashboard |
| "Build a sales dashboard on our order tables" | peliqan-dashboard |
| "Set up bronze/silver/gold for our sales data" | peliqan-dashboard |
| "Is our order sync ready to go live?" | peliqan-audit |
| "Run a health check on our syncs" | peliqan-audit |
| "Orders stopped arriving in the ERP since Tuesday" | peliqan-support |
| "Why are there dead-letter rows?" | peliqan-support |
| "The pipeline failed last night" | peliqan-support |
| "The dashboard numbers don't match Power BI anymore" | peliqan-support |

## Typical lifecycle

1. **Build** with the framework's build skill: `peliqan-sync` for syncs,
   `peliqan-dashboard` for dashboards.
2. **Audit** it with `peliqan-audit` before go-live, and again after changes.
3. **Support** with `peliqan-support` when something breaks. The fix goes
   back through the build skill.

## Requirements

- The Peliqan MCP server connected to your AI agent: `https://mcp.eu.peliqan.io/mcp`.
- Install all skills together. Audit and support read the framework rules
  shipped inside the build skills.

Audit and support cover more domains over time; each new one is a reference
file inside them, so the commands stay the same.
