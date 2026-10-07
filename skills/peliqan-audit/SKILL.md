---
name: peliqan-audit
description: "Audits something in a Peliqan account that looks healthy — before go-live, after a change, or as a periodic check — and returns a pass/warn/fail scorecard with evidence and a ranked fix list. For sync workers it checks the framework contract (version, >= bookmarks, catalog-registered link tables, hash coverage, the 6-step record path, data-loss guards), leftover test settings, and runtime health (error and dead counts, stuck bookmarks, duplicates). For dashboards it checks the medallion layers (business rules only in Gold, consumer layer a passthrough, dashboard reading only the consumer layer), correctness against the PBIX/DAX where available, presentation, freshness and load time. Use when someone asks to 'audit the sync', 'review our worker', 'is this production-ready', 'can we go live', 'validate the order sync', 'check the dashboard', 'does the dashboard match Power BI', 'health check', or '/peliqan-audit'. Read-only: it never deploys, runs, rewinds or replays. For something already broken, use peliqan-support; to apply fixes, the build skill (peliqan-sync for syncs, peliqan-dashboard for dashboards)."
---

# Peliqan Audit

Checks something nobody has reported as broken yet, and looks for the problems
that haven't surfaced. Domain-specific checks live in `references/`:

| What to audit | Read |
|---|---|
| A sync worker | `references/sync.md` |
| A dashboard and its medallion layers | `references/dashboard.md` |

Paths inside a reference file are relative to that file. If the user asks to
audit something with no reference file yet, say so: do a careful read-only
review, but label it a review, not an audit against a contract.

## Ground rules

- **Read-only, no exceptions.** List, read and query only. Never run, deploy,
  update, rewind, replay or write anything. A run is a write.
- **Local offline checks are fine.** Saving a script locally and compiling or
  testing it touches nothing in the account.
- **Evidence for every score.** Each pass/warn/fail cites a code line, a log
  line or a row count. No evidence → `n/a` with what would decide it.
- **Healthy behaviour is not a finding.** Skips on unchanged records, or unused
  helpers that the contract ships on purpose, are not problems.
- **An active incident goes to support.** If the audit finds something already
  broken, say so and hand it to `peliqan-support`.
- If the Peliqan MCP isn't connected, say so and stop. Reviewing a pasted
  script alone is a code review, not an audit.

## Report

1. **Verdict** in one line: **ready**, **ready with warnings**, or **not
   ready**. Any fail means not ready.
2. **Scorecard**, one row per check:

   | # | Check | Result | Evidence |
   |---|---|---|---|
   | C2 | Incremental filters | fail | `L212: updated_at > '{bookmark}'` |

3. **Findings**, most severe first: what is wrong, what it can cost (lost
   records, duplicates, a crashed or slow run), and the fix routed to the
   build skill (`peliqan-sync` for syncs, `peliqan-dashboard` for dashboards) or to `peliqan-support`.
4. **Open questions** that blocked a check.

Never apply a fix from this skill.
