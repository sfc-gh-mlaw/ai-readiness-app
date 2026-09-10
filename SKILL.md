# AI Readiness Score — CoCo Skill

## Description

Deploy and manage the AI Readiness Score Streamlit-in-Snowflake app. This skill automates the full setup: creates the database, persistence tables, internal stage, uploads the app, and creates the Streamlit object.

## Triggers

- "deploy AI readiness app"
- "set up AI readiness score"
- "install AI readiness dashboard"
- "ai readiness score"

---

## Deployment Flow

When the user asks to deploy:

### 1. Check prerequisites

```sql
SELECT CURRENT_ROLE() AS role, CURRENT_ACCOUNT() AS account;
```

Verify the role has `CREATE DATABASE` or the target database already exists.

### 2. Ask for warehouse

Ask the user which warehouse to use for the Streamlit app:

```sql
SHOW WAREHOUSES;
```

Present the list and let them choose.

### 3. Run setup SQL

Execute the statements from `setup.sql` (in the skill directory), substituting the chosen warehouse name into the `CREATE STREAMLIT` statement.

```sql
CREATE DATABASE IF NOT EXISTS AI_READINESS_APP;
USE DATABASE AI_READINESS_APP;
USE SCHEMA PUBLIC;

CREATE TABLE IF NOT EXISTS SCAN_RUNS (
    run_id              VARCHAR DEFAULT UUID_STRING(),
    run_ts              TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    account_name        VARCHAR,
    role_name           VARCHAR,
    database_filter     VARCHAR,
    sample_pct          NUMBER,
    ai_readiness        FLOAT,
    demand_coverage     FLOAT,
    sv_readiness        FLOAT,
    sv_coverage         FLOAT,
    sv_quality          FLOAT,
    n_cr_tables         NUMBER,
    gap                 VARCHAR,
    recommendation_text VARCHAR,
    n_all_scored        NUMBER,
    n_sv                NUMBER,
    n_sv_covered        NUMBER
);

CREATE TABLE IF NOT EXISTS SCAN_IMPROVEMENT_ITEMS (
    run_id         VARCHAR,
    item_type      VARCHAR,
    target         VARCHAR,
    detail         VARCHAR,
    recommendation VARCHAR
);

CREATE STAGE IF NOT EXISTS APP_STAGE;
```

### 4. Upload app files

Use the Snowflake CLI to upload:

```bash
snow stage copy <skill_dir>/streamlit_app.py @AI_READINESS_APP.PUBLIC.APP_STAGE/ --overwrite
snow stage copy <skill_dir>/environment.yml @AI_READINESS_APP.PUBLIC.APP_STAGE/ --overwrite
```

### 5. Create the Streamlit object

```sql
CREATE OR REPLACE STREAMLIT AI_READINESS_APP.PUBLIC.AI_READINESS
    ROOT_LOCATION  = '@AI_READINESS_APP.PUBLIC.APP_STAGE'
    MAIN_FILE      = 'streamlit_app.py'
    QUERY_WAREHOUSE = <chosen_warehouse>
    COMMENT        = 'AI Readiness Score dashboard — CR tables, SV coverage/quality, 6-factor scan'
    TITLE          = 'AI Readiness Score';
```

### 6. Grant imported privileges

```sql
GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE <current_role>;
```

### 7. Confirm deployment

```sql
SHOW STREAMLITS LIKE 'AI_READINESS' IN AI_READINESS_APP.PUBLIC;
```

Report the URL and tell the user to open it in Snowsight.

---

## Teardown Flow

When the user asks to remove/teardown:

```sql
DROP STREAMLIT IF EXISTS AI_READINESS_APP.PUBLIC.AI_READINESS;
DROP TABLE IF EXISTS AI_READINESS_APP.PUBLIC.SCAN_RUNS;
DROP TABLE IF EXISTS AI_READINESS_APP.PUBLIC.SCAN_IMPROVEMENT_ITEMS;
DROP STAGE IF EXISTS AI_READINESS_APP.PUBLIC.APP_STAGE;
DROP DATABASE IF EXISTS AI_READINESS_APP;
```

---

## Update Flow

When the user asks to update/redeploy:

```bash
snow stage copy <skill_dir>/streamlit_app.py @AI_READINESS_APP.PUBLIC.APP_STAGE/ --overwrite
```

Tell the user to refresh the Streamlit page in Snowsight.

---

## References

- `references/scoring-methodology.md` — CR table formula, SV quality scale, composite scoring
- `references/6-factor-framework.md` — the 6 factors, 13 requirements, SQL checks
- `references/deployment-guide.md` — manual deployment steps and troubleshooting
