# Horus

- `server_type`: as `list_connections` shows it (it starts with `horus`).
- Tables: `account_histories`.
- The connector sends the full ledger on every run. A row that wasn't
  received in the latest run is gone at the source. If it is still live in
  the warehouse, it is an orphan: a superseded or deleted line that is still
  counted.

## horus_orphan_rows

- Severity: CRITICAL
- SQL:

  ```sql
  SELECT orphaned FROM (
    SELECT COUNT(*) AS orphaned
    FROM {t[account_histories]}
    WHERE _sdc_deleted_at IS NULL
      AND CAST(_sdc_received_at AS DATE) <
          (SELECT CAST(MAX(_sdc_received_at) AS DATE)
           FROM {t[account_histories]} WHERE _sdc_deleted_at IS NULL)) x
  WHERE orphaned > 0
  ```

| Confirm | First step | AI may | Don't | Fixed when |
|---|---|---|---|---|
| The orphaned count against the total, and the date of the latest full run | Report to Peliqan: rows missing from the latest snapshot are not marked deleted. In the meantime, a view that keeps only rows from the latest snapshot date | draft (report), do (view) | Resync: it keeps the orphans | 0 orphaned rows |

## horus_entries_not_footing

Every journal entry's debit equals its credit.

- Severity: CRITICAL
- SQL:

  ```sql
  SELECT BookEntry_Id,
         ROUND(SUM(COALESCE(Debit, 0)) - SUM(COALESCE(Credit, 0)), 2) AS difference
  FROM {t[account_histories]}
  WHERE _sdc_deleted_at IS NULL AND COALESCE(IsReport, FALSE) = FALSE
  GROUP BY BookEntry_Id
  HAVING ABS(SUM(COALESCE(Debit, 0)) - SUM(COALESCE(Credit, 0))) > 0.005
  ```

| Confirm | First step | AI may | Don't | Fixed when |
|---|---|---|---|---|
| Run it again on rows from the latest snapshot date only. That second count is what the fix will deliver; a big gap between the two points at orphans | As `horus_orphan_rows` | draft | Resync | The count is down to the latest-snapshot number |

Orphan pairs that balance each other pass this check and still distort
turnover. `horus_orphan_rows` is the one that counts them.
