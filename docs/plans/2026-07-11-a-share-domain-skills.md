# A-Share Domain Skills Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add reusable A-share market-understanding skills to the MVP so agents reason with China-specific market structure.

**Architecture:** Create `app/skills/` as deterministic domain modules that consume normalized provider dataclasses and emit `SkillInsight` records. The workflow stores these insights in `ResearchState`, includes them in the final report, and lets portfolio/risk decisions use them as an extra evidence layer.

**Tech Stack:** Python 3.10+, dataclasses, standard library unittest.

---

### Task 1: Schema

**Files:**
- Modify: `app/schemas/report.py`
- Modify: `app/graph/state.py`

**Steps:**
1. Add `SkillInsight` with skill name, category, stage, score, conclusion, strategy, evidence, and risks.
2. Add `skill_insights` to `AnalysisReport` and `ResearchState`.

**Test:** JSON serialization includes `skill_insights`.

### Task 2: Domain Skill Modules

**Files:**
- Create: `app/skills/market_temperature.py`
- Create: `app/skills/sentiment_cycle.py`
- Create: `app/skills/money_making_effect.py`
- Create: `app/skills/theme_lifecycle.py`
- Create: `app/skills/main_force_behavior.py`
- Create: `app/skills/announcement_impact.py`
- Create: `app/skills/risk_scanner.py`
- Create: `app/skills/stock_score_model.py`

**Steps:**
1. Implement each skill as a pure function returning `SkillInsight`.
2. Keep scoring deterministic and transparent.
3. Avoid direct buy/sell recommendations.

**Test:** Each skill returns scores in 0-100 and populated evidence.

### Task 3: Workflow Integration

**Files:**
- Modify: `app/graph/workflow.py`
- Modify: `app/agents/portfolio_manager.py`
- Modify: `app/agents/risk_manager.py`
- Modify: `app/reporting/render.py`
- Modify: `README.md`

**Steps:**
1. Run skills after data collection and before final report build.
2. Include skill insights in final JSON and Markdown.
3. Let low skill scores or risk skills downgrade final confidence/risk.

**Test:** CLI report shows an "A股领域 Skills" section.

### Task 4: Verification

**Files:**
- Create: `tests/test_domain_skills.py`
- Modify: `tests/test_workflow.py`

**Steps:**
1. Test market temperature and sentiment cycle stage outputs.
2. Test workflow report contains core skill names.
3. Run all unit tests.

**Test:** `python -m unittest discover -s tests`

