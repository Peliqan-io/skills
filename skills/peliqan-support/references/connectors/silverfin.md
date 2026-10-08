# Silverfin

- `server_type`: as `list_connections` shows it (it starts with `silverfin`).
- Tables: `balances`.

## silverfin_balances_collapsed

Balances exist per company and per period. If every company has only one
period in `balances`, the rows overwrite each other across periods (a key
collision), and the customer sees a dossier stuck on an old year.

- Severity: CRITICAL
- SQL:

  ```sql
  SELECT companies, max_periods FROM (
    SELECT COUNT(*) AS companies, MAX(periods) AS max_periods
    FROM (SELECT company_id, COUNT(DISTINCT period_id) AS periods
          FROM {t[balances]}
          WHERE _sdc_deleted_at IS NULL
          GROUP BY company_id) pc) x
  WHERE companies > 0 AND max_periods <= 1
  ```

| Confirm | First step | AI may | Don't | Fixed when |
|---|---|---|---|---|
| Periods per company in `balances` against the periods table | Report to Peliqan: balance rows overwrite each other across periods. A full refresh of every Silverfin connection follows the fix | draft | Resync before the fix: same result | Periods per company in `balances` match the periods table |
