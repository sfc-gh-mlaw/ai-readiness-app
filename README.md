# AI Readiness Score

Measure how ready your Snowflake account's data is for AI products — Cortex Agents, Cortex Analyst, and Cortex Search — with a single Streamlit dashboard.

## Why This Matters

Organisations building on Snowflake's AI stack face a common blind spot: **they don't know whether their data is actually ready for AI consumption.** They build semantic views without knowing which tables matter most. They add verified queries without tracking whether accuracy improves. They have no baseline and no way to measure progress.

This app fixes that by scoring two complementary dimensions:

1. **Demand-side readiness** — Are your most-queried tables well-structured? Is analytical traffic concentrated on consumption-ready (CR) tables backed by semantic views?
2. **Structural readiness** — Does your data meet the 6 factors of AI-ready data: Clean, Contextual, Consumable, Current, Correlated, and Compliant?

The result is a single 0–100 AI Readiness Score that gives you a baseline, tracks progress over time, and tells you exactly what to fix next.

## What It Does

A 3-tab Streamlit-in-Snowflake app that runs entirely inside your Snowflake account:

| Tab | What it shows |
|---|---|
| **Current Scan** | Composite AI Readiness score, demand coverage, SV readiness/coverage/quality metrics, radar chart, gap classification, and prioritised improvement actions |
| **Run History** | Append-only scan history with trend charts — track score progression as you build SVs and add VQRs |
| **6-Factor Scan** | Structural assessment across Clean, Contextual, Consumable, Current, Correlated, Compliant — scored per schema with drill-down |

### Architecture

```
+---------------------------+        +---------------------------+
|   snowflake.account_usage |        |    information_schema     |
|                           |        |                           |
|  ACCESS_HISTORY           |        |  tables / columns /       |
|  QUERY_HISTORY            |        |  table_constraints        |
|  SESSIONS                 |        +------------+--------------+
|  TABLES                   |                     |
|  SEMANTIC_VIEWS           |                     |
|  SEMANTIC_TABLES          |                     |
|  TAG_REFERENCES           |                     |
|  POLICY_REFERENCES        |                     |
+------------+--------------+                     |
             |                                    |
             v                                    v
    +--------+------------------------------------+--------+
    |              Streamlit App (SiS)                     |
    |                                                      |
    |  +-------------+  +-------------+  +--------------+  |
    |  | CR Table    |  | SV Quality  |  | 6-Factor     |  |
    |  | Scoring     |  | Scoring     |  | Scan Engine  |  |
    |  | (Cobb-      |  | (9-point    |  | (13 checks   |  |
    |  |  Douglas)   |  |  scale)     |  |  across 6)   |  |
    |  +------+------+  +------+------+  +------+-------+  |
    |         |                |                |           |
    |         v                v                v           |
    |  +------+----------------+----------------+-------+   |
    |  |         Composite Scoring Engine               |   |
    |  |  AI Readiness = (Demand Cov + SV Readiness)/2  |   |
    |  +------+-----------------------------------------+   |
    |         |                                             |
    |         v                                             |
    |  +------+-------------------+  +-------------------+  |
    |  | Tab 1: Current Scan     |  | Tab 2: Run History |  |
    |  | Radar + bar charts      |  | Trend lines        |  |
    |  | Gap classification      |  | Past run inspector  |  |
    |  | Improvement actions     |  | Score comparison    |  |
    |  +-------------------------+  +-------------------+   |
    |  +------+-------------------+                         |
    |  | Tab 3: 6-Factor Scan    |                         |
    |  | Per-schema portfolio    |                         |
    |  | Factor breakdown bars   |                         |
    |  | Requirement detail      |                         |
    |  +-------------------------+                         |
    +---+--------------------------------------------------+
        |
        v
    +---+----------------------------------------------+
    |  AI_READINESS_APP.PUBLIC                         |
    |                                                  |
    |  SCAN_RUNS              SCAN_IMPROVEMENT_ITEMS   |
    |  (append-only           (linked by run_id)       |
    |   scan snapshots)                                |
    +--------------------------------------------------+
```

## Scoring at a Glance

### CR Table Score (Cobb-Douglas blend)

| Signal | Weight | Source |
|---|---|---|
| Activity (read volume) | 35% | `ACCESS_HISTORY` |
| Consumption (user/tool breadth) | 30% | `SESSIONS` + `ACCESS_HISTORY` |
| Speed (query latency) | 20% | `QUERY_HISTORY` |
| Freshness (recency) | 15% | `TABLES.last_altered` |

A table is **Consumption-Ready** at score >= 0.80.

### SV Quality (9-point scale)

Primary key + synonyms + unique keys + distinct ranges + relationships + metrics + VQR saturation (0–2) + comment depth (0–1).

### 6-Factor Scan (13 requirements)

| Factor | Requirements | What it checks |
|---|---|---|
| **Clean** | 3 | NOT NULL columns, PK/UNIQUE constraints, FK declarations |
| **Contextual** | 3 | SV coverage, PK/UNIQUE, column comments/naming |
| **Consumable** | 1 | Clustering keys on large tables |
| **Current** | 2 | Change tracking, data freshness |
| **Correlated** | 2 | Downstream reads, upstream writes (ACCESS_HISTORY) |
| **Compliant** | 2 | Governance tags, masking policies on PII columns |

Based on [Snowflake Labs' AI-Ready Data Framework](https://github.com/Snowflake-Labs/ai-ready-data) (62 requirements, 5 workload profiles).

## Quick Start

### Option A: Automated (via CoCo skill)

```bash
cortex -c <your-connection>
> Deploy the AI Readiness Score app
```

### Option B: Manual

```bash
# 1. Run setup SQL (edit warehouse name first)
snow sql -f setup.sql -c <connection>

# 2. Upload app files
snow stage copy streamlit_app.py @AI_READINESS_APP.PUBLIC.APP_STAGE/ --overwrite -c <connection>
snow stage copy environment.yml @AI_READINESS_APP.PUBLIC.APP_STAGE/ --overwrite -c <connection>

# 3. Open in Snowsight → Streamlit → AI Readiness Score
```

See [references/deployment-guide.md](references/deployment-guide.md) for full details and troubleshooting.

## Prerequisites

- Snowflake Enterprise Edition (for `ACCESS_HISTORY`)
- `IMPORTED PRIVILEGES` on the `SNOWFLAKE` database
- A warehouse for the Streamlit app

## Project Structure

```
ai_readiness_app/
  streamlit_app.py              # The full Streamlit app (1600+ lines)
  environment.yml               # Snowflake Streamlit dependencies
  setup.sql                     # DDL for database, tables, stage, Streamlit object
  SKILL.md                      # CoCo skill definition for automated deployment
  README.md                     # This file
  references/
    scoring-methodology.md      # CR formula, SV quality scale, composite scoring
    6-factor-framework.md       # The 6 factors, 13 requirements, SQL checks
    deployment-guide.md         # Manual deployment, updating, teardown, troubleshooting
```

## Detailed References

| Document | Contents |
|---|---|
| [Scoring Methodology](references/scoring-methodology.md) | Cobb-Douglas CR formula, SV quality 9-point scale, demand coverage, gap waterfall, demo traffic generator |
| [6-Factor Framework](references/6-factor-framework.md) | Clean through Compliant factors, 13 requirements with SQL sources, tier classification, relationship to full 62-requirement framework |
| [Deployment Guide](references/deployment-guide.md) | Prerequisites, manual setup steps, updating, teardown, required privileges, troubleshooting |

## Credits

- Scoring methodology adapted from the bundled `ai-readiness-score` Cortex Code skill
- 6-Factor framework from [Snowflake Labs AI-Ready Data](https://github.com/Snowflake-Labs/ai-ready-data) by Jacob Prall
- Built with [Cortex Code](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-code)
