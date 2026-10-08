# Connector checks

The generic checks in `../connections.md` hold for every connector. A connector
file adds the rules only that kind of source has, such as "a trial balance nets
to zero". One file per connector, named after its `server_type`:
`connectors/<server_type>.md`.

## Format of a check

Each check is one SQL query that returns the rows breaking the rule. No rows
means OK. `{t[<stream>]}` stands for that stream's table; the app fills in
the schema and the quoting for the warehouse.

````markdown
## trial_balance

Every division's ledger nets to zero per fiscal year. If it doesn't, the
balance sheet the customer sees doesn't foot.

- Severity: CRITICAL
- SQL:

  ```sql
  SELECT division, financial_year, SUM(amount) AS total
  FROM {t[transactionlines]}
  GROUP BY division, financial_year
  HAVING ABS(SUM(amount)) > 0.01
  ```

| Confirm | First step | AI may | Don't | Fixed when |
|---|---|---|---|---|
| Totals per division and year, latest version only | ... | ... | ... | 0 rows |
````

Write the SQL for the warehouse the connector loads into. Postgres SQL
usually also runs on Snowflake; BigQuery needs its own dialect.

## Using the checks

- **Health app:** when setting the app up, copy the checks for the connectors
  the sub-accounts actually have into `CONNECTOR_CHECKS`:

  ```python
  CONNECTOR_CHECKS = {
      "<server_type>": [
          ("trial_balance", "CRITICAL", "SELECT ... FROM {t[transactionlines]} ..."),
      ],
  }
  ```

- **Check through the MCP:** run the query only if the MCP can query the
  warehouse; otherwise list the check under "not checked".

A finding from a connector check carries the check's own name. The playbook
row in the connector file says what to do about it.
