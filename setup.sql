-- =============================================================================
-- AI Readiness Score — Deployment Guide
-- =============================================================================
--
-- PREREQUISITES
-- -------------
--   * Snowflake account (Enterprise Edition or higher — needs ACCESS_HISTORY)
--   * A role with ACCOUNTADMIN (or CREATE DATABASE, CREATE STREAMLIT, etc.)
--   * IMPORTED PRIVILEGES on the SNOWFLAKE database
--   * A warehouse for the Streamlit app to run queries against
--
-- FILES REQUIRED (3 files — upload in Step 3)
-- -------------------------------------------
--   * streamlit_app.py   — main application
--   * gen_report.py      — HTML report generator
--   * environment.yml    — Python dependencies (streamlit, pandas, plotly)
--
-- HOW TO DEPLOY
-- =============
--
-- Step 1: Set your warehouse name below (find-and-replace <YOUR_WAREHOUSE>).
-- Step 2: Run every SQL statement in this file, in order, in a SQL worksheet.
-- Step 3: Upload the 3 app files to the stage (see bottom of this file).
-- Step 4: Open Snowsight > Streamlit > "AI Readiness Score" and run your first scan.
--
-- =============================================================================

-- ── Step 1: Set variables ────────────────────────────────────────────────────
-- Replace <YOUR_WAREHOUSE> with a warehouse available to the deploying role.
-- Example: SET warehouse_name = 'COMPUTE_WH';
SET warehouse_name = '<YOUR_WAREHOUSE>';

-- ── Step 2a: Create database and schema ──────────────────────────────────────
CREATE DATABASE IF NOT EXISTS AI_READINESS_APP;
USE DATABASE AI_READINESS_APP;
USE SCHEMA PUBLIC;

-- ── Step 2b: Create persistence tables ───────────────────────────────────────
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
    n_sv_covered        NUMBER,
    report_html_path    VARCHAR
);

CREATE TABLE IF NOT EXISTS SCAN_IMPROVEMENT_ITEMS (
    run_id         VARCHAR,
    item_type      VARCHAR,
    target         VARCHAR,
    detail         VARCHAR,
    recommendation VARCHAR
);

-- ── Step 2c: Create internal stage ───────────────────────────────────────────
CREATE STAGE IF NOT EXISTS APP_STAGE;

-- ── Step 2d: Create Streamlit app object ─────────────────────────────────────
CREATE STREAMLIT IF NOT EXISTS AI_READINESS_APP.PUBLIC.AI_READINESS
    ROOT_LOCATION   = '@AI_READINESS_APP.PUBLIC.APP_STAGE'
    MAIN_FILE       = 'streamlit_app.py'
    QUERY_WAREHOUSE = IDENTIFIER($warehouse_name)
    COMMENT         = 'AI Readiness Score dashboard — CR tables, SV coverage/quality, 6-factor scan'
    TITLE           = 'AI Readiness Score';

-- ── Step 2e: Grant SNOWFLAKE database access (required for account_usage) ────
-- Uncomment and set your role if IMPORTED PRIVILEGES is not already granted:
-- GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE <YOUR_ROLE>;

-- ── Step 2f: (Optional) Grant access to other roles ─────────────────────────
-- Replace <ROLE> with the role(s) that should access the app.
-- GRANT USAGE ON DATABASE AI_READINESS_APP TO ROLE <ROLE>;
-- GRANT USAGE ON SCHEMA AI_READINESS_APP.PUBLIC TO ROLE <ROLE>;
-- GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA AI_READINESS_APP.PUBLIC TO ROLE <ROLE>;
-- GRANT READ ON STAGE AI_READINESS_APP.PUBLIC.APP_STAGE TO ROLE <ROLE>;
-- GRANT USAGE ON STREAMLIT AI_READINESS_APP.PUBLIC.AI_READINESS TO ROLE <ROLE>;

-- =============================================================================
-- Step 3: Upload app files
-- =============================================================================
-- Option A: Snowflake CLI (from the directory containing the 3 files)
--
--   snow stage copy streamlit_app.py @AI_READINESS_APP.PUBLIC.APP_STAGE/ --overwrite
--   snow stage copy gen_report.py    @AI_READINESS_APP.PUBLIC.APP_STAGE/ --overwrite
--   snow stage copy environment.yml  @AI_READINESS_APP.PUBLIC.APP_STAGE/ --overwrite
--
-- Option B: PUT commands (run in SnowSQL or a SQL worksheet with file access)
--
--   PUT file:///path/to/streamlit_app.py @AI_READINESS_APP.PUBLIC.APP_STAGE/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
--   PUT file:///path/to/gen_report.py    @AI_READINESS_APP.PUBLIC.APP_STAGE/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
--   PUT file:///path/to/environment.yml  @AI_READINESS_APP.PUBLIC.APP_STAGE/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
--
-- Option C: Snowsight UI
--   Navigate to Data > Databases > AI_READINESS_APP > PUBLIC > Stages > APP_STAGE
--   Click "+ Files" and upload all 3 files.
--
-- =============================================================================

-- ── Step 4: Verify ───────────────────────────────────────────────────────────
-- Run these to confirm everything is in place:
LIST @AI_READINESS_APP.PUBLIC.APP_STAGE/;
SHOW STREAMLITS IN AI_READINESS_APP.PUBLIC;

-- =============================================================================
-- Teardown (run only if you want to remove the app entirely)
-- =============================================================================
-- DROP STREAMLIT IF EXISTS AI_READINESS_APP.PUBLIC.AI_READINESS;
-- DROP TABLE IF EXISTS AI_READINESS_APP.PUBLIC.SCAN_RUNS;
-- DROP TABLE IF EXISTS AI_READINESS_APP.PUBLIC.SCAN_IMPROVEMENT_ITEMS;
-- DROP STAGE IF EXISTS AI_READINESS_APP.PUBLIC.APP_STAGE;
-- DROP DATABASE IF EXISTS AI_READINESS_APP;
