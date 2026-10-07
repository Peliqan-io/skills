# Sync workers: technical overview

Why you can trust a sync worker built with these skills: what your account needs, how the first run is staged, which risks the framework guards against, and how a worker is tested.

How a worker and a run work is explained in the [Syncs overview](README.md#3-how-it-works).

---

## 1. What your account needs

| Requirement | Why |
|---|---|
| **Connections with the exact names the worker uses** (as set in the worker) | The worker connects at start-up. A different name crashes the app before the first sync starts. |
| **Write access in the target system**, not just read access | Read-only access proves nothing about writes. If the worker creates custom fields in the target, that user must be allowed to. |
| **A warehouse the worker can write its state to** | The link table, run log and views are created there on the first run. The synced data itself doesn't have to be in the warehouse: the worker reads both sides through their APIs, unless a side is a warehouse table. |
| **The Peliqan MCP connected to Claude** | So the skills can inspect the account, deploy and read run logs. |

> **Verify custom fields after the first run.** If the worker creates custom fields and lacks the permission, the creation fails with only a warning, the run stays green and the mappings to those fields write nothing. Check that the fields exist after the first run.

---

## 2. The staged first run

A first run is a write to two live systems, so it is staged:

1. **`TEST_LIMIT` low (e.g. 5), one sync enabled** in `SYNCS_ENABLED`.
2. Check the link table and the target system: are the records right?
3. **Run again.** It must write nothing: only "no change in hash → skip" or "already linked". That is the idempotence proof.
4. Enable the next sync, one at a time.
5. Then lift `TEST_LIMIT` and schedule the worker. That step stays your decision.

---

## 3. Risks and the guards that catch them

Most rules here come from a real incident. A guard without a story behind it tends to get removed sooner or later.

| Risk | What goes wrong | Guard |
|---|---|---|
| **Unregistered link table** | Raw DDL creates the Postgres table without registering it in Peliqan's catalog. Writes to the target land, link rows don't: silent duplicates on every run, with a green run. | `ensure_schema` creates, registers and verifies the tables, and aborts the run if that fails. No sync runs on an unverified link table. |
| **Strict `>` bookmark** | An interrupted run sets the bookmark to a second that more records share. The rest of them are never picked up. | Incremental reads use `>=`. The re-read boundary records are absorbed by hash-skip. `test_bookmarks.py` proves it offline. |
| **Changing what a sync owns** | Adding a field to the hash changes the hash of every record, so the next run rewrites the whole catalogue in the target. | Treated as a deliberate re-drive: stated up front, with a procedure (reset bookmark, run, verify counts). |
| **Two apps on one pair name** | Two workers sharing one link table each see the other's hashes as changed, and rewrite everything. | One writer per pair. A sandbox copy gets its own `PAIR`, so its own link table and bookmarks. |
| **A failed read that looks empty** | Some APIs report a permission problem or a bad field inside a "successful" reply. Read naively, that is "0 changed records": the run stays green and nothing syncs. | Every read checks for an error inside the reply and fails the sync loudly. The bookmark stays put, so the sync catches up once the cause is fixed. |
| **Successful write, failed link row** | The target record exists but the link table doesn't know it: a duplicate on the next run. | Three retries on the link-row insert, plus an error-row fallback. |
| **Running the worker to "just try it"** | Every run writes to live systems. | Test with `TEST_LIMIT`, a sandbox copy or by reading the link table. The skills never run a worker against a live target unasked. |

---

## 4. QA: offline first, then live

| Layer | When | What it checks |
|---|---|---|
| **Offline checks** | Before every deploy | The script compiles and lints clean. `test_bookmarks.py` proves the bookmark rules. A simulated run against fake systems: run 1 creates, run 2 writes nothing, run 3 propagates exactly one change. |
| **Deploy check** | After every deploy | The deployed script is read back and compared with what was tested. |
| **Live, staged** | First run and after changes | The staged first run from §2, on realistic seeded test data (orders with discounts, shipping and deviating taxes, not one bare order line). |
| **Audit** | Before go-live, then periodically | `peliqan-audit`: scorecard against the framework rules and the run history. |

**What tests cannot guard:** write permissions in the target, whether the field mappings are right for *your* business, and the cost of a full re-drive. A matching deploy check proves the right code arrived, not that it runs. That's what the staged first run and the audit are for.
