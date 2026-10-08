# Support: connection health

Checks whether the connections in an account are running and whether the data
they loaded is right, reports per cause with a health dashboard, then proposes
a fix for every cause. Two ways in, one process:

- `peliqan-connection-health`: someone asks for a health check;
- `peliqan-support` Step 1: someone asks for help with connections or the data
  they load, and chooses the full check over one incident.

Most data defects happen on connections whose status says OK or COMPLETED.
**Run status is never evidence that the data is right.** Freshness against the
connection's own schedule is the pipe signal; the data checks are the data
signal.

## Ground rules

These add to the ground rules in `../SKILL.md`.

- **Count causes, not connections.** One expired token across fifty
  connections is one cause. Never say "N connections are failing" without the
  number of causes.
- **Say what was not checked.** Unreadable sub-accounts, connections whose runs
  were not read, data checks that could not run: every report names them.
- **Re-confirm before acting.** A finding can be a day old. Check the latest
  run or query again before proposing a fix for it.
- **A resync is not a universal fix.** On duplicate keys, stacked versions and
  vanished rows it keeps or adds the bad rows. The playbook says where.
- **Unrecognised error, no guess.** Quote the error text, say it is
  unrecognised, and stop there for that cause.
- **Suppress only with an expiry.** Suppressed findings are still counted.
- **Never write into a source or target** to paper over a gap.

## Step 1 — Scope

`list_sub_accounts`.

- **No sub-accounts:** check the account itself through the MCP (Step 2a). No
  app needed.
- **Sub-accounts:** check them with the health app (Step 2b). Ask whether the
  user wants all sub-accounts or one; a complaint about one customer is that
  customer's sub-account.

## Step 2a — Check through the MCP (account without sub-accounts)

1. `list_connections`. Sources are the connections that are not a target or
   the data warehouse.
2. Per source, `get_connection_pipeline_runs` (the last five runs). Apply the
   pipe rules in the checks table below to each one. For a failed run,
   `get_pipeline_run_logs` gives the error text.
3. Apply the structure rules: disabled, schedule off, two connections of the
   same type where one never succeeded, targets without a source.
4. Data: per source, `list_tables` in its schema, then `get_table` and
   `get_table_runs` for row counts and when rows last arrived. The duplicate,
   version and parent-table checks need SQL. Run them only if the MCP can
   query the warehouse (same SQL as `table_checks` in
   `../assets/connection_health_app.py`); otherwise list them under "not
   checked".
5. There is no history here. If an earlier health dashboard for this account
   exists, compare with its findings for new and recovered. Otherwise report
   the current state only.

## Step 2b — The health app (account with sub-accounts)

One data app, `Connection health`, in the parent account:
`../assets/connection_health_app.py`. It checks every connection in every
sub-account, keeps `first_seen` per finding in its own state, and writes the
result to its run log. It writes nothing else: no table, nothing in a
sub-account.

**App exists** (`list_data_apps`): `get_data_app_runs`, then
`get_data_app_run_logs` on the latest successful run, and read its lines (see
"Run log" below). If that run is older than a day, or the question is about
one sub-account, offer a fresh run:

- one sub-account: `get_data_app_state`, add `"only_accounts": [<id>]`, write
  the whole state back with `update_data_app_state` (it replaces, so merge
  first), then `run_data_app`;
- everything: `run_data_app`.

**No app yet:** offer to set it up. Say that it creates one data app in the
parent account, that it writes only its own state, and that nothing is
scheduled until the user says so. With a yes:

1. Save the script locally. In SETTINGS, leave `ACCOUNTS = None` unless the
   user named sub-accounts. Fill `CONNECTOR_CHECKS` only for connectors these
   sub-accounts actually have, from `connectors/` (see `connectors/README.md`).
2. `create_data_app` named `Connection health`, then `run_data_app`.
3. Read the log. `HEALTH_RUN` must be there, and the number of
   `HEALTH_FINDING` lines must equal its `findings`. Run a second time: no
   finding may be `new` unless something really changed.
4. Ask how often it should run: daily, or only on request. A schedule is set
   with `update_data_app` `schedule_settings`, for example
   `{"schedule": true, "weekdays": [0,1,2,3,4,5,6], "run_interval": 86400, "start_time": "06:00:00"}`.

Large accounts take more than one run for a full pass. `MAX_RUN_LOOKUPS` and
`MAX_DATA_ACCOUNTS` cap the work per run and the next run continues where
this one stopped. Findings that were not checked this run stay open with
`"checked": false` and are never reported as recovered.

**User declines the app:** check the sub-accounts the user names through the
MCP, as in Step 2a, with `sub_account_id` on each call. Say that the other
sub-accounts were not checked.

## Run log

Every line the app writes starts with a tag and is followed by JSON:

```
HEALTH_RUN     {"run_at": ..., "accounts": 12, "accounts_unreadable": 1, "connections": 340,
                "run_history_read": 300, "data_accounts_checked": 12, "data_skipped": [...],
                "connector_checks": [...], "findings": 41, "new": 3, "open": 35,
                "recovered": 2, "suppressed": 1, "critical": 9, "warning": 20}
HEALTH_FINDING {"key": "dark|1234|5678|", "check": "dark", "severity": "CRITICAL", "layer": "pipe",
                "account_id": 1234, "account_name": ..., "connection_id": 5678,
                "connection_name": ..., "connector": ..., "table": null,
                "evidence": "Last success 4.2 days ago, scheduled every 24h; health says OK.",
                "metric": 4.2, "first_seen": "2026-10-06", "days_open": 2,
                "status": "open", "checked": true}
```

- `status`: `new`, `open`, `recovered` (fixed since the last run; reported
  once) or `suppressed` (with `suppressed_until`).
- Fewer `HEALTH_FINDING` lines than `findings` means the log was cut off. Say
  so, and read the rest with a run per sub-account (`only_accounts`).
- For the trend, read the `HEALTH_RUN` line of the earlier runs as well
  (`get_data_app_runs`, then the log of each).

To suppress a finding (`noisy` on a module the customer doesn't have, for
example): with the user's go-ahead, add `"suppress": {"<key>": "<YYYY-MM-DD>"}`
to the app state, merged as above. Always with an expiry date.

## Step 3 — Report and dashboard

In the chat, short:

- the delta first: new, recovered, open for more than 7 days;
- then per cause, most severe first: the check, how many connections and
  sub-accounts, the oldest `first_seen`, one line of evidence;
- what was not checked.

Then the **health dashboard**, as one self-contained HTML page. Where the AI
client can publish a page (a Claude artifact, for example) publish it there,
and update that same page on the next check instead of making a new one.
Otherwise save it as an `.html` file. In a plain chat, tables are enough. It
holds:

- the as-of time, the scope, and what was not checked;
- a top row with causes, new, open for more than 7 days, recovered, and
  connections checked out of the total;
- the causes table: check, severity, connections, sub-accounts, open since,
  example evidence, first step from the playbook;
- with sub-accounts: one row per sub-account with its critical and warning
  counts;
- with the app: the trend of critical and warning counts over the last runs;
- every finding, filterable by check, sub-account and status.

Then offer the next step: **"Shall I propose a fix for each of the N causes?"**

## Step 4 — Propose and fix

Per cause, most severe first:

1. Re-confirm with fresh evidence: the latest run of one affected
   connection, or the query again.
2. Look the check up in the playbook: first step, what not to do, and when it
   counts as fixed.
3. **Do** (only after a yes, one cause at a time): name the exact calls and
   what they touch. If the MCP has no call for the action, say where to do it
   in Peliqan.
4. **Draft** where the AI cannot act: the message to the customer, or the
   report to Peliqan with the evidence and the "fixed when" line.
5. Afterwards the next health run marks the cause `recovered`. With the app,
   offer a run for that sub-account; without it, check the affected
   connection again.

Code changes to a sync worker go through `peliqan-sync`. A temporary read-side
filter (deduplicating or keeping only the latest version) goes through
`peliqan-dashboard`.

## Checks

The thresholds are SETTINGS in the app: late at 2× and dark at 3× the
connection's own run interval, stuck at 3× the connector's median run time,
rows dropped by more than 30 %, no rows received for 7 days.

| Check | Layer | Severity | Signal |
|---|---|---|---|
| `account_unreadable` | pipe | CRITICAL | A sub-account's connections could not be listed |
| `never_ran` | pipe | CRITICAL | No run on record at all |
| `auth_failed` | pipe | CRITICAL | Latest run failed with 401, `invalid_grant` or an expired token |
| `failing` | pipe | CRITICAL | Latest run failed and no success within one interval (or none in the last five runs) |
| `dark` | pipe | CRITICAL | Last success more than 3× the run interval ago |
| `stuck_run` | pipe | CRITICAL | Running for more than 3× the connector's median run time |
| `self_disabled` | pipe | CRITICAL | The connector switched itself off (source exit code 2) |
| `late` | pipe | WARNING | Last success more than 2× the run interval ago |
| `loaded_nothing` | pipe | WARNING | Completed with 0 records where the runs before it always loaded some |
| `run_history_unreadable` | pipe | WARNING | Run history could not be read |
| `disabled` | pipe | WARNING | Connection disabled |
| `duplicate_connection` | pipe | WARNING | Two or more connections of one type in an account, one never succeeded |
| `orphan_target` | pipe | WARNING | A target connection that no source writes to |
| `noisy` | pipe | INFO | Latest run errored, but the data is current |
| `scheduler_off` | pipe | INFO | The schedule is off; runs only by hand |
| `duplicate_keys` | data | CRITICAL | More rows than distinct `id` (> 1.01×) |
| `row_count_drop` | data | CRITICAL | Rows down by more than 30 % since the previous check |
| `parent_table_empty` | data | CRITICAL | Table empty while its child tables (`<table>_*`) have rows |
| `mixed_versions` | data | WARNING | More than one `_sdc_table_version` among live rows |
| `check_failed` | data | WARNING | Data checks could not run for a connection |
| `table_stale` | data | INFO | No rows received for 7 days (normal for reference tables) |
| connector checks | data | per check | See `connectors/` |

## Playbook

**AI may:** *do*: after the user's go-ahead, through the MCP or by saying
where in Peliqan. *Draft*: writes the message or report, someone else acts.
*Explain*: no action.

| Check | Confirm | First step | AI may | Don't | Fixed when |
|---|---|---|---|---|---|
| `account_unreadable` | Call `list_connections` with that `sub_account_id` | Check that the parent token can still read the sub-account; if it can't, report it to Peliqan with the account id | draft | Read "unreadable" as "healthy" | The sub-account's connections are listed |
| `never_ran` | `get_connection_pipeline_runs` is empty; the connection is days old | The customer re-authorises or reconnects; the token never worked, or the connection was never activated | draft | Rerun it again and again | First run completes |
| `auth_failed` | Error text in the latest run log | The customer re-authorises (reauth invite where Peliqan offers one) | draft | Resync | The next run succeeds |
| `failing` | Log of the failing run, against the last good one | Depends on the error: auth → as `auth_failed`; timeout → rerun outside busy hours; anything else → quote it as unrecognised | do (rerun) | Guess at an unknown error | A run succeeds within the interval |
| `dark` | No successful run in the history for > 3× the interval | Trigger one run; if it runs, check that the schedule is on. **Ten or more connections dark since the same day:** platform-side, report the date and the list to Peliqan instead of touching each one | do | Fix a cluster one by one | A run within the interval |
| `stuck_run` | Latest run still running, start time in the log | Stop the run (note its id) and start a new one. If that one stalls too, read its log: a timeout is a connector issue, report it | do | Leave it running for days | A run completes within 3× the median |
| `self_disabled` | The run with exit code 2 and its error | Fix what made it stop, then re-enable | do (re-enable) | Re-enable without fixing the cause: it restarts nothing | Runs on schedule again |
| `late` | As `dark` | Watch it; it becomes `dark` at 3× | explain | — | A run within 2× the interval |
| `loaded_nothing` | Records per table in the last run against the ones before | Check the bookmark of the affected stream against the source; a bookmark reset with a resync is the usual cure | do (after the check) | Call the source empty without looking | The next run loads the usual volume |
| `run_history_unreadable` | Read the runs through the MCP | Report to Peliqan if it persists | draft | — | Runs are readable |
| `disabled` / `scheduler_off` | Ask whether it is on purpose | Enable it if it isn't | do | Enable it without asking | Runs on schedule |
| `duplicate_connection` | Which of the two do downstream tables and apps read from? | Keep that one, delete or disable the other after confirmation | do | Delete before checking what reads from it | One connection per source |
| `orphan_target` | Nothing writes to it or reads from it | Delete it after confirmation | do | — | Gone |
| `noisy` | The same error on every run, data current (often 403 on a module the customer doesn't have) | Confirm with the customer once, then suppress with an expiry | do (suppress) | Treat it as `failing` | Suppressed until the date, or the error stops |
| `duplicate_keys` | `COUNT(*)` against `COUNT(DISTINCT id)`; check that `id` really is this stream's key (some key on `id` plus another column: then suppress) | Report to Peliqan as a connector issue with the table, the ratio and since when. In the meantime, a deduplicating view for reporting | draft (report), do (view) | Resync or reset the bookmark: it adds a copy or leaves the rows in place | 1.0 rows per key |
| `row_count_drop` | Compare with the count in the source | Rows the source still has → report to Peliqan. Removed at the source → expected; suppress until the next check | draft | Write it off as a clean-up without checking the source | The count matches the source |
| `parent_table_empty` | The stream's lines in the run log (API errors?) | API errors → report to Peliqan; an empty answer → check the source permission with the customer | draft | — | Rows in line with its child tables |
| `mixed_versions` | Per entity: are superseded rows counted twice? | Report to Peliqan. In the meantime a view that keeps only the latest version | draft (report), do (view) | Resync: it doesn't retire old versions | One live version |
| `check_failed` | The error text | Usually another warehouse dialect or table layout: adapt the app's discovery query | do (code, after a yes) | — | The checks run |
| `table_stale` | Is this a reference table, or should it change daily? | Only for tables that should change: check that the stream is still selected | explain | Report every quiet reference table | Rows arrive again |
| connector checks | See the connector's file in `connectors/` | | | | |
