from __future__ import annotations

from app.memory.models import TradingProfile
from app.playbooks.catalog import Playbook, get_playbook
from app.schemas.report import AgentFinding, SkillInsight


def assess_active_playbook(
    profile: TradingProfile | None,
    findings: list[AgentFinding],
    insights: list[SkillInsight],
) -> SkillInsight | None:
    if profile is None:
        return None
    playbook = get_playbook(profile.active_playbook)
    scores = {item.agent: item.score for item in findings}
    by_skill = {item.skill: item for item in insights}
    technical = scores.get("技术分析 Agent", 0)
    fundamental = scores.get("基本面 Agent", 0)
    capital = scores.get("资金流 Agent", 0)
    sentiment = by_skill.get("情绪周期识别")
    money_making = by_skill.get("赚钱效应分析")
    theme = by_skill.get("热点生命周期分析")
    risk = by_skill.get("A股风险扫描器")

    score = 50
    evidence = [f"当前原型：{playbook.name}（{playbook.group}）", f"研究周期：{playbook.horizon}"]
    risks: list[str] = []

    if playbook.id == "hot_money_leader":
        score, evidence, risks = _hot_money_score(score, evidence, risks, technical, capital, sentiment, money_making, theme, risk)
    elif playbook.id == "trend_core":
        score, evidence, risks = _trend_score(score, evidence, risks, technical, capital, sentiment, theme, risk)
    elif playbook.id == "institutional_growth":
        score, evidence, risks = _growth_score(score, evidence, risks, technical, fundamental, capital, theme, risk)
    else:
        score, evidence, risks = _value_score(score, evidence, risks, fundamental, technical, theme, risk)

    score = max(0, min(100, score))
    if score >= 72:
        stage = "适配"
        conclusion = f"当前市场与个股证据基本满足{playbook.name}的研究前提"
        strategy = f"优化建议：{playbook.optimization_focus}"
    elif score >= 50:
        stage = "观察"
        conclusion = f"当前仅部分符合{playbook.name}，关键条件尚未齐全"
        strategy = f"优化建议：先补齐或核验缺失条件；{playbook.optimization_focus}"
    else:
        stage = "不适配"
        conclusion = f"当前环境不适合按{playbook.name}推进研究"
        strategy = "优化建议：不把风格标签当作信号，等待市场/资金/基本面条件重新满足。"

    return SkillInsight(
        skill="公开风格原型适配",
        category="playbook",
        stage=stage,
        score=score,
        conclusion=conclusion,
        strategy=strategy,
        evidence=evidence,
        risks=risks,
    )


def _hot_money_score(score, evidence, risks, technical, capital, sentiment, money_making, theme, risk):
    if sentiment and sentiment.stage in {"启动", "发酵"}:
        score += 18; evidence.append(f"情绪阶段：{sentiment.stage}")
    else:
        score -= 35; risks.append("情绪不在启动/发酵窗口，短线接力条件不足。")
    if money_making and money_making.score >= 65:
        score += 12; evidence.append(f"赚钱效应得分：{money_making.score}")
    else: risks.append("赚钱效应不足，隔日兑现风险更高。")
    if capital >= 70: score += 12; evidence.append(f"资金面得分：{capital}")
    else: risks.append("资金流未完成确认。")
    if technical >= 70: score += 8
    if theme and theme.stage in {"启动", "扩散"}: score += 8
    if risk and risk.score < 65: score -= 25; risks.append("风险扫描未达短线参与底线。")
    return score, evidence, risks


def _trend_score(score, evidence, risks, technical, capital, sentiment, theme, risk):
    if technical >= 70: score += 20; evidence.append(f"技术趋势得分：{technical}")
    else: score -= 15; risks.append("趋势尚未确认，避免把反弹当趋势。")
    if capital >= 65: score += 12; evidence.append(f"资金面得分：{capital}")
    else: risks.append("资金连续性需要复核。")
    if theme and theme.stage in {"启动", "扩散"}: score += 10; evidence.append(f"题材阶段：{theme.stage}")
    if sentiment and sentiment.stage in {"退潮", "冰点", "高潮"}: score -= 18; risks.append(f"情绪处于{sentiment.stage}，不宜把加速段当回踩机会。")
    if risk and risk.score < 65: score -= 20; risks.append("风险扫描未达趋势跟随底线。")
    return score, evidence, risks


def _growth_score(score, evidence, risks, technical, fundamental, capital, theme, risk):
    if fundamental >= 75: score += 22; evidence.append(f"基本面得分：{fundamental}")
    else: score -= 18; risks.append("盈利质量或预期证据不足。")
    if technical >= 60: score += 8
    else: risks.append("趋势未确认，需控制估值与时间成本。")
    if capital >= 60: score += 6
    if theme and theme.stage == "高潮": score -= 12; risks.append("题材高潮期会放大估值兑现风险。")
    if risk and risk.score >= 70: score += 10
    else: score -= 18; risks.append("风险扫描未达到机构研究底线。")
    return score, evidence, risks


def _value_score(score, evidence, risks, fundamental, technical, theme, risk):
    if fundamental >= 75: score += 22; evidence.append(f"基本面与现金流代理得分：{fundamental}")
    else: score -= 18; risks.append("财务质量不足以支撑价值/红利框架。")
    if risk and risk.score >= 75: score += 12; evidence.append(f"风险扫描：{risk.stage}")
    else: score -= 20; risks.append("高风险资产不应以价值标签放宽约束。")
    if theme and "高股息" in " ".join(theme.evidence): score += 8
    if technical < 45: score -= 10; risks.append("趋势过弱，需防范价值陷阱与机会成本。")
    return score, evidence, risks
