# Installing Peliqan Skills

The [README](README.md#installation) covers the usual route: the `peliqan` plugin from this repo's marketplace. This page covers everything else.

Whatever the setup, install every skill and connect the Peliqan MCP server. Audit and support read the rules inside the build skills, and every skill talks to your account through the MCP.

## Plugin (recommended)

**Claude app:** Settings → Plugins → **Add marketplace** → `https://github.com/Peliqan-io/skills`, then install **peliqan**.

**Claude Code:** send these one at a time:

```
/plugin marketplace add Peliqan-io/skills
/plugin install peliqan@peliqan
```

The plugin bundles every skill and the Peliqan MCP server. Its commands carry the plugin name: `/peliqan:peliqan-sync`, `/peliqan:peliqan-dashboard`, `/peliqan:peliqan-audit`, `/peliqan:peliqan-support`, `/peliqan:peliqan-connection-health` and `/peliqan:peliqan-help`.

## Claude Code without the plugin

```bash
git clone https://github.com/Peliqan-io/skills.git peliqan-skills
mkdir -p ~/.claude/skills
cp -R peliqan-skills/skills/* ~/.claude/skills/
claude mcp add --transport http peliqan https://mcp.eu.peliqan.io/mcp
```

The commands are then `/peliqan-sync`, `/peliqan-dashboard` and so on, without the plugin name. To update, pull the repo and copy the skills again.

## Claude app without the plugin

1. Zip each folder under `skills/` separately. Each zip must contain its skill folder, not just the files inside it.
2. Upload all the zips under **Settings → Capabilities → Skills**.
3. Add the Peliqan MCP server as a custom connector: `https://mcp.eu.peliqan.io/mcp`.

To update, upload the new zips.

## Check that it works

1. Ask *"which Peliqan skills are there?"* (or run `/peliqan:peliqan-help`). The AI should list every skill.
2. Ask *"list my Peliqan connections"*. The first time, the AI asks you to sign in with your own Peliqan account; after that you see your connections. If it can't reach the MCP server, the skills say so and stop instead of guessing.
