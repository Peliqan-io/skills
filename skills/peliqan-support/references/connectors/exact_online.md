# Exact Online

- `server_type`: as `list_connections` shows it (it starts with `exact_online`).
- Tables: `reportingbalance`.
- Generic checks that matter most here: `duplicate_keys` on `transactionlines`
  (every sum inflated by the ratio), and `noisy` for administrations without
  a module (403 on every run on those endpoints, data current).

## exact_stranded_versions

Each division should have one live snapshot version of `reportingbalance`.
Older versions that stay live are counted twice: the open fiscal year doesn't
foot, and the error grows with every sync. Closed years look fine.

- Severity: CRITICAL
- SQL:

  ```sql
  SELECT Division, COUNT(*) AS stranded_rows
  FROM (SELECT Division, _sdc_table_version,
               MAX(_sdc_table_version) OVER (PARTITION BY Division) AS newest
        FROM {t[reportingbalance]}
        WHERE _sdc_deleted_at IS NULL) v
  WHERE _sdc_table_version < newest
  GROUP BY Division
  ```

| Confirm | First step | AI may | Don't | Fixed when |
|---|---|---|---|---|
| `SUM(Amount)` per division and year over all rows, then over the newest version only: the second nets to zero | Report to Peliqan: superseded snapshot versions are not retired. In the meantime, a view that keeps only the newest `_sdc_table_version` per division | draft (report), do (view) | Resync: it does not retire the old versions | One version per division, and `SUM(Amount)` = 0 per division and year |

## exact_trial_balance

On the newest snapshot, every division nets to zero per year. If it doesn't,
rows are missing, for example because a run that failed halfway still
merged what it had.

- Severity: CRITICAL
- SQL:

  ```sql
  SELECT Division, ReportingYear, ROUND(SUM(Amount), 2) AS net
  FROM (SELECT Division, ReportingYear, Amount,
               COALESCE(_sdc_table_version, 0) AS version,
               MAX(COALESCE(_sdc_table_version, 0)) OVER (PARTITION BY Division) AS newest
        FROM {t[reportingbalance]}
        WHERE _sdc_deleted_at IS NULL) v
  WHERE version = newest
  GROUP BY Division, ReportingYear
  HAVING ABS(SUM(Amount)) > 0.005
  ```

| Confirm | First step | AI may | Don't | Fixed when |
|---|---|---|---|---|
| The divisions and years the query returns; whether the last runs of the connection ended in an error | Report to Peliqan with the divisions, the years and the run that failed | draft | Resync before the cause is fixed: the gap comes back | 0 rows after the fix and one full refresh |

## exact_period0_missing

Opening balances arrive as `ReportingPeriod = 0`. Without them, equity shows
a debit balance and opening and closing years get mixed up.

- Severity: WARNING
- SQL:

  ```sql
  SELECT rows_total FROM (
    SELECT COUNT(*) AS rows_total,
           SUM(CASE WHEN ReportingPeriod = 0 THEN 1 ELSE 0 END) AS period0_rows
    FROM {t[reportingbalance]}
    WHERE _sdc_deleted_at IS NULL) x
  WHERE rows_total > 0 AND period0_rows = 0
  ```

| Confirm | First step | AI may | Don't | Fixed when |
|---|---|---|---|---|
| For one division, the reconstructed opening per GL account against `openingbalanceafterentry` | Report to Peliqan. In the meantime, read the openings from `openingbalanceafterentry` | draft | — | Period 0 rows present |

## exact_period_cutoff

Across divisions, last year's data should mostly run to period 12. More than
half of the divisions stopping at the same earlier period is systematic, not
bookkeeping.

- Severity: CRITICAL
- SQL:

  ```sql
  SELECT last_period, divisions, total FROM (
    SELECT last_period, COUNT(*) AS divisions, SUM(COUNT(*)) OVER () AS total
    FROM (SELECT Division, MAX(ReportingPeriod) AS last_period
          FROM {t[reportingbalance]}
          WHERE ReportingYear = EXTRACT(YEAR FROM CURRENT_DATE) - 1
            AND _sdc_deleted_at IS NULL
          GROUP BY Division) d
    GROUP BY last_period) p
  WHERE last_period < 12 AND divisions > 0.5 * total
  ```

| Confirm | First step | AI may | Don't | Fixed when |
|---|---|---|---|---|
| Check in Exact itself whether two affected divisions have later periods | Exact has them: connector issue, report to Peliqan. Exact doesn't: the customer's bookkeeping, explain | draft, explain | Resync before you know where the data stops | Most divisions end at period 12 |
