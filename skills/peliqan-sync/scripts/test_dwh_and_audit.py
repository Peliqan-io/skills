"""Fake-platform smoke test for framework v6 additions: dwh_drain + audit.
Usage: python smoke_v6.py <worker_template.py>"""
import sys
import duckdb

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


con = duckdb.connect()


class DB:
    def fetch(self, dw, query):
        cur = con.execute(query)
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def execute(self, dw, query):
        con.execute(query)

    def insert(self, dw, schema, table, record):
        cols = ", ".join(record)
        con.execute(f"INSERT INTO {schema}.{table} ({cols}) VALUES ({', '.join('?' * len(record))})",
                    list(record.values()))


class PQ:
    DW_NAME = "dw"
    state = {}

    def dbconnect(self, name):
        return DB()

    def connect(self, name):
        return object()

    def get_state(self):
        return dict(self.state)

    def set_state(self, s):
        PQ.state = dict(s)

    def refresh_schema(self, **kw):
        pass


log = []


class ST:
    def __getattr__(self, name):
        return lambda *a, **k: log.append((name, " ".join(str(x) for x in a)))


ns = {"pq": PQ(), "st": ST()}
exec(open(sys.argv[1]).read(), ns)

# --- schema -------------------------------------------------------------
tables = {r[0] for r in con.execute(
    "SELECT table_name FROM information_schema.tables WHERE table_schema='link_tables'").fetchall()}
check("ensure_schema creates audit table + view",
      {"audit_shopify_odoo", "v_audit_latest_shopify_odoo"} <= tables)
check("no audit on a normal run", not any("Audit" in m for _, m in log))

# --- dwh_drain ------------------------------------------------------------
con.execute("CREATE SCHEMA src")
con.execute("CREATE TABLE src.products (id int, updated_at text, title text)")
rows = [(1, "2026-10-01 10:00:00"), (2, "2026-10-01 10:00:05"), (3, "2026-10-01 10:00:05"),
        (4, "2026-10-01 10:00:05"), (5, "2026-10-01 11:00:00"), (6, "2026-10-01 09:00:00")]
for i, ts in rows:
    con.execute("INSERT INTO src.products VALUES (?, ?, ?)", [i, ts, f"p{i}"])
pages = list(ns["dwh_drain"]("src.products", "updated_at", "2026-10-01 10:00:05", page_size=2))
got = [r["id"] for p in pages for r in p]
check("dwh_drain uses >= (equal-second records included)", got[:3] == [2, 3, 4])
check("dwh_drain pages oldest-first with id tiebreak, until empty", got == [2, 3, 4, 5] and len(pages) == 2)
check("dwh_drain shows a freshness line", any("max updated_at = 2026-10-01 11:00:00" in m for _, m in log))
ov = ns["bookmark_with_overlap"]("2026-10-01 10:00:05", fmt="%Y-%m-%d %H:%M:%S", seconds=3600)
check("pipeline-lag overlap rewinds one interval",
      [r["id"] for p in ns["dwh_drain"]("src.products", "updated_at", ov) for r in p] == [1, 2, 3, 4, 5])
try:
    list(ns["dwh_drain"]("src.missing_table", "updated_at", "2026"))
    check("dwh_drain raises on a failed query", False)
except RuntimeError as e:
    check("dwh_drain raises on a failed query", "source_error" in str(e))

# --- audit ------------------------------------------------------------------
lt = "link_tables.link_shopify_odoo"
link = [  # id, sync, status, shopify_id, ts
    (1, "s_products", "ok", "A", "2026-10-01T10:00:00Z"),
    (2, "s_products", "target_error", "B", "2026-10-01T10:00:00Z"),
    (3, "s_products", "ok", "B", "2026-10-01T11:00:00Z"),      # B recovered
    (4, "s_products", "target_error", "C", "2026-10-01T10:00:00Z"),
    (5, "s_products", "dead", "D", "2026-10-01T10:00:00Z"),
]
for i, s, status, sid, ts in link:
    con.execute(f"INSERT INTO {lt} (id, sync_name, action, status, shopify_id, timestamp) VALUES (?,?,?,?,?,?)",
                [i, s, "insert", status, sid, ts])


def audit_products():
    ns["record_audit"]("s_products", "missing", shopify_id="E")
    return {"missing": 1}


ns["SYNC_REGISTRY"].append({"name": "s_products", "run": lambda: {"processed": 0}, "audit": audit_products})
PQ.state = {"audit": {"requested": True}}
log.clear()
ns["process_all"]()
found = ns["fetch"]("SELECT check_name, shopify_id, detail FROM link_tables.v_audit_latest_shopify_odoo ORDER BY check_name, detail")
check("backlog counts only latest-not-ok ids (C target_error, D dead; B recovered)",
      sorted(r["detail"] for r in found if r["check_name"] == "backlog") == ["dead: 1", "target_error: 1"])
check("per-sync audit fn findings recorded", any(r["check_name"] == "missing" and r["shopify_id"] == "E" for r in found))
check("audit request cleared after the run", PQ.state.get("audit", {}).get("requested") is False)
check("audit writes nothing to the link table", con.execute(f"SELECT count(*) FROM {lt}").fetchone()[0] == 5)
log.clear()
ns["process_all"]()
check("no audit on the next run without a request", not any("Audit" in m for _, m in log))

ns["AUDIT_EVERY_N_RUNS"] = 2
PQ.state = {"audit": {"requested": False, "runs_since": 0}}
log.clear(); ns["process_all"](); first = any("Audit" in m for _, m in log)
log.clear(); ns["process_all"](); second = any("Audit" in m for _, m in log)
check("AUDIT_EVERY_N_RUNS=2 audits every second run", not first and second)


def boom():
    raise ValueError("drift read failed")


ns["SYNC_REGISTRY"][0]["audit"] = boom
PQ.state = {"audit": {"requested": True}}
log.clear(); ns["process_all"]()
check("a failing audit fn is recorded as audit_error, run continues",
      any(r["check_name"] == "audit_error" for r in ns["fetch"](
          "SELECT check_name FROM link_tables.v_audit_latest_shopify_odoo")))

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
