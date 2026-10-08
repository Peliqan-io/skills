# Peliqan data app: Connection health
#
# For accounts with sub-accounts (an account without them is checked by the AI
# through the MCP, no app needed). Checks every connection in every sub-account:
#   pipe  is it running? Freshness against its own run interval, stuck runs,
#         authorisation errors, runs that load nothing, leftover connections
#   data  is what it loaded right? Duplicate keys, stacked snapshot versions,
#         vanished rows, empty parent tables, plus the connector checks below
# and writes the result to the run log as JSON lines:
#   HEALTH_RUN {...}       one per run: scope, counts, coverage
#   HEALTH_FINDING {...}   one per finding, status new | open | recovered | suppressed
# The AI reads these lines with get_data_app_run_logs to report, build the
# health dashboard and propose fixes (../references/connections.md).
#
# It writes nothing but this app's own state: open findings with first_seen,
# row-count baselines, resume cursors and suppressions. Nothing is written
# into a connection, a warehouse or a sub-account.
#
# State keys the AI may set before a run (merge, keep the rest):
#   only_accounts  [account ids]: check just these this run (removed after it)
#   suppress       {finding key: "YYYY-MM-DD"}: report as suppressed until then

import json
import re
from collections import defaultdict
from datetime import date, datetime, timezone

# ---- SETTINGS ------------------------------------------------------------------
ACCOUNTS = None           # None: every sub-account; or [sub-account ids]
CONNECTORS = None         # None: every connector; or [server_type, ...]
DATA_CHECKS = True        # False: pipe checks only, no warehouse queries
MAX_RUN_LOOKUPS = 300     # connections whose run history is read per run; the rest follow next run
MAX_DATA_ACCOUNTS = 25    # accounts whose tables are checked per run; the rest follow next run
RUNS_PAGE_SIZE = 5        # recent runs read per connection
LATE, DARK = 2, 3         # x the connection's own run interval since the last success
STUCK = 3                 # x the connector's median run time
ROW_DROP = 0.30           # rows down by more than this share since the previous check
STALE_TABLE_DAYS = 7
# Connector checks from ../references/connectors/, only for connectors this
# account has: {server_type: [(check, severity, sql)]}. The SQL returns the
# rows that break the rule (none = OK); {t[stream]} becomes that stream's table.
CONNECTOR_CHECKS = {}

OK = ("COMPLETED", "COMPLETED_WITH_ERRORS")
RUNNING = ("RUNNING", "IN_PROGRESS", "SYNC_IN_PROGRESS")
AUTH_SIGNS = ("401", "unauthorized", "invalid_grant", "refresh token", "expired access token", "chainid")
SEVERITY = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}


# ---- plumbing ------------------------------------------------------------------

def emit(tag, payload):
    line = "%s %s" % (tag, json.dumps(payload, default=str))
    try:
        st.text(line)   # lands in the run log, like the sync worker's st.* lines
    except NameError:
        print(line)


def as_json(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def parse_ts(v):
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None
    return t.replace(tzinfo=timezone.utc) if t and t.tzinfo is None else t


def inst(account_id):
    return pq.get_subaccount_instance(account_id=account_id)


def finding(check, severity, unit, account, conn=None, evidence="", table=None, metric=None):
    cid = conn["id"] if conn else None
    return {"key": "|".join(str(x) for x in (check, account["id"], cid or "", table or "")),
            "check": check, "severity": severity, "layer": "data" if unit.startswith("data:") else "pipe",
            "unit": unit, "account_id": account["id"], "account_name": account.get("name"),
            "connection_id": cid, "connection_name": conn["name"] if conn else None,
            "connector": conn["connector"] if conn else None, "table": table,
            "evidence": evidence[:300], "metric": metric}


# ---- 1. scope and connections --------------------------------------------------

def accounts_in_scope(only):
    subs, page, error = [], 1, None
    try:
        while True:
            r = as_json(pq.list_subaccounts(page=page))
            if not isinstance(r, dict):
                break
            subs += r.get("data") or []
            if not r.get("next"):
                break
            page += 1
    except Exception as e:
        error = str(e)[:200]
    accounts = [{"id": a.get("id"), "name": a.get("name")} for a in subs]
    wanted = {str(x) for x in (only or ACCOUNTS or [])}
    if wanted:
        accounts = [a for a in accounts if str(a["id"]) in wanted]
    return accounts, error


def sweep(accounts):
    """Every connection per account. An unreadable account is a finding, never a skip."""
    conns, findings, readable = [], [], set()
    for a in accounts:
        try:
            found = as_json(inst(a["id"]).list_connections()) or []
        except Exception as e:
            findings.append(finding("account_unreadable", "CRITICAL", "acct:%s" % a["id"], a,
                                    evidence="Connections could not be listed: %s" % str(e)[:200]))
            continue
        readable.add(a["id"])
        for c in found:
            conns.append({
                "account": a, "id": c.get("id") or c.get("connection_id"), "name": c.get("name"),
                "connector": c.get("server_type"), "health": (c.get("health_status") or "").upper(),
                "is_dw": bool(c.get("is_datawarehouse")),
                "is_target": bool(c.get("is_target") or c.get("is_datawarehouse")),
                "target": c.get("target"), "schema": (c.get("target_schema") or {}).get("schema_name"),
                "interval_h": (c.get("run_interval") or 86400) / 3600.0,
                "scheduler_off": bool(c.get("disable_scheduler")),
            })
    return conns, findings, readable


# ---- 2. pipe -------------------------------------------------------------------

def fetch_runs(account_id, connection_id):
    # The sub-account's own service client on /api/servers/<id>/runs/ is the
    # call that works (pq.get_pipeline_runs 404s on a sub-account instance).
    url = "%s/api/servers/%s/runs/?page_size=%d" % (pq.BACKEND_URL, connection_id, RUNS_PAGE_SIZE)
    r = inst(account_id).__service_client__.call_backend(method="get", url=url, expected_status_code=200)
    body = as_json(r.json() if hasattr(r, "json") else r)
    return (body.get("data") if isinstance(body, dict) else body) or []


def records_in(run):
    """Records loaded by one run, summed over its tables; None if the shape is unknown."""
    tables = as_json(run.get("tables"))
    if not isinstance(tables, (list, dict)):
        return None
    total, seen = 0, False
    for t in (tables.values() if isinstance(tables, dict) else tables):
        for k in ("records", "record_count", "rows", "row_count"):
            if isinstance(t, dict) and isinstance(t.get(k), (int, float)):
                total, seen = total + int(t[k]), True
                break
    return total if seen else None


def error_text(run):
    txt = " ".join(str(run.get(k) or "") for k in ("error", "message", "source_error", "status_message"))
    txt = re.sub(r"\d{4,}", "<n>", re.sub(r"https?://\S+", "<url>", txt)).strip()
    return txt[:160] or "no error text"


def pick(items, state, cursor, cap, resume):
    """Up to cap items, continuing where the previous run stopped."""
    if not resume:
        return items[:cap]
    done = set(state.get(cursor) or [])
    todo = [i for i in items if str(i["id"]) not in done]
    if not todo:
        done, todo = set(), items
    batch = todo[:cap]
    state[cursor] = sorted(done | {str(i["id"]) for i in batch})
    return batch


def pipe_layer(sources, state, now, resume):
    findings, checked, ok, history, durations = [], set(), {}, {}, defaultdict(list)
    for c in pick(sources, state, "runs_done", MAX_RUN_LOOKUPS, resume):
        checked.add("conn:%s" % c["id"])
        try:
            history[c["id"]] = fetch_runs(c["account"]["id"], c["id"])
        except Exception as e:
            findings.append(finding("run_history_unreadable", "WARNING", "conn:%s" % c["id"], c["account"], c,
                                    "Run history could not be read: %s" % str(e)[:200]))
    for c in sources:
        for r in history.get(c["id"], []):
            s, e = parse_ts(r.get("timestamp_start")), parse_ts(r.get("timestamp_end"))
            if s and e and r.get("status") in OK:
                durations[c["connector"]].append((e - s).total_seconds())
    median = {k: sorted(v)[len(v) // 2] for k, v in durations.items()}

    for c in sources:
        runs = history.get(c["id"])
        if runs is None:
            continue

        def add(check, severity, text, metric=None):
            findings.append(finding(check, severity, "conn:%s" % c["id"], c["account"], c, text, metric=metric))

        if not runs:
            ok[c["id"]] = False
            add("never_ran", "CRITICAL", "No run on record; health says %s." % (c["health"] or "nothing"))
            continue
        latest, status = runs[0], runs[0].get("status")
        started = parse_ts(latest.get("timestamp_start"))
        last_ok = next((parse_ts(r.get("timestamp_start")) for r in runs if r.get("status") in OK), None)
        ok[c["id"]] = last_ok is not None
        if status in RUNNING:
            run_s = (now - started).total_seconds() if started else 0
            med = median.get(c["connector"])
            if med and run_s > med * STUCK and run_s > 3600:
                add("stuck_run", "CRITICAL", "Running %.1fh, %.0fx the connector's median run (run %s)."
                    % (run_s / 3600, run_s / med, latest.get("id")))
            continue
        err = error_text(latest) if status != "COMPLETED" else ""
        if str(latest.get("status_code_from_source")) == "2":
            add("self_disabled", "CRITICAL", "The connector disabled itself (source exit code 2) at %s: %s" % (started, err))
        age_h = (now - last_ok).total_seconds() / 3600 if last_ok else None
        if err and any(s in err.lower() for s in AUTH_SIGNS):
            add("auth_failed", "CRITICAL", "Last run %s on authorisation: %s" % (status, err))
        elif age_h is None:
            add("failing", "CRITICAL", "No successful run in the last %d; last one %s: %s" % (len(runs), status, err))
        elif age_h > c["interval_h"] * DARK:
            add("dark", "CRITICAL", "Last success %.1f days ago, scheduled every %.0fh; health says %s."
                % (age_h / 24, c["interval_h"], c["health"] or "nothing"), metric=round(age_h / 24, 1))
        elif status not in OK and age_h > c["interval_h"]:
            add("failing", "CRITICAL", "Last run %s, no success for %.0fh: %s" % (status, age_h, err))
        elif err:
            add("noisy", "INFO", "Last run %s but data is current (%.0fh old): %s" % (status, age_h, err))
        elif age_h > c["interval_h"] * LATE:
            add("late", "WARNING", "Last success %.0fh ago, scheduled every %.0fh." % (age_h, c["interval_h"]))
        if status == "COMPLETED" and records_in(latest) == 0:
            before = [n for n in (records_in(r) for r in runs[1:] if r.get("status") in OK) if n is not None]
            if len(before) >= 2 and min(before) > 0:
                add("loaded_nothing", "WARNING", "Last run loaded 0 records; the %d before it loaded %d-%d."
                    % (len(before), min(before), max(before)))
    return findings, checked, ok


def structure(conns, ok):
    """Per account, from metadata only: switched off, leftovers, re-created connections."""
    findings, by_acct = [], defaultdict(list)
    for c in conns:
        by_acct[c["account"]["id"]].append(c)
    for group in by_acct.values():
        a = group[0]["account"]
        unit = "acct:%s" % a["id"]
        sources = [c for c in group if not c["is_target"]]
        for c in sources:
            if c["health"] == "DISABLED":
                findings.append(finding("disabled", "WARNING", unit, a, c, "Connection is disabled."))
            elif c["scheduler_off"]:
                findings.append(finding("scheduler_off", "INFO", unit, a, c, "Schedule is off: runs only by hand."))
        by_type = defaultdict(list)
        for c in sources:
            by_type[c["connector"]].append(c)
        for g in by_type.values():
            dead = [c for c in g if ok.get(c["id"]) is False]
            if len(g) > 1 and dead:
                findings.append(finding("duplicate_connection", "WARNING", "conn:%s" % dead[0]["id"], a, dead[0],
                                        "%d %s connections in one account (%s); %s never succeeded. Likely re-created."
                                        % (len(g), dead[0]["connector"], ", ".join(str(c["id"]) for c in g),
                                           ", ".join(str(c["id"]) for c in dead))))
        used = {str(c["target"]) for c in sources if c["target"]}
        for t in group:
            if t["is_target"] and not t["is_dw"] and str(t["id"]) not in used:
                findings.append(finding("orphan_target", "WARNING", unit, a, t, "Target without a source connection."))
    return findings


# ---- 3. data -------------------------------------------------------------------

COLUMNS_SQL = {
    "postgres": "SELECT table_schema, table_name, column_name FROM information_schema.columns WHERE table_schema = '{schema}'",
    "snowflake": "SELECT table_schema, table_name, column_name FROM information_schema.columns WHERE UPPER(table_schema) = UPPER('{schema}')",
    "bigquery": "SELECT table_schema, table_name, column_name FROM `{schema}.INFORMATION_SCHEMA.COLUMNS`",
}


def dialect_of(target):
    t = (target["connector"] or "").lower()
    return "bigquery" if "bigquery" in t else "snowflake" if "snowflake" in t else "postgres"


def quote(dialect, name):
    return "`%s`" % name if dialect == "bigquery" else '"%s"' % name


def qualify(dialect, schema, table):
    return "`%s.%s`" % (schema, table) if dialect == "bigquery" else "%s.%s" % (quote(dialect, schema), quote(dialect, table))


class Tables(dict):
    """{t[stream]} in a connector check: that stream's qualified table name."""

    def __init__(self, dialect, schema, names):
        super().__init__()
        self.dialect, self.schema, self.names = dialect, schema, names

    def __missing__(self, stream):
        return qualify(self.dialect, self.schema, self.names.get(stream.lower(), stream))


def table_checks(q, dialect, schema, table, cols, a, src, baseline):
    unit, f = "data:%s" % a["id"], []
    col = lambda k: quote(dialect, cols[k])
    pk = next((k for k in ("id", "_id", "key", "uuid") if k in cols), None)
    live = (lambda e: "CASE WHEN %s IS NULL THEN %s END" % (col("_sdc_deleted_at"), e)) \
        if "_sdc_deleted_at" in cols else (lambda e: e)
    sel = ["COUNT(*) AS n"]
    if pk:
        sel.append("COUNT(DISTINCT %s) AS ids" % col(pk))
    if "_sdc_table_version" in cols:
        sel.append("COUNT(DISTINCT %s) AS versions" % live(col("_sdc_table_version")))
    if "_sdc_received_at" in cols:
        sel.append("MAX(%s) AS last_received" % col("_sdc_received_at"))
    rows = q("SELECT %s FROM %s" % (", ".join(sel), qualify(dialect, schema, table)))
    r = {k.lower(): v for k, v in (rows[0] if rows else {}).items()}
    n, ids = int(r.get("n") or 0), int(r.get("ids") or 0)
    if ids and n / ids > 1.01:
        f.append(finding("duplicate_keys", "CRITICAL", unit, a, src, "%d rows for %d distinct %s (%.2fx)."
                         % (n, ids, cols[pk], n / ids), table, round(n / ids, 2)))
    if int(r.get("versions") or 0) > 1:
        f.append(finding("mixed_versions", "WARNING", unit, a, src, "%d snapshot versions live side by side."
                         % int(r["versions"]), table, int(r["versions"])))
    last = parse_ts(r.get("last_received"))
    if last and (datetime.now(timezone.utc) - last).days > STALE_TABLE_DAYS:
        f.append(finding("table_stale", "INFO", unit, a, src, "No rows received since %s." % last.date(), table))
    key = "%s|%s|%s" % (a["id"], src["id"], table)
    prev = baseline.get(key)
    if prev and n < prev * (1 - ROW_DROP):
        f.append(finding("row_count_drop", "CRITICAL", unit, a, src, "%d rows, was %d at the previous check." % (n, prev),
                         table, round(n / float(prev), 2)))
    baseline[key] = n
    return f, n


def data_layer(accounts, conns, readable, state, resume):
    findings, checked, skipped = [], set(), []
    baseline = state.setdefault("row_counts", {})
    for a in pick([a for a in accounts if a["id"] in readable], state, "data_done", MAX_DATA_ACCOUNTS, resume):
        checked.add("data:%s" % a["id"])
        mine = [c for c in conns if c["account"]["id"] == a["id"]]
        targets = {str(c["id"]): c for c in mine if c["is_target"]}
        default = next((c for c in mine if c["is_dw"]), None) or next(iter(targets.values()), None)
        for src in mine:
            if src["is_target"] or not src["schema"]:
                continue
            target = targets.get(str(src["target"])) or default
            if not target:
                skipped.append("%s: no target for connection %s" % (a["id"], src["id"]))
                continue
            dialect = dialect_of(target)
            try:
                db = inst(a["id"]).dbconnect(target["name"])
                q = lambda sql: [{k.lower(): v for k, v in r.items()} for r in
                                 (as_json(db.fetch(target["name"], query=sql)) or [])]
                cols, schema = defaultdict(dict), src["schema"]
                for r in q(COLUMNS_SQL[dialect].format(schema=src["schema"])):
                    schema = r["table_schema"]
                    cols[r["table_name"]][r["column_name"].lower()] = r["column_name"]
                counts = {}
                for table, cs in cols.items():
                    if "__sdc_" not in table:
                        fs, counts[table] = table_checks(q, dialect, schema, table, cs, a, src, baseline)
                        findings += fs
                for table, n in counts.items():
                    kids = [t for t, m in counts.items() if t.startswith(table + "_") and m > 0]
                    if n == 0 and kids:
                        findings.append(finding("parent_table_empty", "CRITICAL", "data:%s" % a["id"], a, src,
                                                "Empty while %d child tables have rows (%s)." % (len(kids), ", ".join(kids[:3])), table))
                names = Tables(dialect, schema, {t.lower(): t for t in cols})
                for check, severity, sql in CONNECTOR_CHECKS.get(src["connector"], []):
                    bad = q(sql.format(t=names))
                    if bad:
                        findings.append(finding(check, severity, "data:%s" % a["id"], a, src, "%d rows break the rule, e.g. %s"
                                                % (len(bad), json.dumps(bad[0], default=str)[:200]), metric=len(bad)))
            except Exception as e:
                findings.append(finding("check_failed", "WARNING", "data:%s" % a["id"], a, src,
                                        "Data checks could not run: %s" % str(e)[:200]))
    return findings, checked, skipped


# ---- 4. compare with the previous run ------------------------------------------

def compare(findings, checked, state, today):
    """new / open / recovered / suppressed, with first_seen kept in state. A finding
    whose connection or account was not checked this run stays open, unchecked."""
    prev, suppress = state.get("open") or {}, state.get("suppress") or {}
    current, recovered = {}, []
    for f in findings:
        p = prev.get(f["key"])
        f.update(first_seen=p["first_seen"] if p else today, status="open" if p else "new", checked=True)
        current[f["key"]] = f
    for k, p in prev.items():
        if k not in current:
            if p["unit"] in checked:
                recovered.append(dict(p, status="recovered", checked=True))
            else:
                current[k] = dict(p, status="open", checked=False)
    for f in current.values():
        until = suppress.get(f["key"])
        if until and until >= today:
            f.update(status="suppressed", suppressed_until=until)
        elif until:
            f["evidence"] = "%s (suppression expired %s)" % (f["evidence"], until)
        f["days_open"] = (date.fromisoformat(today) - date.fromisoformat(f["first_seen"])).days
    state["open"] = {k: {x: v for x, v in f.items() if x not in ("status", "checked", "days_open", "suppressed_until")}
                     for k, f in current.items()}
    return list(current.values()) + recovered


# ---- run -------------------------------------------------------------------------

def run():
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    state = as_json(pq.get_state()) or {}
    only = state.pop("only_accounts", None)
    accounts, subaccounts_error = accounts_in_scope(only)
    if not accounts:
        pq.set_state(state)
        emit("HEALTH_RUN", {"run_at": now.isoformat(timespec="seconds"), "accounts": 0, "only_accounts": only,
                            "subaccounts_error": subaccounts_error or "no sub-accounts in scope",
                            "findings": 0})
        return
    conns, findings, readable = sweep(accounts)
    if CONNECTORS:
        conns = [c for c in conns if c["is_target"] or c["connector"] in CONNECTORS]
    checked = {"acct:%s" % a["id"] for a in accounts}
    sources = [c for c in conns if not c["is_target"] and not c["scheduler_off"] and c["health"] != "DISABLED"]

    pipe, pipe_checked, ok = pipe_layer(sources, state, now, resume=not only)
    findings += pipe + structure(conns, ok)
    checked |= pipe_checked
    data_checked, skipped = set(), []
    if DATA_CHECKS:
        data, data_checked, skipped = data_layer(accounts, conns, readable, state, resume=not only)
        findings += data
        checked |= data_checked

    rows = compare(findings, checked, state, today)
    pq.set_state(state)

    count = lambda field, value: sum(1 for r in rows if r[field] == value)
    emit("HEALTH_RUN", {
        "run_at": now.isoformat(timespec="seconds"),
        "only_accounts": only, "accounts": len(accounts), "accounts_unreadable": len(accounts) - len(readable),
        "subaccounts_error": subaccounts_error, "connections": len(sources),
        "run_history_read": len(pipe_checked), "data_accounts_checked": len(data_checked),
        "data_skipped": skipped[:20], "connector_checks": sorted(CONNECTOR_CHECKS),
        "findings": len(rows), "new": count("status", "new"), "open": count("status", "open"),
        "recovered": count("status", "recovered"), "suppressed": count("status", "suppressed"),
        "critical": count("severity", "CRITICAL"), "warning": count("severity", "WARNING"),
    })
    for r in sorted(rows, key=lambda r: (SEVERITY[r["severity"]], r["check"], str(r["account_id"]))):
        emit("HEALTH_FINDING", {k: v for k, v in r.items() if k != "unit"})


run()
