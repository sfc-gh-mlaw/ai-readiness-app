# AI Readiness Score — Streamlit Dashboard

A Streamlit-in-Snowflake dashboard that puts the [`ai-readiness-score`](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-code) skill's scoring methodology into the hands of business teams — with persistent run history, trend tracking, and the [AI-Ready Data Framework](https://github.com/Snowflake-Labs/ai-ready-data)'s 6-factor structural scan.

## Background

Cortex Code ships with a bundled **`ai-readiness-score` skill** that scores how ready an account's data is for Snowflake's AI products (Cortex Agents, Cortex Analyst, Cortex Search). It measures:

- **Consumption-Ready (CR) tables** — a Cobb-Douglas blend of activity, audience breadth, query speed, and data freshness
- **Semantic View (SV) coverage and quality** — whether CR tables have SVs, and how well those SVs are modeled (PKs, synonyms, VQRs, relationships, metrics)
- **A composite AI Readiness score** — `(Demand Coverage + SV Readiness) / 2`

The skill works well for a point-in-time assessment from the CLI. But it runs once, prints results, and moves on. There's no history, no trend, and no way to share results with stakeholders who don't use Cortex Code.

## What This Project Adds

This project takes the `ai-readiness-score` skill's methodology and wraps it in a **persistent, shareable Streamlit app** that business teams can use directly in Snowsight — no CLI required. The key additions:

| What | Why it matters |
|---|---|
| **Run History** | Every scan is persisted to `SCAN_RUNS` / `SCAN_IMPROVEMENT_ITEMS`. Track your AI readiness score over weeks and months as you build SVs and add VQRs. Show before/after impact to stakeholders. |
| **Trend Charts** | Visualise score progression over time — AI Readiness, Demand Coverage, and SV Readiness on a single trend line. |
| **Gap Waterfall** | Each scan classifies the single most impactful gap and generates prioritised improvement actions. Business teams see exactly what to fix next and why. |
| **HTML Reports** | Every scan generates a self-contained HTML report (matching the bundled skill's styling) that can be downloaded, shared, or previewed inline. Past runs without saved reports are regenerated on-the-fly from stored scores. |
| **6-Factor Scan** | A complementary structural assessment based on the [AI-Ready Data Framework](https://github.com/Snowflake-Labs/ai-ready-data) — 13 requirements across Clean, Contextual, Consumable, Current, Correlated, Compliant. Scored per schema with drill-down. |
| **Demo Traffic Generator** | Seeds realistic query traffic (tiered by table size) so new accounts can see meaningful scores without waiting for organic usage. |

The goal is to make the ROI of semantic views visible to the people who fund and prioritise the work — not just the engineers who build them. When a business team can see that building 3 semantic views moved the score from 35 to 72, the case for continued investment makes itself.

## Architecture

> Open [`architecture.html`](architecture.html) in a browser for the full interactive diagram.

```
Snowflake Account
=================

  snowflake.account_usage          information_schema
  +-----------------------+        +--------------------+
  | ACCESS_HISTORY        |        | tables / columns / |
  | QUERY_HISTORY         |        | table_constraints  |
  | SESSIONS              |        +--------+-----------+
  | TABLES                |                 |
  | SEMANTIC_VIEWS/TABLES |                 |
  | TAG_REFERENCES        |                 |
  | POLICY_REFERENCES     |                 |
  +-----------+-----------+                 |
              |                             |
              v                             v
  +-----------+-----------------------------+-----------+
  |               Scoring Engine                        |
  |                                                     |
  |  CR Table Scoring    SV Quality     6-Factor Scan   |
  |  (Cobb-Douglas)      (9-point)      (13 checks)    |
  +---------------------+------+-----------------------+
                        |      |
              +---------+      +---------+
              v                          v
  +-----------------------+   +-----------------------+
  |  Streamlit Dashboard  |   |  Persistence Tables   |
  |                       |   |                       |
  |  Tab 1: Current Scan  |   |  SCAN_RUNS            |
  |  Tab 2: Run History   |   |  SCAN_IMPROVEMENT_    |
  |  Tab 3: 6-Factor Scan |   |    ITEMS              |
  +-----------------------+   +-----------------------+
```

## The ROI of Semantic Views

This dashboard exists to answer one question for business teams: **"Is our data getting more AI-ready over time?"**

Without semantic views, Cortex Agents and Cortex Analyst have to guess at table relationships, column meanings, and business logic. The result is low-quality answers that erode trust. With well-modeled SVs — primary keys declared, synonyms defined, verified queries added — answer quality improves measurably.

This app makes that improvement visible:

| Step | What CoCo Does | Time | ROI |
|---|---|---|---|
| 1. Score | Runs AI Readiness analysis across your account | Minutes | Replaces weeks of manual catalog auditing |
| 2. Identify Gaps | Shows tables needing SVs, SVs needing VQRs | Instant | Prioritised backlog instead of guesswork |
| 3. Build SVs | Generates semantic views from table schemas | Minutes | Self-service analytics for hundreds of users |
| 4. Add VQRs | Creates verified queries from natural language | Minutes | Reliable, repeatable answers for recurring business questions |
| 5. Re-Score | Validates improvement and tracks progress | Minutes | Measurable before/after proof for stakeholders |

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

Primary key + synonyms + unique keys + distinct ranges + relationships + metrics + VQR saturation (0-2) + comment depth (0-1).

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

Pick one of three paths. **Option A** is recommended if you want to edit the app inside Snowsight and push changes back to GitHub.

### Option A: Git workspace in Snowsight (recommended)

A Git-synced [workspace](https://docs.snowflake.com/en/user-guide/ui-snowsight/workspaces) gives you this repo as an editable project inside Snowsight, with pull/commit/push against GitHub — no local clone, no manual stage uploads.

**Step 1 — Create an API integration** (one-time, needs `CREATE API INTEGRATION`, usually `ACCOUNTADMIN`).

The Snowflake GitHub App is the simplest option for repos on github.com; it needs no OAuth app registration:

```sql
CREATE OR REPLACE API INTEGRATION github_api_integration
  API_PROVIDER = git_https_api
  API_ALLOWED_PREFIXES = ('https://github.com')
  API_USER_AUTHENTICATION = (TYPE = SNOWFLAKE_GITHUB_APP)
  ENABLED = TRUE;

-- If a non-admin role will create the workspace:
GRANT USAGE ON INTEGRATION github_api_integration TO ROLE <YOUR_ROLE>;
```

**Step 2 — Create the workspace from this repo.**

1. Sign in to Snowsight.
2. In the navigation menu, select **Projects » Workspaces**.
3. In the Workspaces menu, select **From Git repository**.
4. For **Repository URL**, enter the clone URL of your fork or this repo, e.g. `https://github.com/<your-org>/ai-readiness-app`.
5. Optionally rename the workspace (e.g. `ai-readiness-app`).
6. For **API Integration**, select `github_api_integration` from Step 1.
7. For the authentication method, choose one:
   - **OAuth2** — select **Sign in**, then **Configure** next to your GitHub account and **Authorize** Snowflake Computing. Under **Permissions**, grant *Read access to metadata* and *Read and write access to code* (write access is required to push). Under **Repository access**, scope it to the repos you want, then **Save**.
   - **Personal access token** — select the database and schema holding a `TYPE = password` secret with your GitHub username and PAT, or select **+ Secret** to create one.
   - **Public repository** — read-only; you can pull but **cannot** commit and push.
8. Select **Create**.

**Step 3 — Deploy from the workspace.** Open `setup.sql` in the workspace, replace `<YOUR_WAREHOUSE>`, and run it. Then upload the three app files to the stage (see [Option B](#option-b-local-cli) or the upload options at the bottom of `setup.sql`).

**Step 4 — Edit and push back.** Change files in the workspace, select **Changes** at the top of the folder view to review the diff (`A` added, `M` modified, `D` deleted), write a commit message, and select **Push**. If a conflict is flagged, pull first and resolve it inline.

> Requirements: the repo must have at least one branch (empty repos are unsupported) and be under 2 GB. For private-network Git servers, branch management, and conflict resolution, see [Integrate workspaces with a Git repository](https://docs.snowflake.com/en/user-guide/ui-snowsight/workspaces-git) and [Connect to a Git repository over a public network](https://docs.snowflake.com/en/developer-guide/git/git-setting-up-public).

### Option B: Local CLI

```bash
# 1. Run setup SQL (edit warehouse name first)
snow sql -f setup.sql -c <connection>

# 2. Upload app files
snow stage copy streamlit_app.py @AI_READINESS_APP.PUBLIC.APP_STAGE/ --overwrite -c <connection>
snow stage copy gen_report.py    @AI_READINESS_APP.PUBLIC.APP_STAGE/ --overwrite -c <connection>
snow stage copy environment.yml  @AI_READINESS_APP.PUBLIC.APP_STAGE/ --overwrite -c <connection>

# 3. Open in Snowsight -> Streamlit -> AI Readiness Score
```

### Option C: Automated (via CoCo skill)

```bash
cortex -c <your-connection>
> Deploy the AI Readiness Score app
```

See [references/deployment-guide.md](references/deployment-guide.md) for full details and troubleshooting.

## Viewing HTML Reports

Every scan generates a self-contained HTML report that matches the bundled `ai-readiness-score` skill's formatting — hero score, score breakdown bars, industry comparison dot strips, and an opportunities table.

### Where to find reports

**Current Scan tab** — after running a scan, scroll down to the "AI Readiness Report" section:
- **Download** — click the download button to save the HTML file locally. Open it in any browser to see the full report, share it with stakeholders via email or Slack.
- **Preview** — expand the "Preview report" section to view the report inline within the Streamlit app.

**Run History tab** — select any past run from the dropdown, then scroll to "AI Readiness Report":
- If the run has a saved report on stage (`@APP_STAGE/reports/`), it fetches and displays it.
- If the run predates the report feature (no saved file), the app **regenerates the report on-the-fly** from the scores and improvement items stored in `SCAN_RUNS` / `SCAN_IMPROVEMENT_ITEMS`. Every past run gets a viewable report — nothing is lost.

### Where reports are stored

```
@AI_READINESS_APP.PUBLIC.APP_STAGE/reports/
  ai_readiness_report_<date>_<run_id>.html   -- one per scan (dated snapshot)
  ai_readiness_report_latest.html            -- always the most recent scan
```

The stage path is recorded in `SCAN_RUNS.report_html_path` for each new run. You can also query it directly:

```sql
SELECT run_ts, ai_readiness, report_html_path
FROM AI_READINESS_APP.PUBLIC.SCAN_RUNS
WHERE report_html_path IS NOT NULL
ORDER BY run_ts DESC;
```

### Sharing reports

The HTML files are fully self-contained (no external JS, fonts via Google Fonts CDN). Download and share via:
- Email attachment
- Slack / Teams upload
- Snowflake workspace (`cortex ws cp` from CoCo)
- Any internal file share

## Prerequisites

- Snowflake Enterprise Edition (for `ACCESS_HISTORY`)
- `IMPORTED PRIVILEGES` on the `SNOWFLAKE` database
- A warehouse for the Streamlit app

## Project Structure

```
ai-readiness-app/
  streamlit_app.py              # The full Streamlit app (1800+ lines)
  gen_report.py                 # HTML report renderer (matches bundled skill styling)
  environment.yml               # Snowflake Streamlit dependencies
  setup.sql                     # DDL for database, tables, stage, Streamlit object
  SKILL.md                      # CoCo skill definition for automated deployment
  README.md                     # This file
  architecture.json             # Archify IR source
  architecture.html             # Interactive architecture diagram (open in browser)
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

- **Scoring methodology** from the bundled [`ai-readiness-score`](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-code) Cortex Code skill — this project reuses its formulas and extends them with persistence and a visual layer
- **6-Factor framework** from [Snowflake Labs AI-Ready Data](https://github.com/Snowflake-Labs/ai-ready-data) by Jacob Prall
- **Architecture diagram** generated with [Archify](https://github.com/tt-a1i/archify)
- Built with [Cortex Code](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-code)
