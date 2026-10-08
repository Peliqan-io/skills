# Connector checks

The generic checks in `../connections.md` hold for every connector. A connector
file adds the rules only that kind of source has, such as "a trial balance nets
to zero". The library grows one connector at a time.

| Connector | File | Checks |
|---|---|---|
| Exact Online | `exact_online.md` | stranded snapshot versions, trial balance, opening balances, period cutoff |
| Octopus | `octopus.md` | ledger per dossier, purchase journal gaps |
| Horus | `horus.md` | orphan rows, entries that don't foot |
| Silverfin | `silverfin.md` | balances collapsed onto one period |

## Format of a check

One file per connector, named after it. Each check is a `##` section named
`<connector>_<rule>`, with the rule in a sentence or two, a severity, one SQL
query, and one playbook row:

````markdown
## exact_trial_balance

On the newest snapshot, every division nets to zero per year.

- Severity: CRITICAL
- SQL:

  ```sql
  SELECT Division, ReportingYear, ROUND(SUM(Amount), 2) AS net
  FROM {t[reportingbalance]}
  ...
  HAVING ABS(SUM(Amount)) > 0.005
  ```

| Confirm | First step | AI may | Don't | Fixed when |
|---|---|---|---|---|
| ... | ... | ... | ... | 0 rows |
````

The query returns the rows that break the rule. No rows means OK. Write it so
that it runs on Postgres, Snowflake and BigQuery alike:

- `{t[<stream>]}` stands for that stream's table; the app fills in the schema
  and the quoting.
- No other curly braces in the query.
- `CASE WHEN` rather than `IF` or `COUNTIF`; `COALESCE` rather than `IFNULL`;
  `CAST(x AS DATE)`; aggregates in `HAVING` rather than their aliases.
- Unquoted column names, so they match however the warehouse stored the case.
- A rule that is about the whole table (rather than about single rows) wraps
  its aggregate: `SELECT ... FROM (SELECT COUNT(*) AS n ...) x WHERE <broken>`.

Before adding a check, run it once on a table with good data (no rows) and
on one with the problem (rows).

## Using the checks

- **Health app:** when setting the app up, copy the checks for the connectors
  the sub-accounts actually have into `CONNECTOR_CHECKS`, keyed on the exact
  `server_type` that `list_connections` shows:

  ```python
  CONNECTOR_CHECKS = {
      "<server_type>": [
          ("exact_trial_balance", "CRITICAL", """SELECT ... FROM {t[reportingbalance]} ..."""),
      ],
  }
  ```

  Check the column names against the table first (`get_table`). Drop the
  `_sdc_deleted_at` filter if the table has no such column.

- **Check through the MCP:** run the query only if the MCP can query the
  warehouse; otherwise list the check under "not checked".

A finding from a connector check carries the check's name. The playbook row in
the connector's file says what to do about it.
