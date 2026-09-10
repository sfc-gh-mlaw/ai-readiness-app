# Deployment Guide

## Prerequisites

- Snowflake account (Enterprise Edition or higher — required for `ACCESS_HISTORY`)
- A role with `ACCOUNTADMIN` or equivalent privileges (for setup)
- `IMPORTED PRIVILEGES` on the `SNOWFLAKE` database
- A warehouse for the Streamlit app to use
- [Snowflake CLI](https://docs.snowflake.com/en/developer-guide/snowflake-cli-v2/index) (`snow`) installed

---

## Automated Deployment (via CoCo Skill)

If you have [Cortex Code](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-code) installed:

```
cortex -c <your-connection>
> Deploy the AI Readiness Score app
```

The skill will walk you through warehouse selection and deploy everything automatically.

---

## Manual Deployment

### Step 1: Run setup SQL

Edit `setup.sql` to set your warehouse name, then execute:

```bash
snow sql -f setup.sql -c <your-connection>
```

Or run the SQL statements in Snowsight.

### Step 2: Upload app files

```bash
snow stage copy streamlit_app.py @AI_READINESS_APP.PUBLIC.APP_STAGE/ --overwrite -c <connection>
snow stage copy environment.yml @AI_READINESS_APP.PUBLIC.APP_STAGE/ --overwrite -c <connection>
```

### Step 3: Verify

Open Snowsight, navigate to **Streamlit** apps, and find "AI Readiness Score". Click to open.

### Step 4: First run

1. Select **AI_READINESS_APP** as the database scope (or "All databases")
2. Click **Run scan**
3. If you see 0 CR tables, click **Generate demo traffic** in the sidebar, wait 15–45 min for `ACCESS_HISTORY` to catch up, then re-scan

---

## Updating the App

After editing `streamlit_app.py` locally:

```bash
snow stage copy streamlit_app.py @AI_READINESS_APP.PUBLIC.APP_STAGE/ --overwrite -c <connection>
```

Refresh the Streamlit app page in Snowsight — changes take effect immediately.

---

## Teardown

```sql
DROP STREAMLIT IF EXISTS AI_READINESS_APP.PUBLIC.AI_READINESS;
DROP TABLE IF EXISTS AI_READINESS_APP.PUBLIC.SCAN_RUNS;
DROP TABLE IF EXISTS AI_READINESS_APP.PUBLIC.SCAN_IMPROVEMENT_ITEMS;
DROP STAGE IF EXISTS AI_READINESS_APP.PUBLIC.APP_STAGE;
DROP DATABASE IF EXISTS AI_READINESS_APP;
```

---

## Required Privileges

| Object | Privilege | Why |
|---|---|---|
| `SNOWFLAKE` database | `IMPORTED PRIVILEGES` | Access to `account_usage` views |
| `ACCESS_HISTORY` | (via above) | Read tracking for CR scoring + Correlated factor |
| `QUERY_HISTORY` | (via above) | Execution time for speed scoring |
| `SESSIONS` | (via above) | BI tool detection |
| `SEMANTIC_VIEWS` / `SEMANTIC_TABLES` | (via above) | SV coverage and quality |
| `TAG_REFERENCES` | (via above) | Governance tag scoring |
| `POLICY_REFERENCES` | (via above) | Masking policy scoring |
| `AI_READINESS_APP` database | `CREATE STREAMLIT`, `CREATE TABLE`, `CREATE STAGE` | App deployment |

---

## Troubleshooting

| Issue | Cause | Fix |
|---|---|---|
| 0 CR tables scored | No analytical reads in last 7 days | Use "Generate demo traffic" button, wait 15-45 min |
| SV Readiness = 0 | No semantic views exist | Create semantic views on your key tables |
| 6-Factor scan errors on Compliant | `TAG_REFERENCES` has ~2hr latency for new tags | Wait for `account_usage` to catch up |
| Permission denied on `account_usage` | Missing `IMPORTED PRIVILEGES` | `GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE <role>` |
