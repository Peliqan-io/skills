---
name: peliqan-connection-health
description: "Checks whether every connection in a Peliqan account is running and whether the data it loaded is right: freshness against each connection's own schedule, stuck runs, failed authorisation, leftover or re-created connections, and duplicate, vanished or stacked rows in the warehouse. Works on the account itself or on all of its sub-accounts. Reports per cause, builds a health dashboard, then offers a proposed fix for every cause. For accounts with sub-accounts it can set up a small health-check app whose run logs keep the history. Use for 'connection health', 'connector health check', 'are all our connections running', 'which connections are failing', 'check all sub-accounts', 'daily health check of our connectors', 'is the data from our connectors right', '/peliqan-connection-health'. Changes nothing without your go-ahead. For one sync worker or dashboard use peliqan-audit; for one broken thing, peliqan-support."
---

# Peliqan Connection Health

The way in for a connection health check. The process lives in
`peliqan-support`, so a customer who asks support for help with their
connections goes through the same steps.

Read `../peliqan-support/SKILL.md` (its ground rules apply) and
`../peliqan-support/references/connections.md`, then follow that file from
Step 1:

1. **Scope:** with or without sub-accounts.
2. **Check:** through the MCP for an account without sub-accounts; with the
   health app for an account with sub-accounts.
3. **Report and dashboard:** per cause, with what was not checked.
4. **Offer fixes:** "Shall I propose a fix for each of the N causes?"

If the Peliqan MCP isn't connected, say so and stop.
