-- =============================================================================
-- AI Readiness Score — Setup Script
-- Run this in any Snowflake account to deploy the app infrastructure.
-- Replace <YOUR_WAREHOUSE> with a warehouse available to the deploying role.
-- =============================================================================

-- 1. Database and schema
CREATE DATABASE IF NOT EXISTS AI_READINESS_APP;
USE DATABASE AI_READINESS_APP;
USE SCHEMA PUBLIC;

-- 2. Persistence tables for Run History
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

-- 3. Internal stage for Streamlit app files
CREATE STAGE IF NOT EXISTS APP_STAGE;

-- 4. Streamlit app object (adjust QUERY_WAREHOUSE)
CREATE STREAMLIT IF NOT EXISTS AI_READINESS_APP.PUBLIC.AI_READINESS
    ROOT_LOCATION  = '@AI_READINESS_APP.PUBLIC.APP_STAGE'
    MAIN_FILE      = 'streamlit_app.py'
    QUERY_WAREHOUSE = COMPUTE_WH   -- << CHANGE THIS
    COMMENT        = 'AI Readiness Score dashboard — CR tables, SV coverage/quality, 6-factor scan'
    TITLE          = 'AI Readiness Score';

-- 5. Grant imported privileges on SNOWFLAKE database (required for account_usage views)
-- Uncomment if not already granted:
-- GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE <YOUR_ROLE>;

-- 6. (Optional) Grant access to other roles
-- GRANT USAGE ON DATABASE AI_READINESS_APP TO ROLE <ROLE>;
-- GRANT USAGE ON SCHEMA AI_READINESS_APP.PUBLIC TO ROLE <ROLE>;
-- GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA AI_READINESS_APP.PUBLIC TO ROLE <ROLE>;
-- GRANT READ ON STAGE AI_READINESS_APP.PUBLIC.APP_STAGE TO ROLE <ROLE>;
-- GRANT USAGE ON STREAMLIT AI_READINESS_APP.PUBLIC.AI_READINESS TO ROLE <ROLE>;
