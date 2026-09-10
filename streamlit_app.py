"""
AI Readiness Score — Streamlit-in-Snowflake app.

Reuses the scoring methodology from the bundled `ai-readiness-score` CoCo skill:
  - Consumption-Ready (CR) table scoring (Cobb-Douglas blend of activity/consumption/speed/freshness)
  - Semantic View (SV) coverage + quality scoring (PK, synonyms, unique keys, relationships,
    metrics, verified queries, comment depth)
  - Composite AI Readiness score = avg(demand coverage, sqrt(SV coverage * SV quality))
"""

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from snowflake.snowpark.context import get_active_session
from gen_report import render_html as render_report_html

st.set_page_config(page_title="AI Readiness Score", page_icon="🤖", layout="wide")

session = get_active_session()

# --------------------------------------------------------------------------------------
# SQL templates
# --------------------------------------------------------------------------------------

CR_TABLES_SQL = """
WITH ah_base AS (
    SELECT
        f.value:objectName::string                               AS full_table_name,
        UPPER(SPLIT_PART(f.value:objectName::string, '.', 1))    AS database_name,
        UPPER(SPLIT_PART(f.value:objectName::string, '.', 2))    AS schema_name,
        UPPER(SPLIT_PART(f.value:objectName::string, '.', 3))    AS table_name,
        ah.query_id,
        ah.user_name
    FROM snowflake.account_usage.access_history ah,
         LATERAL FLATTEN(input => ah.base_objects_accessed) f
    WHERE ah.query_start_time::DATE BETWEEN '{start_ts}'::DATE AND '{end_ts}'::DATE
      AND ARRAY_SIZE(ah.objects_modified) = 0
      AND f.value:objectDomain::string = 'Table'
      AND SPLIT_PART(f.value:objectName::string, '.', 2) != ''
      AND SPLIT_PART(f.value:objectName::string, '.', 3) != ''
      AND NOT (
          UPPER(SPLIT_PART(f.value:objectName::string, '.', 1)) = 'AI_READINESS_APP'
          AND UPPER(SPLIT_PART(f.value:objectName::string, '.', 2)) = 'PUBLIC'
          AND UPPER(SPLIT_PART(f.value:objectName::string, '.', 3)) IN ('SCAN_RUNS', 'SCAN_IMPROVEMENT_ITEMS')
      )
      {sample_predicate}
      {db_predicate}
),
reads_joined AS (
    SELECT
        ab.database_name, ab.schema_name, ab.table_name, ab.full_table_name, ab.user_name,
        qh.execution_time AS execution_time_ms,
        TRY_PARSE_JSON(s.CLIENT_ENVIRONMENT):APPLICATION::string AS application_name,
        CASE WHEN application_name
                  ILIKE ANY ('%looker%', '%googledatastudio%', '%tabproto%',
                             '%tableauserver%', '%tableau%prep%', '%tableaudesktop%',
                             '%tableaubridge%', '%tableaucloud%',
                             '%Power%BI%', '%data gateway%', '%MashupEngine%',
                             '%Onpremisesdatagateway%',
                             '%thoughtspot%', '%microstrategy%', '%sisense%',
                             '%metabase%', '%cognos%', '%spotfire%', '%qlik%',
                             '%atscale%', '%cluvio%', '%gooddata%', '%sisu_data%',
                             '%SAP%BusinessObjects%', '%bobjenterprise%', '%domo%',
                             '%periscope%', '%abinitio%', '%birst%', '%chartio%',
                             '%zoomdata%', '%datavaultbuilder%', '%adverity%',
                             '%astrato%')
             OR application_name = 'Sigma \u03a3'
             OR application_name = 'M'
             OR application_name = 'modeanalytics'
             OR application_name ILIKE 'Snowflake Web App (snowsight\\_streamlit)'
             OR application_name ILIKE 'Snowflake Web App (snowsight\\_dashboard)'
             OR application_name = 'streamlit'
             OR application_name ILIKE 'SNOWCLI.STREAMLIT%'
             THEN 1 ELSE NULL END AS is_bi_or_dashboard
    FROM ah_base ab
    JOIN snowflake.account_usage.query_history qh ON ab.query_id = qh.query_id
    LEFT JOIN snowflake.account_usage.sessions s ON qh.session_id = s.session_id
    WHERE qh.query_type = 'SELECT'
      AND qh.error_code IS NULL
      AND qh.execution_time > 0
      AND qh.warehouse_id IS NOT NULL
      AND qh.is_client_generated_statement = FALSE
      AND (qh.user_type IS NULL OR qh.user_type != 'SNOWFLAKE_SERVICE')
      AND qh.start_time::DATE BETWEEN '{start_ts}'::DATE AND '{end_ts}'::DATE
),
reads_agg AS (
    SELECT
        database_name, schema_name, table_name, full_table_name,
        COUNT(*)                  AS analytical_reads,
        COUNT(DISTINCT user_name) AS distinct_users,
        COUNT(is_bi_or_dashboard) AS app_reads,
        COUNT(DISTINCT CASE WHEN is_bi_or_dashboard = 1 THEN application_name END) AS distinct_app_tools,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY execution_time_ms) AS p50_execution_ms
    FROM reads_joined
    GROUP BY database_name, schema_name, table_name, full_table_name
    HAVING COUNT(*) >= 5
),
table_meta AS (
    SELECT
        UPPER(table_catalog) AS database_name,
        UPPER(table_schema)  AS schema_name,
        UPPER(table_name)    AS table_name,
        DATEDIFF('day', last_altered, CURRENT_TIMESTAMP()) AS days_since_update
    FROM snowflake.account_usage.tables
    WHERE deleted IS NULL
      AND table_type = 'BASE TABLE'
      AND last_altered >= '{freshness_start_ts}'::TIMESTAMP_LTZ
),
reads_with_freshness AS (
    SELECT
        r.database_name, r.schema_name, r.table_name, r.full_table_name,
        r.analytical_reads, r.distinct_users, r.app_reads, r.distinct_app_tools,
        r.p50_execution_ms,
        COALESCE(m.days_since_update, 60) AS days_since_update
    FROM reads_agg r
    LEFT JOIN table_meta m
        ON r.database_name = m.database_name
       AND r.schema_name   = m.schema_name
       AND r.table_name    = m.table_name
),
pct_ranked AS (
    SELECT *,
        PERCENT_RANK() OVER (ORDER BY analytical_reads) AS activity_pctile,
        PERCENT_RANK() OVER (ORDER BY distinct_users)   AS user_pctile,
        PERCENT_RANK() OVER (ORDER BY app_reads)        AS app_pctile
    FROM reads_with_freshness
)
SELECT
    database_name, schema_name, table_name, full_table_name,
    analytical_reads, distinct_users, app_reads, distinct_app_tools,
    ROUND(activity_pctile, 4)                                         AS activity_score,
    ROUND(GREATEST(user_pctile, app_pctile), 4)                       AS consumption_score,
    ROUND(1.0 / (1.0 + POW(p50_execution_ms / 5000.0, 3)), 4)         AS speed_score,
    ROUND(EXP(-LN(2) / 30.0 * days_since_update), 4)                  AS freshness_score,
    ROUND(
        POW(GREATEST(activity_pctile, 0.001), 0.35)
      * POW(GREATEST(GREATEST(user_pctile, app_pctile), 0.001), 0.30)
      * POW(GREATEST(1.0 / (1.0 + POW(p50_execution_ms / 5000.0, 3)), 0.001), 0.20)
      * POW(GREATEST(EXP(-LN(2) / 30.0 * days_since_update), 0.001), 0.15)
    , 4) AS consumption_readiness_score
FROM pct_ranked
ORDER BY consumption_readiness_score DESC
"""

SV_QUALITY_SQL = """
WITH sv AS (
    SELECT
        SEMANTIC_VIEW_ID,
        SEMANTIC_VIEW_DATABASE_NAME || '.' || SEMANTIC_VIEW_SCHEMA_NAME || '.' || SEMANTIC_VIEW_NAME AS sv_fqn,
        comment AS view_comment
    FROM SNOWFLAKE.ACCOUNT_USAGE.SEMANTIC_VIEWS
    WHERE DELETED IS NULL
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY SEMANTIC_VIEW_DATABASE_NAME, SEMANTIC_VIEW_SCHEMA_NAME, SEMANTIC_VIEW_NAME
        ORDER BY LAST_ALTERED DESC NULLS LAST
    ) = 1
),
st_deduped AS (
    SELECT SEMANTIC_VIEW_ID, SEMANTIC_TABLE_NAME,
           UPPER(BASE_TABLE_DATABASE_NAME) AS base_database,
           UPPER(BASE_TABLE_SCHEMA_NAME)   AS base_schema,
           UPPER(BASE_TABLE_NAME)          AS base_table,
           PRIMARY_KEYS, UNIQUE_KEYS, DISTINCT_RANGES, SYNONYMS,
           comment, last_altered
    FROM SNOWFLAKE.ACCOUNT_USAGE.SEMANTIC_TABLES
    WHERE DELETED IS NULL
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY SEMANTIC_VIEW_ID, SEMANTIC_TABLE_NAME
        ORDER BY LAST_ALTERED DESC NULLS LAST
    ) = 1
),
st_base_tables AS (
    SELECT DISTINCT SEMANTIC_VIEW_ID, base_database, base_schema, base_table
    FROM st_deduped
    WHERE base_database IS NOT NULL AND base_table IS NOT NULL
),
tbl_signals AS (
    SELECT
        SEMANTIC_VIEW_ID,
        COALESCE(BOOLOR_AGG(ARRAY_SIZE(PRIMARY_KEYS)    > 0), FALSE) AS has_pk,
        COALESCE(BOOLOR_AGG(ARRAY_SIZE(UNIQUE_KEYS)     > 0), FALSE) AS has_unique_keys,
        COALESCE(BOOLOR_AGG(ARRAY_SIZE(DISTINCT_RANGES) > 0), FALSE) AS has_distinct_ranges,
        COALESCE(BOOLOR_AGG(ARRAY_SIZE(SYNONYMS)        > 0), FALSE) AS tbl_has_synonyms
    FROM st_deduped
    GROUP BY 1
),
st_comments AS (
    SELECT SEMANTIC_VIEW_ID, ARRAY_AGG(comment) WITHIN GROUP (ORDER BY last_altered DESC) AS table_comments
    FROM st_deduped WHERE comment IS NOT NULL GROUP BY 1
),
sd_deduped AS (
    SELECT SEMANTIC_VIEW_ID, SYNONYMS, comment, last_altered
    FROM SNOWFLAKE.ACCOUNT_USAGE.SEMANTIC_DIMENSIONS
    WHERE DELETED IS NULL
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY SEMANTIC_VIEW_ID, SEMANTIC_DIMENSION_NAME
        ORDER BY LAST_ALTERED DESC NULLS LAST
    ) = 1
),
sd_synonyms AS (
    SELECT SEMANTIC_VIEW_ID, COALESCE(BOOLOR_AGG(ARRAY_SIZE(SYNONYMS) > 0), FALSE) AS has_synonyms
    FROM sd_deduped GROUP BY 1
),
sd_comments AS (
    SELECT SEMANTIC_VIEW_ID, ARRAY_AGG(comment) WITHIN GROUP (ORDER BY last_altered DESC) AS dimension_comments
    FROM sd_deduped WHERE comment IS NOT NULL GROUP BY 1
),
sf_deduped AS (
    SELECT SEMANTIC_VIEW_ID, SYNONYMS, comment, last_altered
    FROM SNOWFLAKE.ACCOUNT_USAGE.SEMANTIC_FACTS
    WHERE DELETED IS NULL
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY SEMANTIC_VIEW_ID, SEMANTIC_FACT_NAME
        ORDER BY LAST_ALTERED DESC NULLS LAST
    ) = 1
),
sf_synonyms AS (
    SELECT SEMANTIC_VIEW_ID, COALESCE(BOOLOR_AGG(ARRAY_SIZE(SYNONYMS) > 0), FALSE) AS has_synonyms
    FROM sf_deduped GROUP BY 1
),
sf_comments AS (
    SELECT SEMANTIC_VIEW_ID, ARRAY_AGG(comment) WITHIN GROUP (ORDER BY last_altered DESC) AS fact_comments
    FROM sf_deduped WHERE comment IS NOT NULL GROUP BY 1
),
sm_deduped AS (
    SELECT SEMANTIC_VIEW_ID, SYNONYMS, comment, last_altered
    FROM SNOWFLAKE.ACCOUNT_USAGE.SEMANTIC_METRICS
    WHERE DELETED IS NULL
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY SEMANTIC_VIEW_ID, SEMANTIC_METRIC_NAME
        ORDER BY LAST_ALTERED DESC NULLS LAST
    ) = 1
),
sm_synonyms AS (
    SELECT SEMANTIC_VIEW_ID, COALESCE(BOOLOR_AGG(ARRAY_SIZE(SYNONYMS) > 0), FALSE) AS has_synonyms
    FROM sm_deduped GROUP BY 1
),
metric_signals AS (
    SELECT DISTINCT SEMANTIC_VIEW_ID FROM sm_deduped
),
sm_comments AS (
    SELECT SEMANTIC_VIEW_ID, ARRAY_AGG(comment) WITHIN GROUP (ORDER BY last_altered DESC) AS metric_comments
    FROM sm_deduped WHERE comment IS NOT NULL GROUP BY 1
),
rel_signals AS (
    SELECT DISTINCT SEMANTIC_VIEW_ID
    FROM SNOWFLAKE.ACCOUNT_USAGE.SEMANTIC_RELATIONSHIPS
    WHERE DELETED IS NULL
),
comment_agg AS (
    SELECT
        sv.SEMANTIC_VIEW_ID,
        ARRAY_COMPACT(
            ARRAY_FLATTEN(ARRAY_CONSTRUCT(
                ARRAY_CONSTRUCT(sv.view_comment),
                COALESCE(stc.table_comments,     ARRAY_CONSTRUCT()),
                COALESCE(sdc.dimension_comments, ARRAY_CONSTRUCT()),
                COALESCE(sfc.fact_comments,      ARRAY_CONSTRUCT()),
                COALESCE(smc.metric_comments,    ARRAY_CONSTRUCT())
            ))
        ) AS all_comments,
        ROUND(LEN(ARRAY_TO_STRING(all_comments, '')) / NULLIF(ARRAY_SIZE(all_comments), 0), 1) AS avg_comment_length
    FROM sv
    LEFT JOIN st_comments stc ON sv.SEMANTIC_VIEW_ID = stc.SEMANTIC_VIEW_ID
    LEFT JOIN sd_comments sdc ON sv.SEMANTIC_VIEW_ID = sdc.SEMANTIC_VIEW_ID
    LEFT JOIN sf_comments sfc ON sv.SEMANTIC_VIEW_ID = sfc.SEMANTIC_VIEW_ID
    LEFT JOIN sm_comments smc ON sv.SEMANTIC_VIEW_ID = smc.SEMANTIC_VIEW_ID
),
vqr_counts AS (
    {vqr_source}
)
SELECT
    sv.sv_fqn,
    bt.base_database,
    bt.base_schema,
    bt.base_table,
    COALESCE(ts.has_pk, FALSE)                                                          AS has_pk,
    COALESCE(ts.tbl_has_synonyms OR sds.has_synonyms OR sfs.has_synonyms OR sms.has_synonyms, FALSE) AS has_synonyms,
    COALESCE(ts.has_unique_keys, FALSE)                                                 AS has_unique_keys,
    COALESCE(ts.has_distinct_ranges, FALSE)                                             AS has_distinct_ranges,
    (rs.SEMANTIC_VIEW_ID IS NOT NULL)                                                   AS has_relationships,
    (mets.SEMANTIC_VIEW_ID IS NOT NULL)                                                 AS has_metrics,
    COALESCE(c.avg_comment_length, 0.0)                                                 AS avg_comment_length,
    COALESCE(vq.n_verified_queries, 0)                                                  AS n_verified_queries,
    ROUND((
        COALESCE(ts.has_pk, FALSE)::INT
        + COALESCE(ts.tbl_has_synonyms OR sds.has_synonyms OR sfs.has_synonyms OR sms.has_synonyms, FALSE)::INT
        + COALESCE(ts.has_unique_keys, FALSE)::INT
        + COALESCE(ts.has_distinct_ranges, FALSE)::INT
        + (rs.SEMANTIC_VIEW_ID IS NOT NULL)::INT
        + (mets.SEMANTIC_VIEW_ID IS NOT NULL)::INT
        + 2 * (1 - EXP(-(LN(10) / 10) * COALESCE(vq.n_verified_queries, 0)))
        + 1 * (1 - EXP(-(LN(100) / 100) * COALESCE(c.avg_comment_length, 0.0)))
    ) / 9.0, 4) AS quality_score
FROM sv
LEFT JOIN st_base_tables bt   ON bt.SEMANTIC_VIEW_ID   = sv.SEMANTIC_VIEW_ID
LEFT JOIN tbl_signals    ts   ON ts.SEMANTIC_VIEW_ID   = sv.SEMANTIC_VIEW_ID
LEFT JOIN sd_synonyms    sds  ON sds.SEMANTIC_VIEW_ID  = sv.SEMANTIC_VIEW_ID
LEFT JOIN sf_synonyms    sfs  ON sfs.SEMANTIC_VIEW_ID  = sv.SEMANTIC_VIEW_ID
LEFT JOIN sm_synonyms    sms  ON sms.SEMANTIC_VIEW_ID  = sv.SEMANTIC_VIEW_ID
LEFT JOIN rel_signals    rs   ON rs.SEMANTIC_VIEW_ID   = sv.SEMANTIC_VIEW_ID
LEFT JOIN metric_signals mets ON mets.SEMANTIC_VIEW_ID = sv.SEMANTIC_VIEW_ID
LEFT JOIN comment_agg    c    ON c.SEMANTIC_VIEW_ID    = sv.SEMANTIC_VIEW_ID
LEFT JOIN vqr_counts     vq   ON vq.sv_fqn            = sv.sv_fqn
ORDER BY quality_score DESC
"""


# --------------------------------------------------------------------------------------
# 6-Factor Scan — AI-Ready Data Framework ("scan" profile, 13 requirements)
# Ported from https://github.com/Snowflake-Labs/ai-ready-data
# --------------------------------------------------------------------------------------

SIX_FACTOR_CHECKS = {
    "Clean": {
        "data_completeness": {
            "label": "Data completeness (columns marked NOT NULL)",
            "sql": """
WITH all_cols AS (
    SELECT c.table_name, c.column_name, c.is_nullable
    FROM {database}.information_schema.columns c
    JOIN {database}.information_schema.tables t
        ON c.table_catalog = t.table_catalog
        AND c.table_schema = t.table_schema
        AND c.table_name = t.table_name
    WHERE UPPER(c.table_schema) = UPPER('{schema}')
      AND t.table_type = 'BASE TABLE'
)
SELECT
    COUNT_IF(is_nullable = 'NO') AS numerator,
    COUNT(*) AS denominator,
    COUNT_IF(is_nullable = 'NO')::FLOAT / NULLIF(COUNT(*)::FLOAT, 0) AS value
FROM all_cols
""",
        },
        "uniqueness": {
            "label": "Uniqueness (tables with PK or UNIQUE constraint)",
            "sql": """
WITH tables_in_scope AS (
    SELECT UPPER(table_name) AS table_name
    FROM {database}.information_schema.tables
    WHERE UPPER(table_schema) = UPPER('{schema}')
      AND table_type = 'BASE TABLE'
),
tables_with_unique AS (
    SELECT DISTINCT UPPER(table_name) AS table_name
    FROM {database}.information_schema.table_constraints
    WHERE UPPER(table_schema) = UPPER('{schema}')
      AND constraint_type IN ('PRIMARY KEY', 'UNIQUE')
)
SELECT
    COUNT_IF(t.table_name IN (SELECT table_name FROM tables_with_unique)) AS numerator,
    COUNT(*) AS denominator,
    COUNT_IF(t.table_name IN (SELECT table_name FROM tables_with_unique))::FLOAT
        / NULLIF(COUNT(*)::FLOAT, 0) AS value
FROM tables_in_scope t
""",
        },
        "referential_integrity": {
            "label": "Referential integrity (FK constraints declared)",
            "sql": """
WITH tables_with_fk_cols AS (
    SELECT DISTINCT UPPER(c.table_name) AS table_name
    FROM {database}.information_schema.columns c
    JOIN {database}.information_schema.tables t
        ON c.table_catalog = t.table_catalog
        AND c.table_schema = t.table_schema
        AND c.table_name = t.table_name
    WHERE UPPER(c.table_schema) = UPPER('{schema}')
      AND t.table_type = 'BASE TABLE'
      AND REGEXP_LIKE(LOWER(c.column_name), '.*_id$')
),
tables_with_fk_constraint AS (
    SELECT DISTINCT UPPER(table_name) AS table_name
    FROM {database}.information_schema.table_constraints
    WHERE UPPER(table_schema) = UPPER('{schema}')
      AND constraint_type = 'FOREIGN KEY'
)
SELECT
    (SELECT COUNT(*) FROM tables_with_fk_constraint
     WHERE table_name IN (SELECT table_name FROM tables_with_fk_cols)) AS numerator,
    GREATEST((SELECT COUNT(*) FROM tables_with_fk_cols), 1) AS denominator,
    (SELECT COUNT(*) FROM tables_with_fk_constraint
     WHERE table_name IN (SELECT table_name FROM tables_with_fk_cols))::FLOAT
        / NULLIF(GREATEST((SELECT COUNT(*) FROM tables_with_fk_cols), 1)::FLOAT, 0) AS value
""",
        },
    },
    "Contextual": {
        "semantic_documentation": {
            "label": "Semantic documentation (SV coverage)",
            "sql": """
WITH base_tables AS (
    SELECT UPPER(table_name) AS table_name
    FROM {database}.information_schema.tables
    WHERE UPPER(table_schema) = UPPER('{schema}')
        AND table_type = 'BASE TABLE'
),
covered AS (
    SELECT DISTINCT UPPER(st.base_table_name) AS table_name
    FROM SNOWFLAKE.ACCOUNT_USAGE.SEMANTIC_TABLES st
    WHERE UPPER(st.base_table_database_name) = UPPER('{database}')
      AND UPPER(st.base_table_schema_name) = UPPER('{schema}')
      AND st.deleted IS NULL
)
SELECT
    (SELECT COUNT(*) FROM covered c JOIN base_tables b ON c.table_name = b.table_name) AS numerator,
    (SELECT COUNT(*) FROM base_tables) AS denominator,
    (SELECT COUNT(*) FROM covered c JOIN base_tables b ON c.table_name = b.table_name)::FLOAT
        / NULLIF((SELECT COUNT(*) FROM base_tables)::FLOAT, 0) AS value
""",
        },
        "entity_identifier_declaration": {
            "label": "Entity identifier declaration (PK/UNIQUE)",
            "sql": """
WITH tables_in_scope AS (
    SELECT UPPER(table_name) AS table_name
    FROM {database}.information_schema.tables
    WHERE UPPER(table_schema) = UPPER('{schema}')
      AND table_type = 'BASE TABLE'
),
tables_with_identifiers AS (
    SELECT DISTINCT UPPER(table_name) AS table_name
    FROM {database}.information_schema.table_constraints
    WHERE UPPER(table_schema) = UPPER('{schema}')
      AND constraint_type IN ('PRIMARY KEY','UNIQUE')
)
SELECT
    COUNT_IF(t.table_name IN (SELECT table_name FROM tables_with_identifiers)) AS numerator,
    COUNT(*) AS denominator,
    COUNT_IF(t.table_name IN (SELECT table_name FROM tables_with_identifiers))::FLOAT
        / NULLIF(COUNT(*)::FLOAT, 0) AS value
FROM tables_in_scope t
""",
        },
        "schema_type_coverage": {
            "label": "Schema type coverage (semantic-role signal)",
            "sql": """
WITH columns_in_scope AS (
    SELECT
        c.table_name,
        c.column_name,
        c.comment
    FROM {database}.information_schema.columns c
    JOIN {database}.information_schema.tables t
        ON c.table_catalog = t.table_catalog
        AND c.table_schema = t.table_schema
        AND c.table_name = t.table_name
    WHERE UPPER(c.table_schema) = UPPER('{schema}')
        AND t.table_type = 'BASE TABLE'
),
columns_with_semantic_type AS (
    SELECT *
    FROM columns_in_scope
    WHERE (comment IS NOT NULL AND comment <> '')
       OR REGEXP_LIKE(
            LOWER(column_name),
            '.*(_id$|_key$|_date$|_at$|_time$|time|amount|price|cost|count|quantity|total|name|description|status|type|category).*'
          )
)
SELECT
    (SELECT COUNT(*) FROM columns_with_semantic_type) AS numerator,
    (SELECT COUNT(*) FROM columns_in_scope) AS denominator,
    (SELECT COUNT(*) FROM columns_with_semantic_type)::FLOAT
        / NULLIF((SELECT COUNT(*) FROM columns_in_scope)::FLOAT, 0) AS value
""",
        },
    },
    "Consumable": {
        "access_optimization": {
            "label": "Access optimization (clustering on large tables)",
            "sql": """
WITH large_tables AS (
    SELECT
        table_name,
        clustering_key
    FROM {database}.information_schema.tables
    WHERE UPPER(table_schema) = UPPER('{schema}')
      AND table_type = 'BASE TABLE'
      AND row_count > 10000
)
SELECT
    COUNT_IF(clustering_key IS NOT NULL) AS numerator,
    COUNT(*) AS denominator,
    COUNT_IF(clustering_key IS NOT NULL)::FLOAT / NULLIF(COUNT(*)::FLOAT, 0) AS value
FROM large_tables
""",
        },
    },
    "Current": {
        "change_detection": {
            "label": "Change detection (change tracking enabled)",
            "sql": """
SHOW TABLES IN SCHEMA {database}.{schema};

SELECT
    COUNT_IF("change_tracking" = 'ON') AS numerator,
    COUNT(*) AS denominator,
    COUNT_IF("change_tracking" = 'ON')::FLOAT
        / NULLIF(COUNT(*)::FLOAT, 0) AS value
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))
WHERE "kind" = 'TABLE'
""",
        },
        "data_freshness": {
            "label": "Data freshness (altered within 7 days)",
            "sql": """
SELECT
    COUNT_IF(DATEDIFF('hour', last_altered, CURRENT_TIMESTAMP()) <= 168) AS numerator,
    COUNT(*) AS denominator,
    COUNT_IF(DATEDIFF('hour', last_altered, CURRENT_TIMESTAMP()) <= 168)::FLOAT
        / NULLIF(COUNT(*)::FLOAT, 0) AS value
FROM {database}.information_schema.tables
WHERE UPPER(table_schema) = UPPER('{schema}')
    AND table_type = 'BASE TABLE'
""",
        },
    },
    "Correlated": {
        "data_provenance": {
            "label": "Data provenance (tables read by downstream queries)",
            "sql": """
WITH tables_in_scope AS (
    SELECT UPPER(table_name) AS table_name
    FROM {database}.information_schema.tables
    WHERE UPPER(table_schema) = UPPER('{schema}')
      AND table_type = 'BASE TABLE'
),
tables_read AS (
    SELECT DISTINCT
        UPPER(SPLIT_PART(f.value:objectName::string, '.', 3)) AS table_name
    FROM snowflake.account_usage.access_history ah,
         LATERAL FLATTEN(input => ah.base_objects_accessed) f
    WHERE ah.query_start_time >= DATEADD('day', -30, CURRENT_TIMESTAMP())
      AND UPPER(SPLIT_PART(f.value:objectName::string, '.', 1)) = UPPER('{database}')
      AND UPPER(SPLIT_PART(f.value:objectName::string, '.', 2)) = UPPER('{schema}')
      AND f.value:objectDomain::string = 'Table'
)
SELECT
    COUNT_IF(t.table_name IN (SELECT table_name FROM tables_read)) AS numerator,
    COUNT(*) AS denominator,
    COUNT_IF(t.table_name IN (SELECT table_name FROM tables_read))::FLOAT
        / NULLIF(COUNT(*)::FLOAT, 0) AS value
FROM tables_in_scope t
""",
        },
        "lineage_completeness": {
            "label": "Lineage completeness (tables with upstream write history)",
            "sql": """
WITH tables_in_scope AS (
    SELECT UPPER(table_name) AS table_name
    FROM {database}.information_schema.tables
    WHERE UPPER(table_schema) = UPPER('{schema}')
      AND table_type = 'BASE TABLE'
),
tables_written AS (
    SELECT DISTINCT
        UPPER(SPLIT_PART(f.value:objectName::string, '.', 3)) AS table_name
    FROM snowflake.account_usage.access_history ah,
         LATERAL FLATTEN(input => ah.objects_modified) f
    WHERE ah.query_start_time >= DATEADD('day', -30, CURRENT_TIMESTAMP())
      AND UPPER(SPLIT_PART(f.value:objectName::string, '.', 1)) = UPPER('{database}')
      AND UPPER(SPLIT_PART(f.value:objectName::string, '.', 2)) = UPPER('{schema}')
      AND f.value:objectDomain::string = 'Table'
)
SELECT
    COUNT_IF(t.table_name IN (SELECT table_name FROM tables_written)) AS numerator,
    COUNT(*) AS denominator,
    COUNT_IF(t.table_name IN (SELECT table_name FROM tables_written))::FLOAT
        / NULLIF(COUNT(*)::FLOAT, 0) AS value
FROM tables_in_scope t
""",
        },
    },
    "Compliant": {
        "classification": {
            "label": "Classification (governance tags applied)",
            "sql": """
WITH table_count AS (
    SELECT COUNT(*) AS cnt
    FROM {database}.information_schema.tables
    WHERE UPPER(table_schema) = UPPER('{schema}')
        AND table_type = 'BASE TABLE'
),
tagged_tables AS (
    SELECT COUNT(DISTINCT tr.object_name) AS cnt
    FROM snowflake.account_usage.tag_references tr
    JOIN {database}.information_schema.tables t
        ON UPPER(tr.object_name) = UPPER(t.table_name)
        AND UPPER(t.table_schema) = UPPER('{schema}')
        AND t.table_type = 'BASE TABLE'
    WHERE UPPER(tr.object_database) = UPPER('{database}')
        AND UPPER(tr.object_schema)   = UPPER('{schema}')
        AND tr.domain = 'TABLE'
)
SELECT
    tagged_tables.cnt AS numerator,
    table_count.cnt   AS denominator,
    tagged_tables.cnt::FLOAT / NULLIF(table_count.cnt::FLOAT, 0) AS value
FROM table_count, tagged_tables
""",
        },
        "column_masking": {
            "label": "Column masking (PII columns with masking policy)",
            "sql": """
WITH pii_columns AS (
    SELECT
        UPPER(c.table_name)  AS table_name,
        UPPER(c.column_name) AS column_name
    FROM {database}.information_schema.columns c
    JOIN {database}.information_schema.tables t
        ON c.table_catalog = t.table_catalog
        AND c.table_schema = t.table_schema
        AND c.table_name   = t.table_name
    WHERE UPPER(c.table_schema) = UPPER('{schema}')
        AND t.table_type = 'BASE TABLE'
        AND REGEXP_LIKE(LOWER(c.column_name), '(^|_)(email|phone|ssn|password|credit_card|address)($|_)')
),
masked_columns AS (
    SELECT DISTINCT
        UPPER(ref_entity_name) AS table_name,
        UPPER(ref_column_name) AS column_name
    FROM snowflake.account_usage.policy_references
    WHERE UPPER(ref_database_name) = UPPER('{database}')
        AND UPPER(ref_schema_name) = UPPER('{schema}')
        AND policy_kind = 'MASKING_POLICY'
)
SELECT
    COUNT(m.column_name) AS numerator,
    COUNT(*)             AS denominator,
    COUNT(m.column_name)::FLOAT / NULLIF(COUNT(*)::FLOAT, 0) AS value
FROM pii_columns pc
LEFT JOIN masked_columns m
    ON pc.table_name = m.table_name
   AND pc.column_name = m.column_name
""",
        },
    },
}

SIX_FACTOR_PASS_THRESHOLD = 0.50


def run_six_factor_check(database, schema, sql_template):
    sql = sql_template.format(database=database, schema=schema).strip()
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    result_row = None
    for stmt in statements:
        rows = session.sql(stmt).collect()
        if rows:
            result_row = rows[0].as_dict()
    if not result_row:
        return None, None, None
    value = result_row.get("VALUE")
    numerator = result_row.get("NUMERATOR")
    denominator = result_row.get("DENOMINATOR")
    return (float(value) if value is not None else None), numerator, denominator


@st.cache_data(show_spinner=False, ttl=3600)
def run_six_factor_scan(database, schemas):
    """Run the AI-Ready Data Framework's lightweight 'scan' profile (8 requirements,
    4 factors) against each schema in scope. Returns per-schema, per-requirement results."""
    results = []
    for schema in schemas:
        row = {"schema": schema}
        factor_scores = {}
        requirement_detail = []
        for factor, checks in SIX_FACTOR_CHECKS.items():
            req_values = []
            for req_key, req in checks.items():
                try:
                    value, num, denom = run_six_factor_check(database, schema, req["sql"])
                except Exception as exc:
                    value, num, denom = None, None, None
                    requirement_detail.append({
                        "factor": factor, "requirement": req_key, "label": req["label"],
                        "value": None, "numerator": None, "denominator": None,
                        "passed": None, "error": str(exc)[:200],
                    })
                    continue
                passed = (value >= SIX_FACTOR_PASS_THRESHOLD) if value is not None else None
                if value is not None:
                    req_values.append(value)
                requirement_detail.append({
                    "factor": factor, "requirement": req_key, "label": req["label"],
                    "value": value, "numerator": num, "denominator": denom,
                    "passed": passed, "error": None,
                })
            factor_scores[factor] = (sum(req_values) / len(req_values)) if req_values else None
        row["factor_scores"] = factor_scores
        row["requirement_detail"] = requirement_detail
        scored = [v for v in factor_scores.values() if v is not None]
        row["overall"] = (sum(scored) / len(scored)) if scored else None
        results.append(row)
    return results


def six_factor_tier(overall):
    if overall is None:
        return "N/A"
    if overall >= 0.70:
        return "High"
    if overall >= 0.40:
        return "Medium"
    return "Low"


# --------------------------------------------------------------------------------------
# Scoring logic (ported from the ai-readiness-score skill's scoring.py / recommendations.py)
# --------------------------------------------------------------------------------------

def classify_gap(pct_demand, n_cr_tables, pct_sv_coverage, avg_sv_quality):
    if pct_demand is None or n_cr_tables == 0:
        return "BUILD_CR_TABLES"
    if pct_demand < 0.5:
        return "BUILD_CR_TABLES"
    if pct_sv_coverage == 0:
        return "BUILD_SVS"
    if pct_sv_coverage < 0.5:
        return "EXPAND_SV_COVERAGE"
    if avg_sv_quality < 0.5:
        return "IMPROVE_SV_QUALITY"
    return "HEALTHY"


def compute_composite_scores(cr_results, sv_results):
    sv_signals = {}
    for row in sv_results:
        fqn = str(row.get("sv_fqn") or "")
        if not fqn:
            continue
        if fqn not in sv_signals:
            sv_signals[fqn] = {
                "has_pk": int(row.get("has_pk") or 0),
                "has_synonyms": int(row.get("has_synonyms") or 0),
                "has_unique_keys": int(row.get("has_unique_keys") or 0),
                "has_distinct_ranges": int(row.get("has_distinct_ranges") or 0),
                "has_relationships": int(row.get("has_relationships") or 0),
                "has_metrics": int(row.get("has_metrics") or 0),
                "n_verified_queries": int(row.get("n_verified_queries") or 0),
                "avg_comment_length": float(row.get("avg_comment_length") or 0),
                "quality_score": float(row.get("quality_score") or 0),
                "base_tables": [],
            }
        sv_signals[fqn]["base_tables"].append({
            "database": str(row.get("base_database") or ""),
            "schema": str(row.get("base_schema") or ""),
            "table": str(row.get("base_table") or ""),
        })

    all_scored = cr_results
    cr_tables = [r for r in all_scored if float(r.get("consumption_readiness_score") or 0) >= 0.80]
    cr_set = {(r["database_name"], r["schema_name"], r["table_name"]) for r in cr_tables}

    total_reads = sum(int(r.get("analytical_reads") or 0) for r in all_scored)
    reads_on_cr = sum(
        int(r.get("analytical_reads") or 0) for r in all_scored
        if (r["database_name"], r["schema_name"], r["table_name"]) in cr_set
    )
    pct_demand = (reads_on_cr / total_reads) if total_reads >= 10 else None

    sv_covered = {
        (bt["database"], bt["schema"], bt["table"])
        for sig in sv_signals.values()
        for bt in sig.get("base_tables", [])
        if (bt["database"], bt["schema"], bt["table"]) in cr_set
    }
    n_sv_covered = len(sv_covered)
    pct_sv_coverage = n_sv_covered / len(cr_set) if cr_set else 0.0

    relevant_fqns = {
        fqn for fqn, sig in sv_signals.items()
        if any((bt["database"], bt["schema"], bt["table"]) in cr_set for bt in sig.get("base_tables", []))
    }
    avg_sv_quality = (
        sum(sv_signals[f]["quality_score"] for f in relevant_fqns) / len(relevant_fqns)
        if relevant_fqns else 0.0
    )

    dc_100 = (pct_demand or 0.0) * 100
    sv_cov_100 = pct_sv_coverage * 100
    sv_qual_100 = avg_sv_quality * 100
    sv_readiness = math.sqrt(pct_sv_coverage * avg_sv_quality) * 100
    ai_readiness = ((pct_demand or 0.0) + math.sqrt(pct_sv_coverage * avg_sv_quality)) / 2.0 * 100

    gap = classify_gap(pct_demand, len(cr_set), pct_sv_coverage, avg_sv_quality)

    missing_dims = [
        label for flag, label in [
            ("has_pk", "primary keys"),
            ("has_synonyms", "synonyms"),
            ("has_metrics", "metrics"),
            ("has_relationships", "relationships"),
        ]
        if relevant_fqns and sum(sv_signals[f][flag] for f in relevant_fqns) / len(relevant_fqns) < 0.5
    ]

    sv_covered_set = sv_covered
    items = []
    top_targets = []

    if gap == "BUILD_CR_TABLES":
        schema_stats = defaultdict(lambda: {"total_reads": 0, "tables_read": 0, "cr_tables": 0, "cr_reads": 0})
        for r in all_scored:
            key = (r["database_name"], r["schema_name"])
            reads = int(r.get("analytical_reads") or 0)
            schema_stats[key]["total_reads"] += reads
            schema_stats[key]["tables_read"] += 1
            if (r["database_name"], r["schema_name"], r["table_name"]) in cr_set:
                schema_stats[key]["cr_tables"] += 1
                schema_stats[key]["cr_reads"] += reads

        schema_items = []
        for (db, schema), stats in schema_stats.items():
            if stats["total_reads"] < 10:
                continue
            uncovered_reads = stats["total_reads"] - stats["cr_reads"]
            schema_items.append({
                "type": "SCHEMA_GAP",
                "target": f"{db}.{schema}",
                "detail": f"{stats['total_reads']:,} reads across {stats['tables_read']} tables, {stats['cr_tables']} CR",
                "recommendation": f"Increase CR coverage \u2014 {uncovered_reads:,} reads land on non-CR tables.",
                "_sort_key": uncovered_reads,
            })
        schema_items.sort(key=lambda x: x["_sort_key"], reverse=True)
        for item in schema_items[:10]:
            del item["_sort_key"]
            items.append(item)
        top_targets = [item["target"] for item in items[:5]]

    elif gap in ("BUILD_SVS", "EXPAND_SV_COVERAGE"):
        uncovered = [
            r for r in all_scored
            if (r["database_name"], r["schema_name"], r["table_name"]) in cr_set
            and (r["database_name"], r["schema_name"], r["table_name"]) not in sv_covered_set
        ]
        uncovered.sort(key=lambda r: int(r.get("analytical_reads") or 0), reverse=True)
        for r in uncovered[:10]:
            items.append({
                "type": "UNCOVERED_CR_TABLE",
                "target": f"{r['database_name']}.{r['schema_name']}.{r['table_name']}",
                "detail": f"{int(r.get('analytical_reads') or 0):,} reads, {int(r.get('distinct_users') or 0)} distinct users",
                "recommendation": "Create a semantic view for this table.",
            })
        top_targets = [item["target"] for item in items[:5]]

    elif gap == "IMPROVE_SV_QUALITY":
        relevant_svs = [
            (fqn, sig) for fqn, sig in sv_signals.items()
            if any((bt["database"], bt["schema"], bt["table"]) in cr_set for bt in sig.get("base_tables", []))
            and sig["quality_score"] < 0.5
        ]
        relevant_svs.sort(key=lambda x: x[1]["quality_score"])
        for fqn, sig in relevant_svs[:10]:
            missing = []
            if not sig["has_pk"]:
                missing.append("primary key")
            if not sig["has_synonyms"]:
                missing.append("synonyms")
            if not sig["has_metrics"]:
                missing.append("metrics")
            if not sig["has_relationships"]:
                missing.append("relationships")
            if not sig["has_unique_keys"]:
                missing.append("unique keys")
            if not sig["n_verified_queries"]:
                missing.append("verified queries")
            items.append({
                "type": "SV_QUALITY_GAP",
                "target": fqn,
                "detail": f"Quality: {sig['quality_score'] * 100:.0f}/100",
                "recommendation": f"Add: {', '.join(missing[:4])}." if missing else "Improve SV metadata.",
            })

    return {
        "ai_readiness": round(ai_readiness, 2),
        "demand_coverage": round(dc_100, 2),
        "sv_readiness": round(sv_readiness, 2),
        "sv_coverage": round(sv_cov_100, 2),
        "sv_quality": round(sv_qual_100, 2),
        "n_cr_tables": len(cr_set),
        "gap": gap,
        "top_targets": top_targets,
        "missing_dims": missing_dims,
        "n_all_scored": len(all_scored),
        "n_sv": len(sv_signals),
        "n_sv_covered": n_sv_covered,
        "pct_demand_raw": pct_demand,
        "pct_sv_coverage_raw": pct_sv_coverage,
        "avg_sv_quality_raw": avg_sv_quality,
        "improvement_items": items,
    }


def build_recommendation(account_name, scores):
    composite = scores["ai_readiness"]
    gap = scores["gap"]
    pct_demand = scores["pct_demand_raw"]
    n_cr_tables = scores["n_cr_tables"]
    pct_sv_coverage = scores["pct_sv_coverage_raw"]
    n_sv_covered = scores["n_sv_covered"]
    avg_sv_quality = scores["avg_sv_quality_raw"]
    top_targets = scores["top_targets"]
    missing_dims = scores["missing_dims"]

    parts = []
    score_str = f"{composite:.0f}/100"
    if gap == "HEALTHY":
        parts.append(f"{account_name} scores {score_str} \u2014 all dimensions are healthy.")
    else:
        parts.append(f"{account_name} scores {score_str} (primary gap: {gap.replace('_', ' ')}).")

    dc_pct = round((pct_demand or 0) * 100)
    if pct_demand is not None and pct_demand >= 0.7:
        parts.append(f"Demand coverage is strong at {dc_pct}% ({n_cr_tables} CR tables).")
    elif pct_demand is not None and pct_demand >= 0.5:
        parts.append(f"Demand coverage is moderate at {dc_pct}% ({n_cr_tables} CR tables).")
    elif n_cr_tables == 0:
        parts.append("No consumption-ready tables exist.")
    else:
        top_str = ("; top areas: " + ", ".join(top_targets)) if top_targets else ""
        parts.append(f"Demand coverage is low at {dc_pct}% \u2014 most reads land on non-CR tables{top_str}.")

    if n_cr_tables > 0:
        sv_pct = round((pct_sv_coverage or 0) * 100)
        uncovered = n_cr_tables - n_sv_covered
        if (pct_sv_coverage or 0) == 0:
            parts.append(f"No semantic views cover any of the {n_cr_tables} CR tables.")
        elif pct_sv_coverage < 0.5:
            top_str = ("; top uncovered: " + ", ".join(top_targets)) if gap in ("BUILD_SVS", "EXPAND_SV_COVERAGE") and top_targets else ""
            parts.append(f"SV coverage is low at {sv_pct}% \u2014 {uncovered} CR tables lack semantic views{top_str}.")
        else:
            parts.append(f"SV coverage is good at {sv_pct}% ({n_sv_covered} of {n_cr_tables} CR tables).")

    if avg_sv_quality > 0:
        qual_str = f"{avg_sv_quality:.2f}/1.0"
        if avg_sv_quality < 0.5:
            dims_str = (f" \u2014 common gaps: {', '.join(missing_dims)}") if missing_dims else ""
            parts.append(f"SV quality averages {qual_str}{dims_str}.")
        else:
            parts.append(f"SV quality is good at {qual_str}.")

    quality_suffix = (" \u2014 add " + ", ".join(missing_dims)) if missing_dims else ""
    priorities = {
        "BUILD_CR_TABLES": "Priority: increase consumption-ready table coverage.",
        "BUILD_SVS": f"Priority: build semantic views for the {n_cr_tables} CR tables.",
        "EXPAND_SV_COVERAGE": f"Priority: expand SV coverage to the {n_cr_tables - n_sv_covered} uncovered CR tables.",
        "IMPROVE_SV_QUALITY": f"Priority: improve SV quality{quality_suffix}.",
        "HEALTHY": "No immediate action needed.",
    }
    parts.append(priorities.get(gap, ""))

    return " ".join(p for p in parts if p)


# --------------------------------------------------------------------------------------
# Data access helpers
# --------------------------------------------------------------------------------------

def _rows_to_dicts(rows):
    return [{k.lower(): v for k, v in r.as_dict().items()} for r in rows]


@st.cache_data(show_spinner=False, ttl=3600)
def run_cr_query(sample_pct, start_ts, end_ts, freshness_start_ts, database_filter):
    sample_predicate = f"AND MOD(ABS(HASH(ah.query_id) % 100), 100) < {sample_pct}" if sample_pct else ""
    db_predicate = ""
    if database_filter and database_filter != "All databases":
        safe_db = database_filter.replace("'", "''")
        db_predicate = f"AND UPPER(SPLIT_PART(f.value:objectName::string, '.', 1)) = UPPER('{safe_db}')"
    sql = CR_TABLES_SQL.format(
        sample_predicate=sample_predicate,
        start_ts=start_ts,
        end_ts=end_ts,
        freshness_start_ts=freshness_start_ts,
        db_predicate=db_predicate,
    )
    rows = session.sql(sql).collect()
    return _rows_to_dicts(rows)


@st.cache_data(show_spinner=False, ttl=3600)
def get_vqr_counts():
    """Describe every semantic view in the account to count verified queries."""
    show_rows = session.sql("SHOW SEMANTIC VIEWS IN ACCOUNT").collect()
    fqns = []
    seen = set()
    for r in show_rows:
        d = r["database_name"] + "." + r["schema_name"] + "." + r["name"]
        if d in seen:
            continue
        seen.add(d)
        quoted = (
            '"' + r["database_name"].replace('"', '""') + '"."'
            + r["schema_name"].replace('"', '""') + '"."'
            + r["name"].replace('"', '""') + '"'
        )
        fqns.append({"display": d, "quoted": quoted})

    vqr_map = {}
    for fqn in fqns:
        try:
            rows = session.sql(f"DESCRIBE SEMANTIC VIEW {fqn['quoted']}").collect()
            count = 0
            for row in rows:
                d = row.as_dict()
                kind = str(d.get("object_kind") or "").upper()
                if kind in ("AI_VERIFIED_QUERY", "VERIFIED_QUERY"):
                    count += 1
                elif kind == "EXTENSION" and str(d.get("object_name") or "").upper() == "CA" and str(d.get("property") or "").upper() == "VALUE":
                    import json as _json
                    try:
                        ext = _json.loads(d.get("property_value", "{}"))
                        count += len(ext.get("verified_queries", []))
                        count += len(ext.get("ai_verified_queries", []))
                    except Exception:
                        pass
            vqr_map[fqn["display"]] = count
        except Exception:
            vqr_map[fqn["display"]] = 0
    return vqr_map


@st.cache_data(show_spinner=False, ttl=3600)
def run_sv_query(vqr_map_items):
    vqr_map = dict(vqr_map_items)
    if vqr_map:
        vqr_unions = " UNION ALL ".join(
            f"SELECT '{fqn.replace(chr(39), chr(39) + chr(39))}' AS sv_fqn, {count} AS n_verified_queries"
            for fqn, count in vqr_map.items()
        )
        vqr_source = vqr_unions
    else:
        vqr_source = "SELECT NULL AS sv_fqn, NULL AS n_verified_queries WHERE 1=0"
    sql = SV_QUALITY_SQL.format(vqr_source=vqr_source)
    rows = session.sql(sql).collect()
    return _rows_to_dicts(rows)


def find_sv_covered_tables(database_filter):
    """Base tables covered by existing semantic views, scoped to database_filter."""
    where = ""
    if database_filter and database_filter != "All databases":
        safe_db = database_filter.replace("'", "''")
        where = f"AND UPPER(st.BASE_TABLE_DATABASE_NAME) = UPPER('{safe_db}')"
    rows = session.sql(
        f"""
        SELECT DISTINCT
            st.BASE_TABLE_DATABASE_NAME AS db, st.BASE_TABLE_SCHEMA_NAME AS sch, st.BASE_TABLE_NAME AS tbl
        FROM SNOWFLAKE.ACCOUNT_USAGE.SEMANTIC_VIEWS sv
        JOIN SNOWFLAKE.ACCOUNT_USAGE.SEMANTIC_TABLES st ON sv.SEMANTIC_VIEW_ID = st.SEMANTIC_VIEW_ID
        WHERE sv.DELETED IS NULL AND st.DELETED IS NULL
          AND st.BASE_TABLE_NAME IS NOT NULL
          {where}
        """
    ).collect()
    return [(r["DB"], r["SCH"], r["TBL"]) for r in rows]


def generate_demo_traffic(database_filter):
    """Run real SELECT queries (from within this Streamlit app) against SV-covered
    tables so ACCESS_HISTORY records genuine, BI-tool-tagged analytical demand.

    Larger tables receive more query variants (mimicking real BI behaviour where
    fact tables attract heavier analytical traffic), which breaks PERCENT_RANK
    ties in the consumption signal.
    """
    tables = find_sv_covered_tables(database_filter)
    if not tables:
        return 0, []

    # Probe row counts to weight traffic realistically
    table_sizes = {}
    for db, sch, tbl in tables:
        fqn = f'"{db}"."{sch}"."{tbl}"'
        try:
            row = session.sql(f"SELECT COUNT(*) AS n FROM {fqn}").collect()
            table_sizes[(db, sch, tbl)] = row[0]["N"]
        except Exception:
            table_sizes[(db, sch, tbl)] = 0

    # Assign traffic tiers: large (>=1000 rows) → 10 variants,
    # medium (>=100) → 6, small → 3
    n_queries = 0
    for db, sch, tbl in tables:
        fqn = f'"{db}"."{sch}"."{tbl}"'
        row_count = table_sizes[(db, sch, tbl)]

        base_variants = [
            f"SELECT COUNT(*) FROM {fqn}",
            f"SELECT * FROM {fqn} LIMIT 10",
            f"SELECT * FROM {fqn} ORDER BY 1 LIMIT 5",
        ]
        medium_variants = [
            f"SELECT * FROM {fqn} LIMIT 25",
            f"SELECT * FROM {fqn} ORDER BY 1 DESC LIMIT 5",
            f"SELECT * FROM {fqn} SAMPLE (50)",
        ]
        large_variants = [
            f"SELECT COUNT(DISTINCT *) FROM (SELECT * FROM {fqn} LIMIT 500)",
            f"SELECT * FROM {fqn} LIMIT 50",
            f"SELECT * FROM {fqn} ORDER BY 1 LIMIT 20",
            f"SELECT * FROM {fqn} ORDER BY 1 DESC LIMIT 20",
        ]

        if row_count >= 1000:
            variants = base_variants + medium_variants + large_variants
        elif row_count >= 100:
            variants = base_variants + medium_variants
        else:
            variants = base_variants

        for q in variants:
            try:
                session.sql(q).collect()
                n_queries += 1
            except Exception:
                pass
    return n_queries, tables


def run_full_scan(sample_pct, database_filter):
    now = datetime.now(timezone.utc)
    start_ts = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    end_ts = now.strftime("%Y-%m-%d %H:%M:%S")
    freshness_start_ts = (now - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")

    progress = st.empty()
    with st.spinner("Running AI Readiness scan\u2026"):
        progress.write("\U0001F50D Scoring table consumption readiness (CR tables)\u2026")
        cr_results = run_cr_query(sample_pct, start_ts, end_ts, freshness_start_ts, database_filter)
        progress.write(f"\u2705 {len(cr_results):,} tables scored")

        progress.write("\U0001F9E9 Scanning semantic views for verified queries\u2026")
        vqr_map = get_vqr_counts()
        progress.write(f"\u2705 {len(vqr_map):,} semantic views scanned")

        progress.write("\U0001F48E Scoring semantic view quality\u2026")
        sv_results = run_sv_query(tuple(sorted(vqr_map.items())))
        progress.write(f"\u2705 {len(sv_results):,} SV \u00d7 base-table rows scored")
    progress.empty()

    scores = compute_composite_scores(cr_results, sv_results)
    scores["cr_results"] = cr_results
    scores["run_date"] = now.strftime("%Y-%m-%d %H:%M UTC")
    scores["sample_pct"] = sample_pct
    scores["database_filter"] = database_filter
    return scores


def save_run_to_history(scores, account_name, role_name):
    """Persist this scan's results to SCAN_RUNS / SCAN_IMPROVEMENT_ITEMS."""
    def esc(v):
        if v is None:
            return "NULL"
        return "'" + str(v).replace("'", "''") + "'"

    recommendation_text = build_recommendation(str(account_name), scores)
    db_filter = scores.get("database_filter") or "All databases"

    insert_run_sql = f"""
        INSERT INTO AI_READINESS_APP.PUBLIC.SCAN_RUNS
            (run_id, account_name, role_name, database_filter, sample_pct,
             ai_readiness, demand_coverage, sv_readiness, sv_coverage, sv_quality,
             n_cr_tables, gap, recommendation_text, n_all_scored, n_sv, n_sv_covered)
        SELECT UUID_STRING(), {esc(account_name)}, {esc(role_name)}, {esc(db_filter)},
            {scores['sample_pct'] if scores.get('sample_pct') else 'NULL'},
            {scores['ai_readiness']}, {scores['demand_coverage']}, {scores['sv_readiness']},
            {scores['sv_coverage']}, {scores['sv_quality']}, {scores['n_cr_tables']},
            {esc(scores['gap'])}, {esc(recommendation_text)},
            {scores['n_all_scored']}, {scores['n_sv']}, {scores['n_sv_covered']}
    """
    session.sql(insert_run_sql).collect()

    run_id_row = session.sql(
        "SELECT run_id FROM AI_READINESS_APP.PUBLIC.SCAN_RUNS ORDER BY run_ts DESC LIMIT 1"
    ).collect()
    run_id = run_id_row[0]["RUN_ID"]

    items = scores.get("improvement_items") or []
    if items:
        values_sql = ", ".join(
            f"({esc(run_id)}, {esc(it.get('type'))}, {esc(it.get('target'))}, "
            f"{esc(it.get('detail'))}, {esc(it.get('recommendation'))})"
            for it in items
        )
        session.sql(
            f"INSERT INTO AI_READINESS_APP.PUBLIC.SCAN_IMPROVEMENT_ITEMS "
            f"(run_id, item_type, target, detail, recommendation) VALUES {values_sql}"
        ).collect()

    # Generate and upload HTML report
    try:
        from datetime import datetime, timezone
        report_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        html_content = render_report_html(
            account_name=str(account_name),
            role=str(role_name),
            run_date=report_date,
            ai_readiness=scores['ai_readiness'],
            demand_coverage=scores['demand_coverage'],
            sv_readiness=scores['sv_readiness'],
            sv_coverage=scores['sv_coverage'],
            sv_quality=scores['sv_quality'],
            n_cr_tables=scores['n_cr_tables'],
            gap=scores['gap'],
            recommendation=recommendation_text,
            improvement_items=items,
            sample_pct=scores.get('sample_pct'),
            database_filter=scores.get('database_filter', 'All databases'),
        )
        # Write to temp file and PUT to stage
        import tempfile, os
        report_filename = f"ai_readiness_report_{report_date}_{run_id[:8]}.html"
        tmp_path = os.path.join(tempfile.gettempdir(), report_filename)
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        session.sql(f"PUT 'file://{tmp_path}' @AI_READINESS_APP.PUBLIC.APP_STAGE/reports/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE").collect()
        # Also upload as latest
        latest_path = os.path.join(tempfile.gettempdir(), "ai_readiness_report_latest.html")
        with open(latest_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        session.sql(f"PUT 'file://{latest_path}' @AI_READINESS_APP.PUBLIC.APP_STAGE/reports/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE").collect()
        # Update SCAN_RUNS with the report path
        stage_path = f"@AI_READINESS_APP.PUBLIC.APP_STAGE/reports/{report_filename}"
        session.sql(f"UPDATE AI_READINESS_APP.PUBLIC.SCAN_RUNS SET report_html_path = '{stage_path}' WHERE run_id = '{run_id}'").collect()
        os.unlink(tmp_path)
    except Exception as exc:
        pass  # Report generation is best-effort; don't break the scan

    return run_id


def load_run_history(database_filter=None):
    where = ""
    if database_filter and database_filter != "All databases":
        safe_db = database_filter.replace("'", "''")
        where = f"WHERE database_filter = '{safe_db}'"
    rows = session.sql(
        f"""
        SELECT run_id, run_ts, account_name, role_name, database_filter, sample_pct,
               ai_readiness, demand_coverage, sv_readiness, sv_coverage, sv_quality,
               n_cr_tables, gap, recommendation_text, n_all_scored, n_sv, n_sv_covered,
               report_html_path
        FROM AI_READINESS_APP.PUBLIC.SCAN_RUNS
        {where}
        ORDER BY run_ts DESC
        """
    ).collect()
    return _rows_to_dicts(rows)


def load_run_items(run_id):
    rows = session.sql(
        f"""
        SELECT item_type, target, detail, recommendation
        FROM AI_READINESS_APP.PUBLIC.SCAN_IMPROVEMENT_ITEMS
        WHERE run_id = '{run_id}'
        """
    ).collect()
    return _rows_to_dicts(rows)


# --------------------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------------------

st.title("\U0001F916 AI Readiness Score")
st.caption("Consumption-Ready tables \u00d7 Semantic View coverage/quality \u2192 composite score")
st.markdown(
    "Measures how ready a customer/account is for AI products by scoring two things:\n"
    "- Whether analytical demand is concentrated on well-structured consumption-ready (CR) tables\n"
    "- Whether those tables are properly modeled in semantic views (SVs)\n\n"
    "**AI readiness score = (Demand Coverage + SV Readiness) / 2** where "
    "**SV Readiness = (SV Coverage \u00d7 SV quality)^0.5**\n\n"
    "More details in: [AI Readiness Documentation]"
    "(https://docs.google.com/document/u/0/d/141iiBiZdVAEYL7kTIiOUt0Ki9Mh4DT_pPCLypmX4Xts)"
)

with st.expander("\u2139\uFE0F AI Readiness Overview \u2014 how the score works"):
    st.markdown(
        """
This score is built on five dimensions, computed from `snowflake.account_usage`:

| Dimension | What it measures | Formula |
|---|---|---|
| **Demand Coverage** | % of analytical reads landing on consumption-ready (CR) tables | `reads_on_cr / total_reads \u00d7 100` |
| **SV Coverage** | % of CR tables covered by \u22651 semantic view | `cr_tables_with_sv / total_cr_tables \u00d7 100` |
| **SV Quality** | Average quality of semantic views on a 9-point scale | `(6 binary signals + VQR saturation + comment depth) / 9 \u00d7 100` |
| **SV Readiness** | Combined signal of coverage and quality | `\u221a(SV Coverage \u00d7 SV Quality) \u00d7 100` |
| **AI Readiness Composite** | Overall score, 0\u2013100 | `(Demand Coverage + SV Readiness) / 2` |

**What makes a table "Consumption-Ready" (CR)?**

A table's Consumption Readiness Score is a weighted (Cobb-Douglas) blend of four signals,
computed only for tables with \u22655 analytical reads in the last 7 days. A table needs a
score \u2265 0.80 to count as CR:

| Signal | Weight | What it captures |
|---|---|---|
| Activity | 35% | Read volume, relative to other scored tables |
| Consumption | 30% | Audience breadth \u2014 distinct users *or* usage from a recognized BI/dashboard tool (Looker, Tableau, Power BI, Streamlit, etc.) |
| Speed | 20% | Query latency (faster = better; based on median execution time) |
| Freshness | 15% | Days since the table was last altered (decays on a ~30-day half-life) |

**The 6 SV quality signals** (each worth 1 of 9 points, plus 2 points for verified-query
saturation and 1 point for comment depth):
- Has a primary key
- Has synonyms (on the table, a dimension, fact, or metric)
- Has unique keys
- Has distinct-range constraints
- Has at least one relationship to another table
- Has at least one metric defined

**Gap classification** (waterfall, checked in order):
```
Demand Coverage < 50% (or 0 CR tables)  \u2192  BUILD_CR_TABLES
SV Coverage = 0                         \u2192  BUILD_SVS
SV Coverage < 50%                       \u2192  EXPAND_SV_COVERAGE
SV Quality < 50%                        \u2192  IMPROVE_SV_QUALITY
All thresholds met                      \u2192  HEALTHY
```

*This app's scoring methodology is sourced from the canonical `ai-readiness-score` skill
(demand coverage + SV coverage/quality only \u2014 a narrower, table/semantic-view-focused check).*

*For the full 6-factor assessment \u2014 Clean, Contextual, Consumable, Current, Correlated,
Compliant \u2014 see the **6-Factor Scan** tab, or install Snowflake Labs'*
[AI-Ready Data Framework](https://github.com/Snowflake-Labs/ai-ready-data)
*(`ai-ready-data` Cortex Code skill) for the complete 62 requirements and 5 workload
profiles (scan, RAG, agents, feature-serving, training).*
"""
    )


with st.sidebar:
    st.header("Scan settings")
    account_name = session.sql("SELECT CURRENT_ACCOUNT() AS a").collect()[0]["A"]
    role_name = session.sql("SELECT CURRENT_ROLE() AS r").collect()[0]["R"]
    st.markdown(f"**Account:** `{account_name}`  \n**Role:** `{role_name}`")

    db_rows = session.sql("SHOW DATABASES").collect()
    db_names = sorted({r["name"] for r in db_rows if r["kind"] in ("STANDARD", "IMPORTED DATABASE")})
    db_options = ["All databases"] + db_names
    default_db = "AI_READINESS_APP"
    default_index = db_options.index(default_db) if default_db in db_options else 0
    database_filter = st.selectbox("Database scope", options=db_options, index=default_index)

    sample_choice = st.selectbox(
        "Sample size",
        options=["10%", "30% (default)", "50%", "Full scan (100%)"],
        index=1,
    )
    if "Full" in sample_choice:
        sample_pct = None
    else:
        sample_pct = int(sample_choice.split("%")[0])
    run_clicked = st.button("\U0001F680 Run scan", type="primary", use_container_width=True)
    st.caption("Results are cached for an hour per sample size + database scope.")

    with st.expander("\U0001F3AC Demo helper"):
        st.caption(
            "Scoring 0 with no CR tables? Generate real query traffic against tables "
            "that already have semantic views in this scope, tagged as coming from "
            "this app (counts toward the demand-coverage signal). ACCOUNT_USAGE has "
            "ingestion latency (often 15-45 min) before a rerun reflects it."
        )
        demo_clicked = st.button("Generate demo traffic", use_container_width=True)

if demo_clicked:
    with st.spinner("Generating demo traffic\u2026"):
        n_queries, demo_tables = generate_demo_traffic(database_filter)
    if n_queries:
        st.success(
            f"Ran {n_queries} queries against {len(demo_tables)} semantic-view-covered "
            f"table(s). Wait ~15-45 min for ACCOUNT_USAGE to catch up, then click **Run scan**."
        )
    else:
        st.warning("No semantic-view-covered tables found in this scope to generate traffic against.")

if run_clicked:
    st.session_state["scores"] = run_full_scan(sample_pct, database_filter)
    st.session_state["last_run_id"] = save_run_to_history(
        st.session_state["scores"], account_name, role_name
    )
    # Generate HTML report for inline display
    try:
        _sc = st.session_state["scores"]
        _rec = build_recommendation(str(account_name), _sc)
        st.session_state["report_html"] = render_report_html(
            account_name=str(account_name),
            role=str(role_name),
            run_date=_sc.get("run_date", ""),
            ai_readiness=_sc["ai_readiness"],
            demand_coverage=_sc["demand_coverage"],
            sv_readiness=_sc["sv_readiness"],
            sv_coverage=_sc["sv_coverage"],
            sv_quality=_sc["sv_quality"],
            n_cr_tables=_sc["n_cr_tables"],
            gap=_sc["gap"],
            recommendation=_rec,
            improvement_items=_sc.get("improvement_items", []),
            sample_pct=_sc.get("sample_pct"),
            database_filter=_sc.get("database_filter", "All databases"),
        )
    except Exception:
        st.session_state["report_html"] = None

scores = st.session_state.get("scores")

tab_current, tab_history, tab_six_factor = st.tabs(
    ["\U0001F4CA Current Scan", "\U0001F553 Run History", "\U0001F9EC 6-Factor Scan"]
)

with tab_current:
    if not scores:
        st.info("Choose a database scope and sample size, then click **Run scan**.")
    else:
        # --- Metric cards ---
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("\U0001F916 AI Readiness", f"{scores['ai_readiness']:.0f}/100")
        c2.metric("\U0001F4C8 Demand Coverage", f"{scores['demand_coverage']:.0f}/100")
        c3.metric("\U0001F9E9 SV Readiness", f"{scores['sv_readiness']:.0f}/100")
        c4.metric("\U0001F5FA\uFE0F SV Coverage", f"{scores['sv_coverage']:.0f}/100")
        c5.metric("\U0001F48E SV Quality", f"{scores['sv_quality']:.0f}/100")
        c6.metric("\U0001F4E6 CR Tables", f"{scores['n_cr_tables']}")

        st.divider()

        # --- Charts ---
        col_radar, col_bar = st.columns(2)

        metric_labels = ["AI Readiness", "Demand Coverage", "SV Readiness", "SV Coverage", "SV Quality"]
        metric_values = [
            scores["ai_readiness"], scores["demand_coverage"], scores["sv_readiness"],
            scores["sv_coverage"], scores["sv_quality"],
        ]
        healthy_threshold = [70, 70, 70, 70, 70]

        with col_radar:
            fig = go.Figure()
            fig.add_trace(go.Scatterpolar(r=metric_values + [metric_values[0]], theta=metric_labels + [metric_labels[0]],
                                           fill="toself", name="Your account"))
            fig.add_trace(go.Scatterpolar(r=healthy_threshold + [healthy_threshold[0]], theta=metric_labels + [metric_labels[0]],
                                           fill="none", name="Healthy threshold", line=dict(dash="dash")))
            fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 100])), showlegend=True,
                               title="Score profile", margin=dict(t=60, b=20))
            st.plotly_chart(fig, use_container_width=True)

        with col_bar:
            fig2 = go.Figure(go.Bar(x=metric_values, y=metric_labels, orientation="h",
                                     marker_color="#29B5E8"))
            fig2.update_layout(title="Score breakdown", xaxis=dict(range=[0, 100]), margin=dict(t=60, b=20))
            st.plotly_chart(fig2, use_container_width=True)

        st.divider()

        # --- Recommendation ---
        st.subheader("\U0001F3AF Recommendation")
        recommendation_text = build_recommendation(str(account_name), scores)
        gap = scores["gap"]
        if gap == "HEALTHY":
            st.success(recommendation_text)
        else:
            st.warning(f"**Primary Gap: {gap}**\n\n{recommendation_text}")

        # --- Improvement opportunities ---
        st.subheader("\U0001F6E0\uFE0F Top Improvement Opportunities")
        items = scores.get("improvement_items", [])
        if items:
            df = pd.DataFrame(items)[["type", "target", "detail", "recommendation"]]
            df.columns = ["Type", "Target", "Detail", "Recommendation"]
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.write("No improvement items \u2014 account is healthy or no data was scored.")

        # --- HTML Report ---
        report_html = st.session_state.get("report_html")
        if report_html:
            st.divider()
            st.subheader("\U0001F4C4 AI Readiness Report")
            st.caption("Matching the bundled `ai-readiness-score` skill report format — download or preview below.")
            col_dl, col_spacer = st.columns([1, 3])
            with col_dl:
                st.download_button(
                    "\u2B07\uFE0F Download HTML report",
                    data=report_html,
                    file_name=f"ai_readiness_report_{scores.get('run_date', 'latest').replace(' ', '_').replace(':', '')}.html",
                    mime="text/html",
                    use_container_width=True,
                )
            with st.expander("Preview report", expanded=False):
                import streamlit.components.v1 as components
                components.html(report_html, height=800, scrolling=True)

        st.divider()
        st.caption(
            f"Scope: {scores.get('database_filter', 'All databases')}  \u00b7  "
            f"Scan run: {scores.get('run_date', '')}  \u00b7  "
            f"Sample: {(str(scores['sample_pct']) + '%') if scores.get('sample_pct') else 'Full scan'}  \u00b7  "
            f"{scores['n_all_scored']} tables scanned, {scores['n_sv']} semantic views scanned"
        )

with tab_history:
    st.subheader("\U0001F553 Run History")
    with st.expander("\u2139\uFE0F How Run History works"):
        st.markdown(
            """
**Data source:** Every scan persists its results to two tables in
`AI_READINESS_APP.PUBLIC`:

| Table | What it stores |
|---|---|
| `SCAN_RUNS` | One row per scan: composite scores, gap classification, recommendation text, scope/sample metadata |
| `SCAN_IMPROVEMENT_ITEMS` | Per-table/SV improvement actions linked to a run via `run_id` |

**Scoring inputs come from `snowflake.account_usage`** (ACCESS_HISTORY,
QUERY_HISTORY, SESSIONS, TABLES, SEMANTIC_VIEWS, etc.), which have
**15\u201345 min ingestion latency**. A score reflects the account state at
scan time minus that lag \u2014 not real-time.

**Design principles:**

1. **Append-only** \u2014 runs are never updated or deleted; each scan is an
   immutable snapshot so you can track progress over time.
2. **Scope-partitioned** \u2014 runs are tagged with the database filter used,
   so you can compare apples-to-apples across reruns of the same scope.
3. **Gap waterfall** \u2014 each run classifies the single most impactful gap
   (`BUILD_CR_TABLES` \u2192 `BUILD_SVS` \u2192 `EXPAND_SV_COVERAGE` \u2192
   `IMPROVE_SV_QUALITY` \u2192 `HEALTHY`), giving a clear next action.
4. **Trend line** \u2014 the chart above plots AI Readiness, Demand Coverage,
   and SV Readiness over time so you can show before/after impact of
   building SVs, adding VQRs, or generating traffic.
"""
        )
    history_scope = st.selectbox(
        "Filter by database scope", options=db_options, index=default_index, key="history_scope"
    )
    history = load_run_history(history_scope)

    if not history:
        st.info("No past runs yet for this scope. Run a scan to start building history.")
    else:
        hist_df = pd.DataFrame(history)
        hist_df["run_ts"] = pd.to_datetime(hist_df["run_ts"])
        hist_df = hist_df.sort_values("run_ts")

        fig_trend = go.Figure()
        fig_trend.add_trace(go.Scatter(
            x=hist_df["run_ts"], y=hist_df["ai_readiness"], mode="lines+markers", name="AI Readiness"
        ))
        fig_trend.add_trace(go.Scatter(
            x=hist_df["run_ts"], y=hist_df["demand_coverage"], mode="lines+markers", name="Demand Coverage"
        ))
        fig_trend.add_trace(go.Scatter(
            x=hist_df["run_ts"], y=hist_df["sv_readiness"], mode="lines+markers", name="SV Readiness"
        ))
        fig_trend.update_layout(title="Score trend over time", yaxis=dict(range=[0, 100]), margin=dict(t=60, b=20))
        st.plotly_chart(fig_trend, use_container_width=True)

        display_df = hist_df.sort_values("run_ts", ascending=False)[
            ["run_ts", "database_filter", "ai_readiness", "demand_coverage",
             "sv_readiness", "sv_coverage", "sv_quality", "n_cr_tables", "gap"]
        ].copy()
        display_df.columns = ["Run Time", "Scope", "AI Readiness", "Demand Cov", "SV Readiness",
                               "SV Coverage", "SV Quality", "CR Tables", "Gap"]
        st.dataframe(display_df, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("**Inspect a past run**")
        run_labels = [
            f"{r['run_ts']} \u2014 {r['database_filter']} \u2014 score {r['ai_readiness']:.0f} \u2014 {r['gap']}"
            for r in history
        ]
        selected_idx = st.selectbox("Select a run", options=range(len(history)), format_func=lambda i: run_labels[i])
        selected_run = history[selected_idx]

        rc1, rc2, rc3, rc4, rc5, rc6 = st.columns(6)
        rc1.metric("AI Readiness", f"{selected_run['ai_readiness']:.0f}/100")
        rc2.metric("Demand Coverage", f"{selected_run['demand_coverage']:.0f}/100")
        rc3.metric("SV Readiness", f"{selected_run['sv_readiness']:.0f}/100")
        rc4.metric("SV Coverage", f"{selected_run['sv_coverage']:.0f}/100")
        rc5.metric("SV Quality", f"{selected_run['sv_quality']:.0f}/100")
        rc6.metric("CR Tables", f"{selected_run['n_cr_tables']}")

        gap_r = selected_run["gap"]
        if gap_r == "HEALTHY":
            st.success(selected_run["recommendation_text"])
        else:
            st.warning(f"**Primary Gap: {gap_r}**\n\n{selected_run['recommendation_text']}")

        if selected_run.get("report_html_path"):
            st.divider()
            st.subheader("\U0001F4C4 HTML Report")
            report_path = selected_run["report_html_path"]
            try:
                import tempfile, os
                local_dir = tempfile.mkdtemp()
                session.sql(
                    f"GET '{report_path}' 'file://{local_dir}/'"
                ).collect()
                local_file = os.path.join(local_dir, os.path.basename(report_path))
                with open(local_file, "r", encoding="utf-8") as f:
                    past_html = f.read()
                col_dl2, col_spacer2 = st.columns([1, 3])
                with col_dl2:
                    st.download_button(
                        "\u2B07\uFE0F Download HTML report",
                        data=past_html,
                        file_name=os.path.basename(report_path),
                        mime="text/html",
                        use_container_width=True,
                        key=f"dl_{selected_run['run_id']}",
                    )
                with st.expander("Preview report", expanded=False):
                    import streamlit.components.v1 as components
                    components.html(past_html, height=800, scrolling=True)
                os.unlink(local_file)
            except Exception as exc:
                st.caption(f"Report saved at: `{report_path}` (preview unavailable: {exc})")

        run_items = load_run_items(selected_run["run_id"])
        if run_items:
            items_df = pd.DataFrame(run_items)[["item_type", "target", "detail", "recommendation"]]
            items_df.columns = ["Type", "Target", "Detail", "Recommendation"]
            st.dataframe(items_df, use_container_width=True, hide_index=True)
        else:
            st.write("No improvement items recorded for this run.")

with tab_six_factor:
    st.subheader("\U0001F9EC 6-Factor Scan \u2014 AI-Ready Data Framework")
    st.caption(
        "A complementary, broader assessment from Snowflake Labs' "
        "[AI-Ready Data Framework](https://github.com/Snowflake-Labs/ai-ready-data). "
        "This runs a lightweight scan profile (13 requirements across all 6 factors) "
        "for estate-level prioritization. It is a different scoring system from "
        "the CR/SV composite score in the other tabs \u2014 this one checks cleanliness, "
        "context, consumability, freshness, lineage, and governance independent of query demand."
    )
    with st.expander("Which factors/requirements does this cover?"):
        st.markdown(
            """
The **6 Factors of AI-Ready Data** ([Snowflake Labs](https://github.com/Snowflake-Labs/ai-ready-data)):

| # | Factor | What it means | Requirements in this scan |
|---|---|---|---|
| 0 | **Clean** | Data is accurate, complete, and free of errors | `data_completeness`, `uniqueness`, `referential_integrity` |
| 1 | **Contextual** | Meaning is explicit and machine-readable | `semantic_documentation`, `entity_identifier_declaration`, `schema_type_coverage` |
| 2 | **Consumable** | Data is served in the right format/latency for AI | `access_optimization` |
| 3 | **Current** | Data reflects the present state | `change_detection`, `data_freshness` |
| 4 | **Correlated** | Data is traceable from source to decision | `data_provenance`, `lineage_completeness` |
| 5 | **Compliant** | Data is governed with enforced access boundaries | `classification`, `column_masking` |

| Factor | Requirement | What it checks |
|---|---|---|
| Clean | `data_completeness` | % of columns declared NOT NULL |
| Clean | `uniqueness` | % of tables with a PK or UNIQUE constraint |
| Clean | `referential_integrity` | % of tables with `_id` columns that have FK constraints |
| Contextual | `semantic_documentation` | % of base tables covered by a semantic view |
| Contextual | `entity_identifier_declaration` | % of base tables with a PK/UNIQUE constraint |
| Contextual | `schema_type_coverage` | % of columns with a comment or recognizable name pattern |
| Consumable | `access_optimization` | % of large tables (>10K rows) with a clustering key |
| Current | `change_detection` | % of tables with change tracking enabled |
| Current | `data_freshness` | % of tables altered within the last 7 days |
| Correlated | `data_provenance` | % of tables read by at least one downstream query (last 30 days) |
| Correlated | `lineage_completeness` | % of tables with upstream write history (last 30 days) |
| Compliant | `classification` | % of tables with a governance tag applied |
| Compliant | `column_masking` | % of PII-candidate columns with a masking policy |

*For the full 62 requirements and deeper profiles (RAG, agents, feature-serving, training),
install the `ai-ready-data` Cortex Code skill.*
"""
        )

    six_factor_db = st.selectbox(
        "Database", options=db_names, index=db_names.index("AI_READINESS_APP") if "AI_READINESS_APP" in db_names else 0,
        key="six_factor_db",
    )
    schema_rows = session.sql(f"SHOW SCHEMAS IN DATABASE {six_factor_db}").collect()
    schema_names = sorted({
        r["name"] for r in schema_rows
        if r["name"] not in ("INFORMATION_SCHEMA",)
    })
    six_factor_schemas = st.multiselect(
        "Schemas to scan", options=schema_names, default=schema_names, key="six_factor_schemas"
    )
    six_factor_run = st.button("\U0001F9EC Run 6-factor scan", type="primary")

    if six_factor_run:
        if not six_factor_schemas:
            st.warning("Select at least one schema.")
        else:
            with st.spinner("Running 6-factor scan\u2026"):
                st.session_state["six_factor_results"] = run_six_factor_scan(
                    six_factor_db, tuple(six_factor_schemas)
                )
                st.session_state["six_factor_db_used"] = six_factor_db

    six_factor_results = st.session_state.get("six_factor_results")

    if not six_factor_results:
        st.info("Choose a database and schema(s), then click **Run 6-factor scan**.")
    else:
        st.caption(f"Scanned database: `{st.session_state.get('six_factor_db_used')}`")

        # --- Portfolio ranking table ---
        portfolio_rows = []
        for r in six_factor_results:
            fs = r["factor_scores"]
            portfolio_rows.append({
                "Schema": r["schema"],
                "Overall": round(r["overall"] * 100, 1) if r["overall"] is not None else None,
                "Tier": six_factor_tier(r["overall"]),
                "Clean": round(fs.get("Clean") * 100, 1) if fs.get("Clean") is not None else None,
                "Contextual": round(fs.get("Contextual") * 100, 1) if fs.get("Contextual") is not None else None,
                "Consumable": round(fs.get("Consumable") * 100, 1) if fs.get("Consumable") is not None else None,
                "Current": round(fs.get("Current") * 100, 1) if fs.get("Current") is not None else None,
                "Correlated": round(fs.get("Correlated") * 100, 1) if fs.get("Correlated") is not None else None,
                "Compliant": round(fs.get("Compliant") * 100, 1) if fs.get("Compliant") is not None else None,
            })
        portfolio_df = pd.DataFrame(portfolio_rows).sort_values("Overall", ascending=False, na_position="last")
        st.dataframe(portfolio_df, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("**Drill into a schema**")
        schema_options = [r["schema"] for r in six_factor_results]
        selected_schema = st.selectbox("Schema", options=schema_options, key="six_factor_drill_schema")
        selected_result = next(r for r in six_factor_results if r["schema"] == selected_schema)

        fs = selected_result["factor_scores"]
        fc1, fc2, fc3, fc4, fc5, fc6, fc7 = st.columns(7)
        overall_val = selected_result["overall"]
        fc1.metric("Overall", f"{overall_val * 100:.0f}/100" if overall_val is not None else "N/A")
        fc2.metric("Clean", f"{fs['Clean'] * 100:.0f}/100" if fs.get("Clean") is not None else "N/A")
        fc3.metric("Contextual", f"{fs['Contextual'] * 100:.0f}/100" if fs.get("Contextual") is not None else "N/A")
        fc4.metric("Consumable", f"{fs['Consumable'] * 100:.0f}/100" if fs.get("Consumable") is not None else "N/A")
        fc5.metric("Current", f"{fs['Current'] * 100:.0f}/100" if fs.get("Current") is not None else "N/A")
        fc6.metric("Correlated", f"{fs['Correlated'] * 100:.0f}/100" if fs.get("Correlated") is not None else "N/A")
        fc7.metric("Compliant", f"{fs['Compliant'] * 100:.0f}/100" if fs.get("Compliant") is not None else "N/A")

        factor_labels = [k for k in fs.keys() if fs[k] is not None]
        factor_values = [fs[k] * 100 for k in factor_labels]
        if factor_values:
            fig_ff = go.Figure(go.Bar(x=factor_values, y=factor_labels, orientation="h", marker_color="#7B61FF"))
            fig_ff.update_layout(title=f"Factor breakdown \u2014 {selected_schema}", xaxis=dict(range=[0, 100]), margin=dict(t=60, b=20))
            st.plotly_chart(fig_ff, use_container_width=True)

        st.markdown("**Per-requirement detail**")
        detail_rows = []
        for d in selected_result["requirement_detail"]:
            detail_rows.append({
                "Factor": d["factor"],
                "Requirement": d["requirement"],
                "Description": d["label"],
                "Value": f"{d['value']:.2f}" if d["value"] is not None else ("N/A" if not d["error"] else "Error"),
                "Numerator/Denominator": (
                    f"{d['numerator']}/{d['denominator']}" if d["numerator"] is not None and d["denominator"] is not None else "\u2014"
                ),
                "Pass": "\u2705" if d["passed"] else ("\u274C" if d["passed"] is False else "\u2014"),
            })
        st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

