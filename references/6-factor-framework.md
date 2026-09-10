# 6-Factor AI-Ready Data Framework

## Overview

The 6-Factor Scan is a complementary assessment based on [Snowflake Labs' AI-Ready Data Framework](https://github.com/Snowflake-Labs/ai-ready-data). It evaluates data readiness across six structural dimensions using metadata signals from `information_schema` and `snowflake.account_usage` — independent of query demand.

This scan runs 13 requirements across all 6 factors for estate-level prioritisation.

---

## The 6 Factors

| # | Factor | What it means | Why AI cares |
|---|---|---|---|
| 0 | **Clean** | Data is accurate, complete, and free of errors | Garbage in, garbage out — AI has no tolerance for dirty data |
| 1 | **Contextual** | Meaning is explicit and machine-readable | AI has zero institutional context; if meaning isn't colocated, the model is blind |
| 2 | **Consumable** | Data is in the right format and latency for AI workloads | AI needs millisecond retrieval, pre-chunked documents, optimised access paths |
| 3 | **Current** | Data reflects the present state | Models treat every input as ground truth — stale data produces confident wrong answers |
| 4 | **Correlated** | Data is traceable from source to decision | When predictions fail, you need to trace backward through the full lineage chain |
| 5 | **Compliant** | Data is governed with enforced access boundaries | AI introduces novel governance surface: PII in embeddings, bias in training, regulatory scrutiny |

---

## 13 Requirements (Scan Profile)

### Factor 0: Clean

| Requirement | What it checks | SQL source |
|---|---|---|
| `data_completeness` | % of columns declared NOT NULL | `information_schema.columns` |
| `uniqueness` | % of tables with a PK or UNIQUE constraint | `information_schema.table_constraints` |
| `referential_integrity` | % of tables with `_id` columns that have FK constraints | `information_schema.table_constraints` + `columns` |

### Factor 1: Contextual

| Requirement | What it checks | SQL source |
|---|---|---|
| `semantic_documentation` | % of base tables covered by a semantic view | `account_usage.SEMANTIC_TABLES` |
| `entity_identifier_declaration` | % of tables with PK/UNIQUE constraint | `information_schema.table_constraints` |
| `schema_type_coverage` | % of columns with a comment or recognisable name pattern | `information_schema.columns` |

### Factor 2: Consumable

| Requirement | What it checks | SQL source |
|---|---|---|
| `access_optimization` | % of large tables (>10K rows) with a clustering key | `information_schema.tables` |

### Factor 3: Current

| Requirement | What it checks | SQL source |
|---|---|---|
| `change_detection` | % of tables with change tracking enabled | `SHOW TABLES` + `RESULT_SCAN` |
| `data_freshness` | % of tables altered within the last 7 days | `information_schema.tables` |

### Factor 4: Correlated

| Requirement | What it checks | SQL source |
|---|---|---|
| `data_provenance` | % of tables read by downstream queries (last 30 days) | `account_usage.ACCESS_HISTORY` (base_objects_accessed) |
| `lineage_completeness` | % of tables with upstream write history (last 30 days) | `account_usage.ACCESS_HISTORY` (objects_modified) |

### Factor 5: Compliant

| Requirement | What it checks | SQL source |
|---|---|---|
| `classification` | % of tables with a governance tag applied | `account_usage.TAG_REFERENCES` |
| `column_masking` | % of PII-candidate columns with a masking policy | `account_usage.POLICY_REFERENCES` |

---

## Scoring

- Each requirement returns a **score between 0.0 and 1.0** (numerator / denominator)
- A requirement **passes** when score >= 0.50
- **Factor score** = average of its requirement scores
- **Overall score** = average across all 6 factor scores
- Displayed as 0–100 in the dashboard

## Tier Classification

| Overall Score | Tier | Interpretation |
|---|---|---|
| >= 70% | **High** | Schema is AI-ready |
| 40–69% | **Medium** | Partial readiness, targeted gaps |
| < 40% | **Low** | Significant structural gaps |

---

## Relationship to the Full Framework

This scan implements the **lightweight scan profile** (13 of 62 requirements). The full [AI-Ready Data Framework](https://github.com/Snowflake-Labs/ai-ready-data) provides deeper profiles:

| Profile | Requirements | Best for |
|---|---|---|
| scan (this app) | 13 | Estate-level sweep |
| rag | 27 | RAG: chunking, embeddings, vector search |
| agents | 37 | Text-to-SQL, agentic tool use |
| feature-serving | 39 | Online feature stores, low-latency lookups |
| training | 50 | Fine-tuning, reproducibility, bias testing |

Install the full framework as a CoCo skill: `npx skills add Snowflake-Labs/ai-ready-data -a cortex`
