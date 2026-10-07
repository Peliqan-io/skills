# ============================================================
# EXAMPLES (v6): a DWH-sourced sync loop + a per-sync audit function
# ============================================================
# Both are for sync 1 (shopify products -> odoo product.template) and REUSE
# its fieldmapping_* and process_<one record> from product_syncs.py verbatim.
# Nothing here is new framework: dwh_drain, record_audit, prefetch_links and
# the link views already exist in the worker template.
#
# Sync header comment the DWH variant must carry (what support reads first):
#   source channel : DWH pipeline table shopify.products  (not the API)
#   ts_field       : updated_at  as text 'YYYY-MM-DDTHH:MM:SSZ'   (probed 3 rows)
#   id_field       : id  (numeric shopify id, no gid)
#   pipeline       : hourly -> overlap 3600 s (bookmark_with_overlap)
#   pipeline filter: none (all statuses loaded)
#   children       : none for this sync (variants have their own sync)
#
# Constants (declared near the other SYNC_* names):
#   SYNC_TEMPLATES = "shopify_products_to_odoo_product_templates"
#   PRODUCTS_TABLE = "shopify.products"      # the pipeline table
#   PIPELINE_INTERVAL_S = 3600               # one pipeline run; drives the overlap


# ============================================================
# SYNC 1-DWH: same sync, source read from the pipeline table
# ============================================================
def dwh_row_to_shopify_product(row):
    """Normalise a flat pipeline row to the API shape sync 1 already handles.
    THIS is what keeps the hash stable across channels: fieldmapping_* sees the
    same dict whether the record came from GraphQL or from the DWH, so
    switching a sync from API to DWH re-drives NOTHING (every record settles
    as 'no change in hash -> skip'). Column names are per-table - probe them."""
    return {
        "id": f"gid://shopify/Product/{row.get('id')}",   # sync 1 strips it again via gid_to_numeric
        "title": row.get("title"),
        "descriptionHtml": row.get("body_html"),
        "status": str(row.get("status") or "").upper(),   # pipeline stores 'active', API 'ACTIVE'
        "updatedAt": row.get("updated_at"),
    }


def process_shopify_products_to_odoo_product_templates_dwh():
    sync_name = SYNC_TEMPLATES
    bookmark = get_bookmark(sync_name) or "2020-01-01T00:00:00Z"   # the TABLE's format
    st.write(f"Sync: {sync_name} | bookmark: {bookmark} | source: {PRODUCTS_TABLE}")

    c = {"processed": 0, "errors": 0, "skipped": 0}
    high_water, limit_hit = bookmark, False
    # pipeline lag: drain from one pipeline interval before the bookmark (peliqan-dwh.md)
    drain_from = bookmark_with_overlap(bookmark, fmt="%Y-%m-%dT%H:%M:%SZ", seconds=PIPELINE_INTERVAL_S)
    for rows in dwh_drain(PRODUCTS_TABLE, "updated_at", drain_from, id_field="id"):
        prefetch_links(sync_name, "shopify", [str(r.get("id")) for r in rows])   # per page
        for row in rows:
            if _limit_reached(c["processed"]):
                st.info("TEST_LIMIT reached"); limit_hit = True; break
            p = dwh_row_to_shopify_product(row)
            try:
                outcome = process_shopify_product_to_odoo_product_template(sync_name, p)
            except Exception as e:
                st.error(f"Unexpected error; recorded and continuing: {e}")
                insert_link_row(sync_name, "insert", "source_error",
                                shopify_id=str(row.get("id")), shopify_source_json=p, error_detail=e)
                outcome = "error"
            if outcome == "error":
                c["errors"] += 1
            elif outcome == "skip":
                c["skipped"] += 1
            c["processed"] += 1
            high_water = advance_bookmark(high_water, p.get("updatedAt"))
        if limit_hit:
            break

    if str(high_water) > str(bookmark):
        set_bookmark(sync_name, high_water)
    st.write(f"New bookmark: {high_water} | {c}")
    return c


# ============================================================
# AUDIT for sync 1: coverage (missing) + drift + orphans. READ-ONLY.
# ============================================================
def audit_shopify_products_to_odoo_product_templates():
    """Returns {check: n}; per-record findings go through record_audit.
    No insert_link_row, no set_bookmark, no target write anywhere in here."""
    sync_name = SYNC_TEMPLATES
    v_latest = f"{LINK_SCHEMA}.v_link_shopify_latest_{PAIR}"
    counts = {}

    # 1. coverage: source rows with no ok link - one SQL, because the source is
    #    a pipeline table. Scope = the sync's scope (sync 1 pushes every status).
    missing = fetch(f"""
        SELECT s.id, s.title FROM {PRODUCTS_TABLE} s
        LEFT JOIN {v_latest} l
               ON l.sync_name = '{_sql(sync_name)}' AND l.shopify_id = s.id::text AND l.status = 'ok'
        WHERE l.shopify_id IS NULL
        ORDER BY s.updated_at DESC LIMIT {int(AUDIT_LIMIT)}
    """)
    for r in missing:
        record_audit(sync_name, "missing", shopify_id=r.get("id"), detail=r.get("title"))
    counts["missing"] = len(missing)

    # 2. drift: newest AUDIT_LIMIT ok links -> current source row + current
    #    target record -> the sync's OWN mapping -> compare mapped fields only.
    links = fetch(f"""
        SELECT shopify_id, odoo_id FROM {v_latest}
        WHERE sync_name = '{_sql(sync_name)}' AND status = 'ok'
        ORDER BY timestamp DESC LIMIT {int(AUDIT_LIMIT)}
    """)
    if links:
        ids = ",".join(_sql(l["shopify_id"]) for l in links)
        source = {str(r["id"]): r for r in fetch(f"SELECT * FROM {PRODUCTS_TABLE} WHERE id IN ({ids})")}
        odoo_ids = [int(l["odoo_id"]) for l in links if l.get("odoo_id")]
        target = {}
        for i in range(0, len(odoo_ids), 200):   # batch read, one call per 200 (search, not search_read)
            for t in odoo_object_search("product.template", [["id", "in", odoo_ids[i:i + 200]],
                                                             ["active", "in", [True, False]]],
                                        ["id", "name", "description_sale", "active", "sale_ok"]):
                target[str(t.get("id"))] = t
        drift = 0
        for l in links:
            row, t = source.get(str(l["shopify_id"])), target.get(str(l["odoo_id"]))
            if row is None or t is None:
                continue   # gone on one side: that is coverage/orphan territory, not drift
            mapped, _ = fieldmapping_shopify_product_to_odoo_product_template(dwh_row_to_shopify_product(row))
            diff = {k: (t.get(k), v) for k, v in mapped.items() if t.get(k) != v}
            if diff:
                drift += 1
                record_audit(sync_name, "drift", shopify_id=l["shopify_id"], odoo_id=l["odoo_id"], detail=diff)
        counts["drift"] = drift

    # 3. orphans: ok links whose source row is gone. Only meaningful if the
    #    pipeline REMOVES deleted products (peliqan-dwh.md) - here it does.
    #    One SQL; recorded, never deleted.
    orphans = fetch(f"""
        SELECT l.shopify_id, l.odoo_id FROM {v_latest} l
        LEFT JOIN {PRODUCTS_TABLE} s ON s.id::text = l.shopify_id
        WHERE l.sync_name = '{_sql(sync_name)}' AND l.status = 'ok' AND s.id IS NULL
        LIMIT {int(AUDIT_LIMIT)}
    """)
    for r in orphans:
        record_audit(sync_name, "orphan", shopify_id=r.get("shopify_id"), odoo_id=r.get("odoo_id"))
    counts["orphan"] = len(orphans)
    return counts


# --- SYNC_REGISTRY entry (replaces sync 1's tuple when the DWH is the source) ---
#   {"name": SYNC_TEMPLATES, "run": process_shopify_products_to_odoo_product_templates_dwh,
#    "replay": process_shopify_product_to_odoo_product_template,
#    "audit": audit_shopify_products_to_odoo_product_templates},
