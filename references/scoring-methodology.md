# Scoring Methodology

## Overview

The AI Readiness Score measures how ready a Snowflake account's data is for AI products (Cortex Agents, Cortex Analyst, Cortex Search) by scoring two dimensions:

1. **Demand Coverage** — is analytical traffic concentrated on well-structured tables?
2. **SV Readiness** — are those tables properly modeled in semantic views?

**Composite formula:**

```
AI Readiness = (Demand Coverage + SV Readiness) / 2
SV Readiness = sqrt(SV Coverage * SV Quality) * 100
```

---

## Consumption-Ready (CR) Table Scoring

A table's Consumption Readiness Score is a **Cobb-Douglas** (multiplicative) blend of four signals. Only tables with >= 5 analytical reads in the last 7 days are scored.

| Signal | Weight (exponent) | Source | What it captures |
|---|---|---|---|
| **Activity** | 0.35 | `PERCENT_RANK() OVER (ORDER BY analytical_reads)` | Read volume relative to other tables |
| **Consumption** | 0.30 | `GREATEST(user_pctile, app_pctile)` | Audience breadth — distinct users or BI tool usage |
| **Speed** | 0.20 | `1 / (1 + (p50_ms / 5000)^3)` | Median query latency (faster = higher) |
| **Freshness** | 0.15 | `exp(-ln(2)/30 * days_since_update)` | Exponential decay, ~30-day half-life |

**Formula:**

```
CR_score = activity^0.35 * consumption^0.30 * speed^0.20 * freshness^0.15
```

A table is **Consumption-Ready** when `CR_score >= 0.80`.

### Data sources

- `snowflake.account_usage.ACCESS_HISTORY` — base_objects_accessed (reads only, filtered to `objects_modified = []`)
- `snowflake.account_usage.QUERY_HISTORY` — execution_time, query_type, error filtering
- `snowflake.account_usage.SESSIONS` — CLIENT_ENVIRONMENT:APPLICATION for BI tool detection
- `snowflake.account_usage.TABLES` — last_altered for freshness

### BI tool detection

The app identifies dashboard/BI reads by matching `CLIENT_ENVIRONMENT:APPLICATION` against patterns for: Looker, Tableau, Power BI, Sigma, ThoughtSpot, Metabase, Streamlit, Snowsight dashboards, and 20+ other tools.

---

## Semantic View (SV) Quality Scoring

Each SV × base-table pair is scored on a **9-point scale**:

| Signal | Points | How it's measured |
|---|---|---|
| Has primary key | 1 | `ARRAY_SIZE(PRIMARY_KEYS) > 0` on any table in the SV |
| Has synonyms | 1 | Synonyms on table, dimension, fact, or metric definitions |
| Has unique keys | 1 | `ARRAY_SIZE(UNIQUE_KEYS) > 0` |
| Has distinct ranges | 1 | `ARRAY_SIZE(DISTINCT_RANGES) > 0` |
| Has relationships | 1 | At least one relationship to another table |
| Has metrics | 1 | At least one metric defined |
| VQR saturation | 0–2 | `2 * (1 - exp(-(ln10/10) * n_verified_queries))` — saturates at ~10 VQRs |
| Comment depth | 0–1 | `1 * (1 - exp(-(ln100/100) * avg_comment_length))` — rewards longer comments |

**Quality score** = sum / 9.0 (normalised 0–1)

### SV Coverage

```
SV Coverage = (CR tables covered by >= 1 SV) / (total CR tables) * 100
```

---

## Demand Coverage

```
Demand Coverage = (reads on CR tables) / (total analytical reads) * 100
```

Measures what percentage of the account's analytical workload lands on well-structured tables.

---

## Gap Classification (Waterfall)

Checked in order; first match wins:

| Condition | Gap | Recommended action |
|---|---|---|
| Demand Coverage < 50% or 0 CR tables | `BUILD_CR_TABLES` | Drive more analytical traffic to structured tables |
| SV Coverage = 0 | `BUILD_SVS` | Create semantic views on CR tables |
| SV Coverage < 50% | `EXPAND_SV_COVERAGE` | Add SVs for uncovered CR tables |
| SV Quality < 50% | `IMPROVE_SV_QUALITY` | Add VQRs, PKs, synonyms, relationships |
| All thresholds met | `HEALTHY` | Maintain and monitor |

---

## Demo Traffic Generator

The app includes a traffic generator that runs SELECT queries against SV-covered tables. Queries are **tiered by table size** to produce realistic ACCESS_HISTORY patterns:

| Table size | Variants run | Rationale |
|---|---|---|
| < 100 rows | 3 queries | Small dimension tables get light traffic |
| 100–999 rows | 6 queries | Mid-size tables get moderate traffic |
| >= 1000 rows | 10 queries | Fact tables attract heavier analytical traffic |

This breaks `PERCENT_RANK` ties that would otherwise give all tables identical consumption scores.
