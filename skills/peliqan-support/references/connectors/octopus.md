# Octopus

- `server_type`: as `list_connections` shows it (it starts with `octopus`).
- Tables: `bookings`.
- If a run fails on the first stream with `MissingKeyPropertiesError` and only
  an empty `dossiers` table exists, one record without a key (often a
  disabled dossier) stopped everything. As a stopgap, the customer
  re-enables or removes that dossier in Octopus. Report it to Peliqan too.

## octopus_ledger_imbalance

Every dossier's bookings net to zero. Dossiers that don't usually have a hole
in their history: the first full load ended early, and later runs only fetch
what changed since.

- Severity: CRITICAL
- SQL:

  ```sql
  SELECT dossier_id, ROUND(SUM(bookingAmount), 2) AS net
  FROM {t[bookings]}
  WHERE _sdc_deleted_at IS NULL
  GROUP BY dossier_id
  HAVING ABS(SUM(bookingAmount)) > 0.005
  ```

| Confirm | First step | AI may | Don't | Fixed when |
|---|---|---|---|---|
| The same sum per book year (`bookyearKey_id`) for one dossier: which years are short? | A full resync from the start: reset the bookmark and set the start date before the first book year | do, after a yes | Resync with a recent start date: the early years stay missing | At least 95 % of dossiers net to zero |

## octopus_purchase_cliff

Purchase-journal lines (`journalTypeId = 1`) spread over the periods. Three or
more periods far below the average mean the backfill never finished. The
accountant sees it as suppliers with a debit balance.

- Severity: WARNING
- SQL:

  ```sql
  SELECT period, lines, avg_lines FROM (
    SELECT period, lines, avg_lines, COUNT(*) OVER () AS thin_periods
    FROM (SELECT bookyearPeriodeNr AS period, COUNT(*) AS lines,
                 AVG(COUNT(*)) OVER () AS avg_lines
          FROM {t[bookings]}
          WHERE _sdc_deleted_at IS NULL AND journalTypeId = 1
            AND bookyearPeriodeNr IS NOT NULL
          GROUP BY bookyearPeriodeNr) m
    WHERE lines < 0.25 * avg_lines) c
  WHERE thin_periods >= 3
  ```

| Confirm | First step | AI may | Don't | Fixed when |
|---|---|---|---|---|
| Lines per period: are the thin periods the early ones? | The same full resync as `octopus_ledger_imbalance` | do, after a yes | — | No period under 25 % of the average |
