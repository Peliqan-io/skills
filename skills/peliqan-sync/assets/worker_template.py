# ============================================================
# SHOPIFY-ODOO DATA SYNC WORKER  ({ACCOUNT_LABEL})
# framework version: 5   (keep FRAMEWORK_VERSION below in sync)
# ============================================================
# CHANGELOG (bump WORKER_VERSION below with every deploy; it is the only way
# to read back which version an account runs)
#   1  {DATE}  scaffold: framework v5, no syncs yet
# ============================================================
# Default system pair: Shopify (SYSTEM A) <-> Odoo (SYSTEM B).
# For a DIFFERENT pair, this file is a mechanical rename of the two system
# tokens (see references/worker-build.md, "A different system pair"). No
# generic system_a/system_b indirection: a worker is bound to one pair for life.
#
# Data apps are single files (no cross-app import), so this framework is
# EMBEDDED. The skill owns the canonical copy and bumps FRAMEWORK_VERSION;
# the sync-builder upgrades this block in place when a worker is stale.
#
# WHAT THIS APP DOES
# A scheduled Worker that runs every enabled sync between Shopify and Odoo
# through process_all(), driven by SYNC_REGISTRY and SYNCS_ENABLED. Each sync
# is a trio (fieldmapping_* / process_<one record> / process_<sync>). Order:
# parents before children, all Shopify -> Odoo first, then Odoo -> Shopify.
#
# STEPS PER RECORD (the 6-step contract)
#   1 validate source  2 lookup link  3 map + stable hash (equal = skip)
#   4 writeback (1 record/call; may fan out / branch)  5 handle response
#   6 append link row (hash only on ok)
#
# RELIABILITY (all generic, inherited by every sync)
#   - two error statuses: source_error / target_error; an error row carries
#     error_detail + an attempt counter. At MAX_ATTEMPTS a row becomes
#     'dead' (poison record; stops retrying).
#   - replay_source(): re-drives error/dead rows from the stored source JSON.
#   - append-only link table + hash-skip = idempotent replays.
#   - per-run link cache (prefetch_links) with write-through on ok rows.
#   - is_ok() also rejects a functional error inside a 200; the source drains
#     raise on it, so a broken read never looks like "0 records".
#   - run log + monitor views; a run summary with durations and a Bookmarks
#     block (before -> after / unchanged).
#   - ensure_schema creates, REGISTERS (pq.refresh_schema) and VERIFIES the
#     warehouse objects; an unregistered link table ABORTS the run instead of
#     silently dropping link rows while writing to the target.
#   - nothing else aborts the run: sync-, record- and link-write-level guards.
#
# LINK TABLE  <LINK_SCHEMA>.link_<pair>  (per-worker, append-only, self-created)
#   id | sync_name | action | status | attempt | shopify_id | odoo_id
#   shopify_source_hash | odoo_source_hash
#   shopify_source_json | odoo_source_json | error_detail | timestamp
#
# TEST: TEST_LIMIT caps processed records per sync per run (None/0 = all);
# SYNCS_ENABLED switches single syncs off for a staged first run.
# ============================================================

import hashlib
import json
import time
import traceback
from datetime import datetime

FRAMEWORK_VERSION = "5"
WORKER_VERSION = "1"    # bump with every deploy, plus a CHANGELOG line above
TEST_LIMIT = 100        # None or 0 = process everything
MAX_ATTEMPTS = 5        # after this many failures a link row is marked 'dead'

dw_name = pq.DW_NAME
dbconn = pq.dbconnect(dw_name)
shopify_api = pq.connect('Shopify V2')   # SYSTEM A connection: use the account's exact name
odoo_api = pq.connect('Odoo')            # SYSTEM B connection: use the account's exact name

st.title("Shopify-Odoo data sync - Worker")
st.caption(f"worker v{WORKER_VERSION} · framework v{FRAMEWORK_VERSION} · "
           f"TEST_LIMIT = {TEST_LIMIT if TEST_LIMIT else 'all'} · MAX_ATTEMPTS = {MAX_ATTEMPTS}")

# --- per-worker warehouse objects -----------------------------------------
# Each worker (system pair) owns its OWN link table, run log and views, so
# multiple workers for different pairs never collide and each has correctly
# named id columns. Name them after this worker's pair. A sandbox copy of a
# worker gets its own PAIR (see SKILL.md, "A sandbox is a copy of the app").
LINK_SCHEMA = "link_tables"
PAIR = "shopify_odoo"                 # this worker's pair; part of every object name
LINK_TABLE = f"link_{PAIR}"          # e.g. link_shopify_odoo
RUNS_TABLE = f"runs_{PAIR}"          # e.g. runs_shopify_odoo
_LT = f"{LINK_SCHEMA}.{LINK_TABLE}"  # convenience for queries
# NOTE: the original hand-built worker used link_tables.link_table. To REUSE
# that existing data instead of a fresh per-pair table, set:
#   PAIR = "shopify_odoo"; LINK_TABLE = "link_table"; RUNS_TABLE = "sync_runs"

ERROR_STATUSES = ("source_error", "target_error")

# --- sync name constants (one per sync; added by the sync-builder) ---
# Convention: "<sourcesys>_<sourceobj>_to_<targetsys>_<targetobj>"


# per-sync on/off for staged first runs; a sync missing here is ON.
# e.g. SYNCS_ENABLED = {SYNC_STOCK: False}
SYNCS_ENABLED = {}


def _limit_reached(processed):
    return bool(TEST_LIMIT) and processed >= TEST_LIMIT


# ------------------------------------------------------------
# Schema bootstrap: link table + run log + monitor views, created AND
# REGISTERED, then VERIFIED (idempotent; safe on first and every later run)
# ------------------------------------------------------------
def ensure_schema():
    """Create and REGISTER this worker's own warehouse objects.

    PLATFORM FACT (verified on a live account): dbconn.insert/fetch only work
    on tables that are registered in Peliqan's catalog. Raw DDL via
    dbconn.execute creates the Postgres object but does NOT register it, so
    insert/fetch return 404 ERROR_TABLE_DOES_NOT_EXIST while DDL "succeeds".
    pq.refresh_schema(connection_name=..., schema_name=...) runs a synchronous
    catalog sync that registers everything in the schema, but only for a
    schema the catalog already knows: register LINK_SCHEMA once with the MCP
    create_schema tool before the first run (worker-build.md, step 3).
    Do NOT create the link table with dbconn.write(): a write-created table is
    pipeline-flagged and dbconn.insert is REJECTED on it ("not allowed for a
    table that is part of a pipeline").

    Order: (1) idempotent DDL  (2) probe the tables once via a real fetch
    (3) if unregistered, refresh_schema and re-probe only if it ran
    (4) still unregistered -> RAISE. process_all treats that as fatal and runs
    no syncs: running syncs that write to the target while unable to record
    link rows is the silent-loss mode this guards against (duplicate target
    records + advanced bookmarks, with a green-looking run)."""
    v_shop = f"v_link_shopify_latest_{PAIR}"
    v_odoo = f"v_link_odoo_latest_{PAIR}"
    v_dead = f"v_dead_letter_{PAIR}"
    v_runs = f"v_run_summary_{PAIR}"
    stmts = [
        f"CREATE SCHEMA IF NOT EXISTS {LINK_SCHEMA}",
        f"""CREATE TABLE IF NOT EXISTS {_LT} (
               id bigint PRIMARY KEY, sync_name text, action text, status text,
               attempt int DEFAULT 0, shopify_id text, odoo_id text,
               shopify_source_hash text, odoo_source_hash text,
               shopify_source_json text, odoo_source_json text,
               error_detail text, timestamp text )""",
        # migrations for a table made before these columns existed
        f"ALTER TABLE {_LT} ADD COLUMN IF NOT EXISTS attempt int DEFAULT 0",
        f"ALTER TABLE {_LT} ADD COLUMN IF NOT EXISTS error_detail text",
        # run log
        f"""CREATE TABLE IF NOT EXISTS {LINK_SCHEMA}.{RUNS_TABLE} (
               id bigint PRIMARY KEY, sync_name text, started_at text, ended_at text,
               processed int, errors int, skipped int, status text, detail text )""",
        # monitor views (ops-facing; queryable without code), per pair
        f"""CREATE OR REPLACE VIEW {LINK_SCHEMA}.{v_shop} AS
           SELECT DISTINCT ON (sync_name, shopify_id) *
           FROM {_LT} WHERE shopify_id IS NOT NULL
           ORDER BY sync_name, shopify_id, timestamp DESC""",
        f"""CREATE OR REPLACE VIEW {LINK_SCHEMA}.{v_odoo} AS
           SELECT DISTINCT ON (sync_name, odoo_id) *
           FROM {_LT} WHERE odoo_id IS NOT NULL
           ORDER BY sync_name, odoo_id, timestamp DESC""",
        f"""CREATE OR REPLACE VIEW {LINK_SCHEMA}.{v_dead} AS
           SELECT * FROM {LINK_SCHEMA}.{v_shop} WHERE status <> 'ok'
           UNION ALL
           SELECT * FROM {LINK_SCHEMA}.{v_odoo}
           WHERE status <> 'ok' AND shopify_id IS NULL""",
        f"""CREATE OR REPLACE VIEW {LINK_SCHEMA}.{v_runs} AS
           SELECT sync_name, left(started_at, 10) AS day,
                  count(*) AS runs, sum(processed) AS processed,
                  sum(errors) AS errors, sum(skipped) AS skipped
           FROM {LINK_SCHEMA}.{RUNS_TABLE}
           GROUP BY sync_name, left(started_at, 10)""",
    ]
    for stmt in stmts:
        try:
            dbconn.execute(dw_name, query=stmt)
        except Exception as e:
            st.info(f"ensure_schema (DDL): {e}")

    # --- registration check + repair (the part raw DDL does not do) ---
    def _registered(table):
        try:
            # deliberately NOT the swallow-errors fetch() helper: we need the failure
            dbconn.fetch(dw_name, query=f"SELECT 1 FROM {LINK_SCHEMA}.{table} LIMIT 1")
            return True
        except Exception:
            return False

    missing = [t for t in (LINK_TABLE, RUNS_TABLE) if not _registered(t)]
    if missing:
        st.info("warehouse objects not registered in the Peliqan catalog yet; "
                "running pq.refresh_schema (synchronous)")
        try:
            pq.refresh_schema(connection_name=dw_name, schema_name=LINK_SCHEMA)
            missing = [t for t in missing if not _registered(t)]
        except Exception as e:
            st.warning(f"refresh_schema failed: {e}")
    if missing:
        raise RuntimeError(
            f"ensure_schema: {LINK_SCHEMA}.{' and '.join(missing)} exist(s) in Postgres but "
            f"remain(s) unregistered in the Peliqan catalog. If refresh_schema returned "
            f"ERROR_SCHEMA_DOES_NOT_EXIST, register schema {LINK_SCHEMA} once with the MCP "
            f"create_schema tool. Aborting the run: without a usable link table, syncs would "
            f"write to the target with no link rows (duplicates) while looking green.")


# ------------------------------------------------------------
# State helpers (bookmarks). State writes shallow-merge at the top level:
# always write the full "bookmarks" object, never a single key.
# ------------------------------------------------------------
def _get_state():
    try:
        state = pq.get_state()
    except Exception:
        return {}
    return state if isinstance(state, dict) else {}


def get_bookmark(sync_name):
    return _get_state().get("bookmarks", {}).get(sync_name)


def set_bookmark(sync_name, bookmark):
    try:
        state = _get_state()
        bookmarks = state.get("bookmarks", {})
        bookmarks[sync_name] = bookmark
        state["bookmarks"] = bookmarks
        pq.set_state(state)
    except Exception as e:
        st.warning(f"Could not persist bookmark for {sync_name}: {e}")


# ------------------------------------------------------------
# Bookmark math (PURE - no I/O - the single source of truth).
# scripts/test_bookmarks.py exec's these four; keep their signatures.
# ------------------------------------------------------------
def sort_by_updated_at(records, ts_field="updatedAt"):
    """Oldest-first. Records without the timestamp sort last (never advance)."""
    return sorted(records, key=lambda r: str(r.get(ts_field) or "9999"))


def bookmark_with_overlap(bookmark, fmt="%Y-%m-%dT%H:%M:%SZ", seconds=1):
    """v4 (contract §6): rewind a bookmark by `seconds` for fetch paths whose
    comparator strictness we do NOT control (e.g. a connector list(bookmark=...)).
    Where we write the filter ourselves, use >= directly instead. Idempotency
    (hash-skip / already-linked) makes the overlap re-reads no-ops."""
    try:
        from datetime import datetime, timedelta
        dt = datetime.strptime(str(bookmark), fmt)
        return (dt - timedelta(seconds=seconds)).strftime(fmt)
    except Exception:
        return bookmark


def advance_bookmark(high_water, ts):
    if ts and str(ts) > str(high_water):
        return str(ts)
    return high_water


def simulate_bookmark_run(records, current_bookmark, limit, ts_field="updatedAt"):
    """Pure preview of where the bookmark lands. Mirrors the real loop minus
    the writeback; what the bookmark tests assert."""
    high_water, processed = current_bookmark, 0
    for r in sort_by_updated_at(records, ts_field):
        if limit and processed >= limit:
            break
        processed += 1
        high_water = advance_bookmark(high_water, r.get(ts_field))
    return high_water, processed


# ------------------------------------------------------------
# Hashing  (stable across field boundaries and None/'': use this, not
# ad-hoc str concatenation)
# ------------------------------------------------------------
def stable_hash(mapped):
    """md5 over canonical JSON of the OWNED/mapped fields. Pass a dict of the
    fields that define change for this direction; key order does not matter."""
    canonical = json.dumps(mapped, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.md5(canonical.encode()).hexdigest()


# ------------------------------------------------------------
# SQL helpers
# ------------------------------------------------------------
def _sql(value):
    return str(value).replace("'", "''")


def fetch(query):
    try:
        return dbconn.fetch(dw_name, query=query) or []
    except Exception as e:
        st.info(f"Query failed: {e}")
        return []


# ------------------------------------------------------------
# Link table helpers (append-only, with attempt/dead) + per-run link cache
# ------------------------------------------------------------
_last_link_id = 0


def _next_link_id():
    # Monotonic guard: a colliding bigint PK drops a link row silently, and
    # time.time_ns() alone is not safe against clock adjustments.
    global _last_link_id
    candidate = int(time.time() * 1_000_000)
    if candidate <= _last_link_id:
        candidate = _last_link_id + 1
    _last_link_id = candidate
    return candidate


def _err(detail, limit=4000):
    if detail is None:
        return None
    try:
        text = detail if isinstance(detail, str) else json.dumps(detail, default=str)
    except Exception:
        text = str(detail)
    return text[:limit]


def _last_attempt(sync_name, shopify_id=None, odoo_id=None):
    key = "shopify_id" if shopify_id is not None else "odoo_id"
    val = shopify_id if shopify_id is not None else odoo_id
    if val is None:
        return 0
    rows = fetch(f"""
        SELECT attempt FROM {_LT}
        WHERE sync_name = '{_sql(sync_name)}' AND {key} = '{_sql(val)}'
        ORDER BY timestamp DESC, id DESC LIMIT 1
    """)
    try:
        return int(rows[0]["attempt"]) if rows and rows[0].get("attempt") is not None else 0
    except Exception:
        return 0


# Link cache: (sync_name, side) -> {id: (other_id, hash)}, mirroring "the
# latest ok row" for that id. prefetch_links fills it one page at a time,
# find_* read it first and fall back to a query for keys never prefetched,
# and insert_link_row writes ok rows through, so a child sync sees a parent
# link written earlier in the SAME run (correctness, not just speed).
_link_cache = {}
_SIDES = {   # side: (key column, other id column, hash column)
    "shopify": ("shopify_id", "odoo_id", "shopify_source_hash"),
    "odoo": ("odoo_id", "shopify_id", "odoo_source_hash"),
}


def prefetch_links(sync_name, side, keys, chunk=500):
    """Load the latest ok link for these keys in one query per `chunk`.
    Call it once per page of source records, for this sync AND for every
    parent sync the loop resolves. Misses are cached as (None, None), so
    "in the cache" means "we know". A failed query caches nothing: find_*
    then falls back to per-key lookups instead of treating linked records
    as new (which would duplicate them)."""
    key_col, other_col, hash_col = _SIDES[side]
    cache = _link_cache.setdefault((sync_name, side), {})
    todo = sorted({str(k) for k in keys if k is not None} - set(cache))
    for i in range(0, len(todo), chunk):
        part = todo[i:i + chunk]
        in_list = ",".join(f"'{_sql(k)}'" for k in part)
        try:
            rows = dbconn.fetch(dw_name, query=f"""
                SELECT DISTINCT ON ({key_col}) {key_col} AS k, {other_col} AS other, {hash_col} AS h
                FROM {_LT}
                WHERE sync_name = '{_sql(sync_name)}' AND status = 'ok' AND {key_col} IN ({in_list})
                ORDER BY {key_col}, timestamp DESC, id DESC
            """) or []
        except Exception as e:
            st.info(f"prefetch_links {sync_name}/{side}: {e}")
            continue
        for k in part:
            cache[k] = (None, None)
        for r in rows:
            cache[str(r["k"])] = (r["other"], r["h"])


def _find_link(sync_name, side, key):
    if key is None:
        return None, None
    cache = _link_cache.setdefault((sync_name, side), {})
    if str(key) in cache:
        return cache[str(key)]
    key_col, other_col, hash_col = _SIDES[side]
    rows = fetch(f"""
        SELECT {other_col} AS other, {hash_col} AS h FROM {_LT}
        WHERE sync_name = '{_sql(sync_name)}' AND {key_col} = '{_sql(key)}' AND status = 'ok'
        ORDER BY timestamp DESC, id DESC LIMIT 1
    """)
    if not rows:
        return None, None   # not cached: fetch() hides query failures
    cache[str(key)] = (rows[0]["other"], rows[0]["h"])
    return cache[str(key)]


def find_target(sync_name, shopify_id):
    """Most recent ok link for a Shopify-driven sync -> (odoo_id, shopify_source_hash)."""
    return _find_link(sync_name, "shopify", shopify_id)


def find_link_by_odoo(sync_name, odoo_id):
    """Most recent ok link keyed by odoo_id -> (shopify_id, odoo_source_hash)."""
    return _find_link(sync_name, "odoo", odoo_id)


def insert_link_row(sync_name, action, status, shopify_id=None, odoo_id=None,
                    shopify_source_hash=None, odoo_source_hash=None,
                    shopify_source_json=None, odoo_source_json=None, error_detail=None):
    # Attempt counting + poison promotion happen here so every sync gets DLQ
    # behaviour for free. ok rows reset attempt to 0.
    if status in ERROR_STATUSES:
        attempt = _last_attempt(sync_name, shopify_id, odoo_id) + 1
        if attempt >= MAX_ATTEMPTS:
            status = "dead"
    else:
        attempt = 0
    sid = str(shopify_id) if shopify_id is not None else None
    oid = str(odoo_id) if odoo_id is not None else None

    def _row():
        row = {
            "id": _next_link_id(), "sync_name": sync_name, "action": action,
            "status": status, "attempt": attempt, "shopify_id": sid, "odoo_id": oid,
            "shopify_source_hash": shopify_source_hash,
            "odoo_source_hash": odoo_source_hash,
            "shopify_source_json": json.dumps(shopify_source_json, default=str) if shopify_source_json is not None else None,
            "odoo_source_json": json.dumps(odoo_source_json, default=str) if odoo_source_json is not None else None,
            "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if error_detail is not None:
            row["error_detail"] = _err(error_detail)
        return row

    # The 3x retry and the error-row fallback STAY: a target write that
    # succeeded with no link row is the silent duplicate this framework
    # exists to prevent.
    last_err = None
    for _ in range(3):
        try:
            dbconn.insert(dw_name, LINK_SCHEMA, LINK_TABLE, _row())
            if status == "ok":   # write-through, same semantics as "latest ok row"
                if sid is not None:
                    _link_cache.setdefault((sync_name, "shopify"), {})[sid] = (oid, shopify_source_hash)
                if oid is not None:
                    _link_cache.setdefault((sync_name, "odoo"), {})[oid] = (sid, odoo_source_hash)
            return True
        except Exception as e:
            last_err = e
            time.sleep(0.01)
    # never drop an error row over an optional column
    if error_detail is not None:
        try:
            row = _row(); row.pop("error_detail", None)
            dbconn.insert(dw_name, LINK_SCHEMA, LINK_TABLE, row)
            st.warning(f"Wrote link row without error_detail ({sync_name}/{status}): {last_err}")
            return True
        except Exception as e:
            last_err = e
    st.warning(f"Could not write link row ({sync_name}/{status}): {last_err}")
    return False


# ------------------------------------------------------------
# Skips are counted, not logged per record: one line per sync and reason
# after the sync. Keep the default reason text: "no change in hash -> skip"
# is the idempotence proof in the log.
# ------------------------------------------------------------
_skips = {}   # sync_name -> {reason: n}


def note_skip(sync_name, reason="no change in hash -> skip"):
    per_sync = _skips.setdefault(sync_name, {})
    per_sync[reason] = per_sync.get(reason, 0) + 1


def write_skips():
    """Called by process_all after every sync, also when it failed. Flushes
    every pending count, including fan-out child syncs."""
    for name in sorted(_skips):
        for reason, n in sorted(_skips[name].items()):
            st.text(f"{name}: {n} x {reason}")
    _skips.clear()


# ------------------------------------------------------------
# Run log
# ------------------------------------------------------------
def record_run(sync_name, started_at, counts, status="ok", detail=""):
    counts = counts or {}
    try:
        dbconn.insert(dw_name, LINK_SCHEMA, RUNS_TABLE, {
            "id": _next_link_id(), "sync_name": sync_name,
            "started_at": started_at,
            "ended_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "processed": int(counts.get("processed", 0)),
            "errors": int(counts.get("errors", 0)),
            "skipped": int(counts.get("skipped", 0)),
            "status": status, "detail": _err(detail) or "",
        })
    except Exception as e:
        st.info(f"record_run: {e}")


# ------------------------------------------------------------
# Replay: re-drive error/dead rows from the stored source snapshot, once the
# cause is fixed. The normal run does NOT retry an error row whose source
# record has not changed (the bookmark has moved past it); this does.
# process_one must accept (sync_name, source_record). Fan-out syncs that
# need resolved parent context register an adapter, or no replay at all and
# are reprocessed by a bookmark rewind instead.
# ------------------------------------------------------------
def replay_source(sync_name, process_one, statuses=("target_error",),
                  include_dead=False, limit=500):
    wanted = list(statuses) + (["dead"] if include_dead else [])
    in_list = ",".join(f"'{s}'" for s in wanted)
    rows = fetch(f"""
        SELECT shopify_source_json, odoo_source_json FROM (
            SELECT DISTINCT ON (sync_name, shopify_id, odoo_id) *
            FROM {_LT} WHERE sync_name = '{_sql(sync_name)}'
            ORDER BY sync_name, shopify_id, odoo_id, timestamp DESC, id DESC
        ) latest WHERE status IN ({in_list}) LIMIT {int(limit)}
    """)
    replayed = 0
    for r in rows:
        raw = r.get("shopify_source_json") or r.get("odoo_source_json")
        if not raw:
            continue
        try:
            record = json.loads(raw) if isinstance(raw, str) else raw
            process_one(sync_name, record)
            replayed += 1
        except Exception as e:
            st.warning(f"replay {sync_name}: {e}")
    st.write(f"replayed {replayed} record(s) for {sync_name}")
    return replayed


# ------------------------------------------------------------
# Response check (both systems)
# ------------------------------------------------------------
def is_ok(result):
    """status == success AND no functional error travelling inside the 200:
    Odoo V2 puts `detail.error` (result null), Shopify puts top-level
    `detail.errors` (ACCESS_DENIED, data null). Without this check a broken
    read looks like "0 records" and the run stays green."""
    if not (isinstance(result, dict) and result.get("status") == "success"):
        return False
    detail = result.get("detail")
    return not (isinstance(detail, dict) and (detail.get("error") or detail.get("errors")))


# ------------------------------------------------------------
# Shopify transport (single-line queries, 1 record per call)
# ------------------------------------------------------------
def gid_to_numeric(gid):
    if gid is None:
        return None
    return str(gid).rsplit("/", 1)[-1]


def shopify_graphql(query, variables=None):
    single_line = " ".join(query.split())  # the edge rejects multi-line queries
    return shopify_api.apicall(path="graphql.json", query=single_line, variables=variables or {})


def graphql_user_errors(result, mutation_name):
    detail = result.get("detail", {}) if isinstance(result, dict) else {}
    data = detail.get("data", {}) or {}
    payload = data.get(mutation_name, {}) or {}
    return payload.get("userErrors", []) or []


def shopify_drain(query, root, bookmark, extra_filter="", page_size=100, max_pages=200):
    """Every <root> node with updated_at >= bookmark (contract §6), all pages.
    `query` declares ($first: Int!, $cursor: String, $q: String) and selects
    <root>(first: $first, after: $cursor, query: $q) { edges { node { ... } }
    pageInfo { hasNextPage endCursor } }; `extra_filter` is ANDed to the
    search query. Returns a list: cursor order is not updatedAt order, so the
    caller sorts (sort_by_updated_at) before the loop.
    RAISES (a loud source_error, the sync is reported failed and its bookmark
    stays put) on a response that is not ok, including a 200 with top-level
    errors and data: null (ACCESS_DENIED), and on hitting max_pages: a
    truncated, unsorted read would let the bookmark skip unread records."""
    q = f"updated_at:>='{bookmark}'" + (f" AND {extra_filter}" if extra_filter else "")
    nodes, cursor = [], None
    for _ in range(max_pages):
        result = shopify_graphql(query, {"first": page_size, "cursor": cursor, "q": q})
        if not is_ok(result):
            raise RuntimeError(f"source_error: Shopify {root} read failed: {_err(result, 1000)}")
        block = ((result.get("detail") or {}).get("data") or {}).get(root) or {}
        nodes.extend(e["node"] for e in (block.get("edges") or []) if e.get("node"))
        page_info = block.get("pageInfo") or {}
        if not page_info.get("hasNextPage") or not page_info.get("endCursor"):
            return nodes
        cursor = page_info["endCursor"]
    raise RuntimeError(f"source_error: shopify_drain({root}) hit max_pages={max_pages} "
                       f"({len(nodes)} records); raise max_pages or narrow extra_filter")


# ------------------------------------------------------------
# Odoo transport (generic 'object' endpoint + search_read via apicall)
# ------------------------------------------------------------
def odoo_object_add(model, record):
    return odoo_api.add("object", {"model": model, "payload": [record], "additional_params": {}})


def odoo_object_update(model, target_id, record):
    return odoo_api.update("object", {"model": model, "payload": [[int(target_id)], record], "additional_params": {}})


def odoo_object_search(model, domain, fields):
    result = odoo_api.get("object", {"model": model, "payload": [domain], "additional_params": {"fields": fields}})
    if isinstance(result, dict):
        result = [result]
    return result or []


def _odoo_error(resp):
    """`detail.error.data` name + message of an Odoo fault, else the raw response."""
    detail = resp.get("detail") if isinstance(resp, dict) else None
    err = detail.get("error") if isinstance(detail, dict) else None
    data = err.get("data") if isinstance(err, dict) else None
    if isinstance(data, dict):
        return f"{data.get('name', '')}: {data.get('message', '')}"
    return _err(resp, 1000)


def odoo_search_read_incremental(model, fields, bookmark, page_size=100):
    """Drain an Odoo model via search_read: write_date >= bookmark, oldest-first,
    offset-paged until empty. Odoo write_date is 'YYYY-MM-DD HH:MM:SS'; keep its
    bookmark SEPARATE from Shopify's. Pages arrive in write_date order, so
    prefetch_links per page. RAISES on a response that is not ok (an Odoo
    fault arrives inside a 200), so a broken read never looks like "0 records"."""
    page = 0
    while True:
        resp = odoo_api.apicall("", odoo_model=model, odoo_method="search_read",
                                payload=[[["write_date", ">=", bookmark]]],  # v4: >= not > (contract §6)
                                additional_params={"limit": page_size, "offset": page * page_size,
                                                   "order": "write_date asc", "fields": fields})
        if not is_ok(resp):
            raise RuntimeError(f"source_error: Odoo search_read({model}) page {page}: {_odoo_error(resp)}")
        rows = (resp.get("detail") or {}).get("result") or []
        if isinstance(rows, dict):
            rows = [rows]
        if not rows:
            return
        yield rows
        page += 1


def find_or_create(model, domain, record, cache, key, strict=False):
    """Odoo id for a supporting record (a partner, a tax, a UoM...): from
    `cache[key]`, else the first search_read match on `domain`, else created
    from `record`. strict=True RAISES when it cannot be resolved (use it where
    the write cannot proceed without the id); strict=False warns and caches
    None, so a lookup that fails is not retried for every record. A failed
    search never falls through to a create."""
    if key in cache:
        return cache[key]
    found, problem = None, None
    try:
        resp = odoo_api.apicall("", odoo_model=model, odoo_method="search_read", payload=[domain],
                                additional_params={"fields": ["id"], "limit": 1})
        if not is_ok(resp):
            problem = f"search failed: {_odoo_error(resp)}"
        else:
            rows = (resp.get("detail") or {}).get("result") or []
            rows = [rows] if isinstance(rows, dict) else rows
            if rows:
                found = rows[0].get("id")
            else:
                created = odoo_object_add(model, record)
                if is_ok(created):
                    found = extract_new_id(created)
                else:
                    problem = f"create failed: {_odoo_error(created)}"
    except Exception as e:
        problem = f"{e}"
    if found is None:
        problem = problem or "no id returned"
        if strict:
            raise RuntimeError(f"find_or_create {model} [{key}]: {problem}")
        st.warning(f"find_or_create {model} [{key}]: {problem}; cached as None for this run")
    cache[key] = found
    return found


def extract_new_id(result):
    if not isinstance(result, dict):
        return None
    detail = result.get("detail")
    if isinstance(detail, dict):
        return detail.get("result") or detail.get("id")
    return detail


# ============================================================
# >>> SYNC INSERTION POINT <<<
# The sync-builder appends each sync's trio here and registers it in
# SYNC_REGISTRY below. A process_<sync> loop should RETURN a counts dict
# {"processed": n, "errors": e, "skipped": s} so the run log is populated.
# ============================================================


# ------------------------------------------------------------
# Registry + run loop. Each entry: {"name", "run", "replay"?}.
# Order = dependency order (parents first; Shopify->Odoo before Odoo->Shopify).
# ------------------------------------------------------------
SYNC_REGISTRY = [
    # {"name": SYNC_X, "run": process_x, "replay": process_one_x},
]


def process_all():
    # Schema failure is FATAL: no sync may run if link rows cannot be recorded.
    try:
        ensure_schema()
    except Exception as e:
        st.error(f"ABORTING RUN - warehouse schema not usable: {e}")
        st.text(traceback.format_exc())
        return
    on = [e["name"] for e in SYNC_REGISTRY if SYNCS_ENABLED.get(e["name"], True)]
    off = [e["name"] for e in SYNC_REGISTRY if e["name"] not in on]
    st.caption(f"syncs on: {', '.join(on) or 'none'} | off: {', '.join(off) or '-'}")
    before = dict(_get_state().get("bookmarks", {}))

    # every summary tuple has the SAME arity: a shorter one on the disabled
    # branch crashed a live run with a ValueError ("Worker aborted unexpectedly")
    summary = []   # (name, status, seconds, counts, detail)
    for entry in SYNC_REGISTRY:
        label, run = entry["name"], entry["run"]
        if label in off:
            summary.append((label, "off", 0.0, {}, ""))
            continue
        st.header(label)
        started, t0 = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), time.time()
        try:
            counts = run() or {}
            record_run(label, started, counts, status="ok")
            summary.append((label, "ok", time.time() - t0, counts, ""))
        except Exception as e:
            st.error(f"Sync {label} failed but the run continues: {e}")
            st.text(traceback.format_exc())
            record_run(label, started, {}, status="failed", detail=f"{e}")
            summary.append((label, "failed", time.time() - t0, {}, f"{e}"))
        finally:
            write_skips()

    # The Bookmarks block answers an incident: "unchanged" means nothing new
    # upstream OR frozen on an orphan, and nothing else tells those apart.
    after = _get_state().get("bookmarks", {})
    names = [s[0] for s in summary] + sorted(set(after) - {s[0] for s in summary})
    width = max((len(n) for n in names), default=0)
    st.header("Run summary")
    for label, status, seconds, c, detail in summary:
        line = (f"[{status.upper()}] {label:<{width}}  {seconds:6.1f}s  "
                f"processed {c.get('processed', 0)}  errors {c.get('errors', 0)}  "
                f"skipped {c.get('skipped', 0)}" + (f"  - {detail}" if detail else ""))
        if status == "ok":
            (st.warning if c.get("errors") else st.success)(line)
        else:
            (st.info if status == "off" else st.error)(line)
    st.subheader("Bookmarks")
    for name in names:
        b, a = before.get(name), after.get(name)
        st.text(f"{name:<{width}}  " + (f"{b} -> {a}" if a != b else "unchanged"))


try:
    process_all()
except Exception as e:
    # Absolute last-resort guard: the Worker must never end on an
    # unhandled exception.
    st.error(f"Worker aborted unexpectedly: {e}")
    st.text(traceback.format_exc())
