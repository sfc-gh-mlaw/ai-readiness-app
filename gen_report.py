"""gen_report.py — Generate AI Readiness Score HTML report."""

import html as html_lib
import math

# ── constants ──────────────────────────────────────────────────────────────────
_GAP_LABELS = {
    "BUILD_CR_TABLES": "build consumption-ready tables",
    "BUILD_SVS": "build semantic views",
    "EXPAND_SV_COVERAGE": "expand semantic view coverage",
    "IMPROVE_SV_QUALITY": "improve semantic view quality",
    "HEALTHY": "maintain your current position",
}

_SCORE_STAGES = [
    (10, "Early stage.",
     "Almost no AI-ready infrastructure yet. Data is used operationally but hasn\u2019t been shaped for analytical AI tools."),
    (30, "You\u2019re getting started.",
     "Some investment in AI-ready data exists, but coverage is narrow. "
     '<span class="help-tip" data-tip="Tables that are actively used, broadly consumed, fast to query, and recently updated. Think: analyst-facing tables, not ETL pipelines.">Consumption-ready tables</span>'
     " and semantic views are present in pockets rather than scaled across the account."),
    (55, "Building momentum.",
     "Real investment is underway. A meaningful share of analytical traffic hits curated tables, and semantic views cover key domains \u2014 but significant gaps remain."),
    (75, "Well positioned.",
     "Strong data foundation. Most analytical demand is served by consumption-ready tables with solid semantic view coverage. Remaining work is optimization and filling edge-case gaps."),
    (100, "AI-ready.",
     "Broad, mature coverage. The vast majority of analytical workloads land on well-documented, fast, fresh tables with comprehensive semantic views. AI tools can operate effectively across the account."),
]

_METRIC_TIPS = {
    "ai_readiness": "How ready is your account for AI-powered analytics? Combines how much of your data is consumption-ready with how well semantic views cover it.",
    "demand_coverage": "What share of your analytical queries actually hit consumption-ready tables versus raw/pipeline tables.",
    "sv_readiness": "How well your semantic views cover your data and how complete they are. Combines breadth (how many tables) with depth (how rich each view is).",
    "sv_coverage": "What percentage of your consumption-ready tables have at least one semantic view defined.",
    "sv_quality": "How complete your semantic views are on average \u2014 do they have primary keys, relationships, metrics, descriptions, and verified queries?",
}

_TERMINOLOGY = [
    ("AI Readiness Score", _METRIC_TIPS["ai_readiness"]),
    ("Consumption-ready tables", "Tables that are actively used, broadly consumed, fast to query, and recently updated. Think: analyst-facing tables, not ETL pipelines."),
    ("Demand coverage", _METRIC_TIPS["demand_coverage"]),
    ("Semantic view readiness", _METRIC_TIPS["sv_readiness"]),
    ("Semantic view coverage", _METRIC_TIPS["sv_coverage"]),
    ("Semantic view quality", _METRIC_TIPS["sv_quality"]),
]


def _e(s) -> str:
    return html_lib.escape(str(s))


def _score_color(v: float) -> str:
    if v <= 30:
        return "var(--score-low)"
    if v <= 55:
        return "var(--score-mid)"
    return "var(--score-high)"


def _score_stage(v: float):
    for threshold, label, desc in _SCORE_STAGES:
        if v <= threshold:
            return label, desc
    return _SCORE_STAGES[-1][1], _SCORE_STAGES[-1][2]


def _dim_interp(name: str, v: float) -> str:
    if name == "AI Readiness":
        if v <= 10: return f"{v:.0f}/100 — Early stage. Almost no AI-ready infrastructure yet."
        if v <= 30: return f"{v:.0f}/100 — Getting started. Some AI-ready data exists but coverage is narrow."
        if v <= 55: return f"{v:.0f}/100 — Building momentum. Meaningful investment underway but gaps remain."
        if v <= 75: return f"{v:.0f}/100 — Well positioned. Strong foundation, mostly optimization left."
        return f"{v:.0f}/100 — AI-ready. Broad, mature coverage across the account."
    if name == "Demand Coverage":
        if v < 25: return f"{v:.0f}% — Most analytical reads land on raw or pipeline tables, not curated ones."
        if v < 50: return f"{v:.0f}% — Some reads hit consumption-ready tables but the majority still don\u2019t."
        if v < 75: return f"{v:.0f}% — Over half of analytical traffic lands on consumption-ready tables."
        return f"{v:.0f}% — Strong. The vast majority of reads hit well-curated tables."
    if name == "Semantic View Readiness":
        if v < 25: return f"{v:.0f}/100 — Semantic views are sparse or low quality. Big room to grow."
        if v < 50: return f"{v:.0f}/100 — Some semantic view investment, but coverage or quality gaps remain."
        if v < 75: return f"{v:.0f}/100 — Good foundation. Most key tables have decent semantic views."
        return f"{v:.0f}/100 — Excellent. Broad, high-quality semantic view coverage."
    if name == "Semantic View Coverage":
        if v < 10: return f"{v:.0f}% — Almost none of your consumption-ready tables have a semantic view."
        if v < 30: return f"{v:.0f}% — A small fraction of consumption-ready tables are covered."
        if v < 60: return f"{v:.0f}% — Moderate. Many consumption-ready tables still lack semantic views."
        return f"{v:.0f}% — Strong. Most consumption-ready tables have at least one semantic view."
    if name == "Semantic View Quality":
        if v < 25: return f"{v:.0f}/100 — Views are bare-bones: missing keys, metrics, or descriptions."
        if v < 50: return f"{v:.0f}/100 — Some metadata present but common gaps in keys, metrics, or relationships."
        if v < 75: return f"{v:.0f}/100 — Good depth. Most views have keys, metrics, and descriptions."
        return f"{v:.0f}/100 — Rich, well-documented views with verified queries and full metadata."
    return f"{v:.1f}"


def render_html(
    account_name: str,
    role: str,
    run_date: str,
    ai_readiness: float,
    demand_coverage: float,
    sv_readiness: float,
    sv_coverage: float,
    sv_quality: float,
    n_cr_tables: int,
    gap: str,
    recommendation: str,
    improvement_items: list,
    sample_pct=None,
    org_name: str = "",
    database_filter: str = "All databases",
) -> str:
    footer_text = "Generated by AI Readiness Score Streamlit App"
    gap_label = _GAP_LABELS.get(gap, gap)
    stage_title, stage_desc = _score_stage(ai_readiness)
    score_color = _score_color(ai_readiness)
    sample_label = f"{sample_pct}% sample" if sample_pct else "Full scan"

    # Opportunities table
    opp_rows = ""
    for item in improvement_items[:15]:
        tag_label = {
            "UNCOVERED_CR_TABLE": "Needs semantic view",
            "SV_QUALITY_GAP": "Quality gap",
            "SCHEMA_GAP": "Low CR coverage",
        }.get(item["type"], item["type"])
        opp_rows += (
            f"<tr>"
            f'<td><span class="type-tag">{_e(tag_label)}</span></td>'
            f"<td><code>{_e(item['target'])}</code></td>"
            f"<td>{_e(item['detail'])}</td>"
            f"<td>{_e(item['recommendation'])}</td>"
            f"</tr>"
        )

    opp_html = ""
    if improvement_items:
        opp_html = f"""
      <div class="opportunities" id="opportunities">
        <h3 class="section-title">Opportunities</h3>
        <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Type</th>
              <th>Target</th>
              <th>Detail</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>{opp_rows}</tbody>
        </table>
        </div>
      </div>"""

    # Industry comparison dimensions
    dims = [
        {
            "name": "AI Readiness",
            "you": round(ai_readiness, 1),
            "youTip": _dim_interp("AI Readiness", ai_readiness),
            "industries": [
                {"n": "Financial Services", "v": 13.7}, {"n": "Technology", "v": 11.2},
                {"n": "Retail & Consumer", "v": 13.0}, {"n": "Manufacturing", "v": 13.6},
                {"n": "Healthcare", "v": 12.9}, {"n": "Media & Entertainment", "v": 11.7},
                {"n": "Consulting", "v": 13.5}, {"n": "Travel & Hospitality", "v": 16.3},
                {"n": "Public Sector", "v": 7.5}, {"n": "Telecom", "v": 13.9},
            ],
        },
        {
            "name": "Demand Coverage",
            "you": round(demand_coverage, 1),
            "youTip": _dim_interp("Demand Coverage", demand_coverage),
            "industries": [
                {"n": "Financial Services", "v": 24.4}, {"n": "Technology", "v": 19.6},
                {"n": "Retail & Consumer", "v": 23.7}, {"n": "Manufacturing", "v": 24.2},
                {"n": "Healthcare", "v": 22.7}, {"n": "Media & Entertainment", "v": 20.8},
                {"n": "Consulting", "v": 23.4}, {"n": "Travel & Hospitality", "v": 27.1},
                {"n": "Public Sector", "v": 15.5}, {"n": "Telecom", "v": 24.4},
            ],
        },
        {
            "name": "Semantic View Readiness",
            "you": round(sv_readiness, 1),
            "youTip": _dim_interp("Semantic View Readiness", sv_readiness),
            "industries": [
                {"n": "Financial Services", "v": 3.6}, {"n": "Technology", "v": 4.0},
                {"n": "Retail & Consumer", "v": 3.0}, {"n": "Manufacturing", "v": 4.1},
                {"n": "Healthcare", "v": 3.8}, {"n": "Media & Entertainment", "v": 3.8},
                {"n": "Consulting", "v": 5.4}, {"n": "Travel & Hospitality", "v": 6.3},
                {"n": "Public Sector", "v": 0.9}, {"n": "Telecom", "v": 4.1},
            ],
        },
        {
            "name": "Semantic View Coverage",
            "you": round(sv_coverage, 1),
            "youTip": _dim_interp("Semantic View Coverage", sv_coverage),
            "industries": [
                {"n": "Financial Services", "v": 1.7}, {"n": "Technology", "v": 2.5},
                {"n": "Retail & Consumer", "v": 1.7}, {"n": "Manufacturing", "v": 2.2},
                {"n": "Healthcare", "v": 2.0}, {"n": "Media & Entertainment", "v": 2.3},
                {"n": "Consulting", "v": 3.3}, {"n": "Travel & Hospitality", "v": 3.0},
                {"n": "Public Sector", "v": 0.8}, {"n": "Telecom", "v": 2.4},
            ],
        },
        {
            "name": "Semantic View Quality",
            "you": round(sv_quality, 1),
            "youTip": _dim_interp("Semantic View Quality", sv_quality),
            "industries": [
                {"n": "Financial Services", "v": 12.6}, {"n": "Technology", "v": 8.5},
                {"n": "Retail & Consumer", "v": 8.7}, {"n": "Manufacturing", "v": 11.5},
                {"n": "Healthcare", "v": 12.3}, {"n": "Media & Entertainment", "v": 9.0},
                {"n": "Consulting", "v": 11.1}, {"n": "Travel & Hospitality", "v": 17.2},
                {"n": "Public Sector", "v": 2.0}, {"n": "Telecom", "v": 13.1},
            ],
        },
    ]

    global_max = max(max(ind["v"] for ind in d["industries"]) for d in dims)
    global_max = max(global_max, max(d["you"] for d in dims))
    axis_max = math.ceil(global_max)

    def _pct(v):
        return min(100.0, max(0.0, (v / axis_max) * 100))

    comp_strips_html = ""
    for d in dims:
        dots = ""
        for ind in d["industries"]:
            dots += f'<div class="comp-dot industry" style="left:{_pct(ind["v"]):.1f}%;" data-tip="{_e(ind["n"])}: {ind["v"]:.1f}"></div>'
        you_tip = _e(d.get("youTip", ""))
        dots += f'<div class="comp-dot you" style="left:{_pct(d["you"]):.1f}%;" data-tip="{you_tip}"><span class="comp-your-score">{d["you"]:.1f}</span></div>'
        comp_strips_html += (
            f'<div class="comp-dimension">'
            f'<div class="comp-header"><span class="comp-label">{_e(d["name"])}</span></div>'
            f'<div class="comp-strip"><div class="comp-strip-inner">{dots}</div></div>'
            f'</div>'
        )

    terminology_rows = ''.join(
        f'      <dt>{_e(term)}</dt><dd>{_e(desc)}</dd>\n'
        for term, desc in _TERMINOLOGY
    )

    run_date_short = run_date.split(" ")[0] if " " in run_date else run_date

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Readiness Score \u2014 {_e(account_name)}</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --sf-blue: #29B5E8;
    --mid-blue: #11567F;
    --iceberg: #003545;
    --star-blue: #71D3DC;
    --windy: #8A999E;
    --orange: #FF9F36;
    --light: #f8fbfc;
    --border: #e2e8f0;
    --card: #ffffff;
    --score-low: #e85d40;
    --score-mid: #f59e0b;
    --score-high: #10b981;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'IBM Plex Sans', sans-serif;
    background: var(--light);
    color: var(--iceberg);
    font-size: 15px;
    line-height: 1.6;
  }}
  .wrap {{
    max-width: 820px;
    margin: 0 auto;
    padding: 64px 48px 80px;
  }}

  .page-header {{
    margin-bottom: 40px;
  }}
  .page-header .eyebrow {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.05em;
    color: var(--windy);
    margin-bottom: 4px;
  }}
  .page-header h1 {{
    font-family: 'Space Grotesk', sans-serif;
    font-size: 2rem;
    font-weight: 700;
    letter-spacing: -0.03em;
    color: var(--mid-blue);
  }}
  .page-header .meta {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    font-weight: 400;
    color: var(--windy);
    text-align: right;
    line-height: 1.7;
  }}
  .page-header .meta svg {{
    width: 11px;
    height: 11px;
    vertical-align: -1px;
    margin-right: 3px;
  }}

  .hero {{
    padding: 8px 0 0;
    margin-bottom: 20px;
  }}
  .hero .score-line {{
    display: flex;
    align-items: baseline;
    gap: 12px;
    flex-wrap: wrap;
  }}
  .hero .score-value {{
    font-family: 'Space Grotesk', sans-serif;
    font-size: 5.5rem;
    font-weight: 700;
    letter-spacing: -0.04em;
    color: {score_color};
    line-height: 1;
  }}
  .hero .score-max {{
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.8rem;
    font-weight: 400;
    color: var(--windy);
    letter-spacing: -0.02em;
  }}
  .hero .score-label {{
    font-family: 'Space Grotesk', sans-serif;
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: var(--windy);
  }}
  .hero .score-stage {{
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--mid-blue);
    margin-top: 16px;
  }}
  .hero .score-desc {{
    font-size: 13px;
    color: var(--windy);
    margin-top: 6px;
    line-height: 1.55;
  }}

  .recommendation {{
    margin-bottom: 40px;
  }}
  .recommendation h2 {{
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--mid-blue);
    margin-bottom: 8px;
  }}
  .recommendation p {{
    font-size: 13px;
    color: var(--windy);
    margin-bottom: 6px;
    line-height: 1.6;
  }}

  .subscores {{
    margin-bottom: 40px;
  }}
  .section-title {{
    font-family: 'Space Grotesk', sans-serif;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 0.02em;
    color: var(--mid-blue);
    margin-bottom: 12px;
    padding-bottom: 4px;
    border-bottom: 1px solid var(--border);
  }}
  .subscore-row {{
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 14px 0;
    border-bottom: 1px solid var(--border);
  }}
  .subscore-row:last-child {{ border-bottom: none; }}
  .subscore-name {{
    flex: 1;
    font-size: 14px;
    font-weight: 500;
    color: var(--iceberg);
  }}
  .subscore-bar-wrap {{
    flex: 2;
    height: 6px;
    background: #e9ecef;
    border-radius: 3px;
    overflow: hidden;
  }}
  .subscore-bar {{
    height: 100%;
    border-radius: 3px;
    background: var(--sf-blue);
  }}
  .subscore-value {{
    font-family: 'Space Grotesk', sans-serif;
    font-size: 15px;
    font-weight: 700;
    color: var(--mid-blue);
    min-width: 32px;
    text-align: right;
  }}
  .subscore-sub {{
    padding-left: 20px;
  }}
  .subscore-sub .subscore-name {{
    font-size: 13px;
    font-weight: 400;
    color: var(--windy);
  }}
  .subscore-sub .subscore-value {{
    font-size: 13px;
    font-weight: 600;
    color: var(--windy);
  }}
  .subscore-sub .subscore-bar {{
    background: var(--star-blue);
    opacity: 0.6;
  }}

  .comparison {{
    margin-bottom: 40px;
  }}
  .comp-dimension {{
    margin-bottom: 24px;
  }}
  .comp-header {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 8px;
  }}
  .comp-label {{
    font-size: 13px;
    font-weight: 600;
    color: var(--iceberg);
  }}
  .comp-your-score {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    font-weight: 500;
    color: var(--mid-blue);
    position: absolute;
    top: -18px;
    left: 50%;
    transform: translateX(-50%);
    white-space: nowrap;
  }}
  .comp-strip {{
    position: relative;
    height: 28px;
    background: #f1f5f9;
    border-radius: 4px;
    overflow: visible;
  }}
  .comp-strip-inner {{
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
  }}
  .comp-dot {{
    position: absolute;
    top: 50%;
    transform: translate(-50%, -50%);
    border-radius: 50%;
    cursor: default;
  }}
  .comp-dot.industry {{
    width: 8px;
    height: 8px;
    background: var(--windy);
    opacity: 0.5;
  }}
  .comp-dot.you {{
    width: 14px;
    height: 14px;
    background: var(--sf-blue);
    border: 2px solid var(--card);
    box-shadow: 0 0 0 2px var(--sf-blue);
    z-index: 2;
  }}
  .comp-legend {{
    display: flex;
    gap: 16px;
    margin-bottom: 20px;
    font-size: 12px;
    color: var(--windy);
  }}
  .comp-legend-item {{
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .comp-legend-dot {{
    width: 8px;
    height: 8px;
    border-radius: 50%;
  }}

  .comp-dot[data-tip]:hover::after {{
    content: attr(data-tip);
    position: absolute;
    bottom: calc(100% + 6px);
    left: 50%;
    transform: translateX(-50%);
    background: var(--iceberg);
    color: #fff;
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 11px;
    padding: 4px 8px;
    border-radius: 4px;
    white-space: nowrap;
    z-index: 10;
    pointer-events: none;
  }}
  .comp-dot.you[data-tip]:hover::after {{
    width: 240px;
    white-space: normal;
    line-height: 1.45;
    padding: 8px 12px;
    border-radius: 6px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  }}

  .opportunities {{
    margin-bottom: 40px;
  }}
  .opportunities table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
  }}
  .opportunities .table-wrap {{
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }}
  .opportunities .table-wrap::-webkit-scrollbar {{
    height: 4px;
  }}
  .opportunities .table-wrap::-webkit-scrollbar-track {{
    background: transparent;
  }}
  .opportunities .table-wrap::-webkit-scrollbar-thumb {{
    background: var(--mid-blue);
    border-radius: 2px;
  }}
  .opportunities th {{
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
    color: var(--windy);
    padding: 10px 14px;
    text-align: left;
    background: #f8fafc;
    border-bottom: 1px solid var(--border);
  }}
  .opportunities td {{
    padding: 10px 14px;
    border-bottom: 1px solid #f1f5f9;
    vertical-align: top;
    white-space: nowrap;
  }}
  .opportunities td code {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--iceberg);
    background: #f1f5f9;
    padding: 2px 6px;
    border-radius: 3px;
  }}
  .type-tag {{
    font-size: 10px;
    font-weight: 600;
    background: rgba(41, 181, 232, 0.1);
    color: var(--mid-blue);
    border-radius: 3px;
    padding: 2px 8px;
    white-space: nowrap;
  }}

  .footer {{
    margin-top: 48px;
    padding-top: 20px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--windy);
    text-align: center;
  }}

  .help-tip {{
    display: inline;
    cursor: help;
    position: relative;
    border-bottom: 1px dotted var(--windy);
  }}
  .help-tip::after {{
    content: attr(data-tip);
    position: absolute;
    bottom: calc(100% + 8px);
    left: 0;
    background: var(--iceberg);
    color: #fff;
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 11px;
    font-weight: 400;
    padding: 8px 12px;
    border-radius: 6px;
    width: 260px;
    white-space: normal;
    line-height: 1.45;
    z-index: 20;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.15s;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  }}
  .help-tip:hover::after {{
    opacity: 1;
  }}

  .terminology {{
    margin-bottom: 40px;
  }}
  .terminology dl {{
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 6px 20px;
    font-size: 13px;
    max-height: 0;
    overflow: hidden;
    opacity: 0;
    transition: max-height 0.35s ease, opacity 0.25s ease, margin-top 0.35s ease;
    margin-top: 0;
  }}
  .terminology:hover dl {{
    max-height: 400px;
    opacity: 1;
    margin-top: 12px;
  }}
  .terminology .section-title {{
    cursor: pointer;
  }}
  .terminology .section-title::after {{
    content: ' \u25be';
    font-size: 11px;
    color: var(--windy);
    transition: transform 0.25s ease;
    display: inline-block;
  }}
  .terminology:hover .section-title::after {{
    transform: rotate(180deg);
  }}
  .terminology dt {{
    font-weight: 600;
    color: var(--iceberg);
    white-space: nowrap;
  }}
  .terminology dd {{
    color: var(--windy);
    margin: 0;
    line-height: 1.55;
  }}

  .stat-pill {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #f1f5f9;
    border-radius: 20px;
    padding: 4px 12px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: var(--windy);
    margin-top: 16px;
  }}
  .stat-pill strong {{
    color: var(--mid-blue);
  }}
</style>
</head>
<body>
<div class="wrap">

  <!-- Header -->
  <div class="page-header">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;">
      <div>
        <div class="eyebrow">AI Readiness Report</div>
        <h1>{_e(account_name)}</h1>
      </div>
      <div class="meta">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a4 4 0 0 0-8 0v2"/></svg>{_e(org_name)}<br>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M6 21v-2a6 6 0 0 1 12 0v2"/></svg>{_e(role)}<br>
        {_e(run_date_short)} \u00b7 {_e(sample_label)}
      </div>
    </div>
  </div>

  <!-- Summary -->
  <h3 class="section-title">Summary</h3>
  <div class="hero" id="summary">
    <div class="score-line">
      <div><span class="score-value">{ai_readiness:.0f}</span><span class="score-max">/100</span></div>
      <div class="score-label"><span class="help-tip" data-tip="{_e(_METRIC_TIPS['ai_readiness'])}">is your AI readiness score.</span></div>
    </div>
    <div class="score-stage">{stage_title}</div>
    <div class="score-desc">{stage_desc}</div>
    <div class="stat-pill">\U0001f4e6 <strong>{n_cr_tables:,}</strong> consumption-ready tables</div>
  </div>

  <!-- Terminology -->
  <div class="terminology">
    <h3 class="section-title">Terminology</h3>
    <dl>
{terminology_rows}    </dl>
  </div>

  <!-- Recommendation -->
  <div class="recommendation">
    <h2>Our recommendation: {_e(gap_label)}</h2>
    <p>{_e(recommendation)}</p>
  </div>

  <!-- Score breakdown -->
  <div id="breakdown">
    <h3 class="section-title">Score breakdown</h3>
    <div class="subscores">
      <div class="subscore-row">
        <div class="subscore-name"><span class="help-tip" data-tip="{_e(_METRIC_TIPS['demand_coverage'])}">Demand coverage</span></div>
        <div class="subscore-bar-wrap"><div class="subscore-bar" style="width:{demand_coverage:.0f}%;"></div></div>
        <div class="subscore-value">{demand_coverage:.0f}</div>
      </div>
      <div class="subscore-row">
        <div class="subscore-name"><span class="help-tip" data-tip="{_e(_METRIC_TIPS['sv_readiness'])}">Semantic view readiness</span></div>
        <div class="subscore-bar-wrap"><div class="subscore-bar" style="width:{sv_readiness:.0f}%;"></div></div>
        <div class="subscore-value">{sv_readiness:.0f}</div>
      </div>
      <div class="subscore-row subscore-sub">
        <div class="subscore-name"><span class="help-tip" data-tip="{_e(_METRIC_TIPS['sv_coverage'])}">Coverage</span></div>
        <div class="subscore-bar-wrap"><div class="subscore-bar" style="width:{sv_coverage:.0f}%;"></div></div>
        <div class="subscore-value">{sv_coverage:.0f}</div>
      </div>
      <div class="subscore-row subscore-sub">
        <div class="subscore-name"><span class="help-tip" data-tip="{_e(_METRIC_TIPS['sv_quality'])}">Quality</span></div>
        <div class="subscore-bar-wrap"><div class="subscore-bar" style="width:{sv_quality:.0f}%;"></div></div>
        <div class="subscore-value">{sv_quality:.0f}</div>
      </div>
    </div>
  </div>

  <!-- Industry comparison -->
  <div id="comparison">
    <h3 class="section-title">Industry comparison</h3>
    <div class="comp-legend">
      <div class="comp-legend-item">
        <div class="comp-legend-dot" style="background:var(--sf-blue);"></div>
        Your account
      </div>
      <div class="comp-legend-item">
        <div class="comp-legend-dot" style="background:var(--windy); opacity:0.5;"></div>
        Industry medians
      </div>
    </div>
    <p style="margin:4px 0 12px 0; font-size:0.78rem; color:#a0aec0; font-style:italic;">Hover over the points to see the industry</p>
    <div id="comp-strips">{comp_strips_html}</div>
  </div>

  <!-- Opportunities -->
  {opp_html}

  <!-- Footer -->
  <div class="footer">
    <span style="white-space:nowrap;">{_e(footer_text)}</span> \u00b7 <span style="white-space:nowrap;">snowflake.account_usage (trailing 7d)</span> \u00b7 <span style="white-space:nowrap;">{_e(run_date)}</span>
  </div>

</div>
</body>
</html>
"""
