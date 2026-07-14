from __future__ import annotations

from app.config.runtime import load_runtime_settings
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
    config = load_runtime_settings().get("scoring", "playbook_evaluator")
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
    market_gate = next((item for item in insights if item.category == "strategy_selection"), None)

    score = config["base_score"]
    evidence = [f"当前原型：{playbook.name}（{playbook.group}）", f"研究周期：{playbook.horizon}"]
    risks: list[str] = []

    if playbook.id == "hot_money_leader":
        score, evidence, risks = _hot_money_score(score, evidence, risks, technical, capital, sentiment, money_making, theme, risk, config[playbook.id])
    elif playbook.id == "trend_core":
        score, evidence, risks = _trend_score(score, evidence, risks, technical, capital, sentiment, theme, risk, config[playbook.id])
    elif playbook.id == "institutional_growth":
        score, evidence, risks = _growth_score(score, evidence, risks, technical, fundamental, capital, theme, risk, config[playbook.id])
    else:
        score, evidence, risks = _value_score(score, evidence, risks, fundamental, technical, theme, risk, config[playbook.id])

    if market_gate:
        allowed_playbooks = market_gate.details.get("allowed_playbooks", [])
        if playbook.id not in allowed_playbooks:
            score = min(score, config["market_exclusion_cap"])
            risks.append(f"市场状态策略门槛为“{market_gate.stage}”，当前原型不在允许研究路线中。")
            evidence.append(f"市场状态策略门槛：{market_gate.stage}")

    score = max(load_runtime_settings().get("scoring", "score_bounds", "min"), min(load_runtime_settings().get("scoring", "score_bounds", "max"), score))
    if market_gate and market_gate.stage == "数据不足":
        stage = "数据不足"
        conclusion = f"关键数据未通过审查，暂不评估{playbook.name}与当前市场的适配度。"
        strategy = "补齐真实、同日期的关键来源后，再将用户画像与战法规则用于比较。"
    elif market_gate and playbook.id not in market_gate.details.get("allowed_playbooks", []):
        stage = "市场不适配"
        conclusion = f"当前市场状态不支持按{playbook.name}推进研究；用户偏好不能覆盖市场风险门槛。"
        strategy = "保留用户画像用于后续匹配，先等待市场门槛重新开放该研究路线。"
    elif score >= config["fit_threshold"]:
        stage = "适配"
        conclusion = f"当前市场与个股证据基本满足{playbook.name}的研究前提"
        strategy = f"优化建议：{playbook.optimization_focus}"
    elif score >= config["watch_threshold"]:
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


def _hot_money_score(score, evidence, risks, technical, capital, sentiment, money_making, theme, risk, config):
    if sentiment and sentiment.stage in set(config["sentiment_stages"]):
        score += config["sentiment_bonus"]; evidence.append(f"情绪阶段：{sentiment.stage}")
    else:
        score -= config["sentiment_penalty"]; risks.append("情绪不在启动/发酵窗口，短线接力条件不足。")
    if money_making and money_making.score >= config["money_threshold"]:
        score += config["money_bonus"]; evidence.append(f"赚钱效应得分：{money_making.score}")
    else: risks.append("赚钱效应不足，隔日兑现风险更高。")
    if capital >= config["capital_threshold"]: score += config["capital_bonus"]; evidence.append(f"资金面得分：{capital}")
    else: risks.append("资金流未完成确认。")
    if technical >= config["technical_threshold"]: score += config["technical_bonus"]
    if theme and theme.stage in set(config["theme_stages"]): score += config["theme_bonus"]
    if risk and risk.score < config["risk_threshold"]: score -= config["risk_penalty"]; risks.append("风险扫描未达短线参与底线。")
    return score, evidence, risks


def _trend_score(score, evidence, risks, technical, capital, sentiment, theme, risk, config):
    if technical >= config["technical_threshold"]: score += config["technical_bonus"]; evidence.append(f"技术趋势得分：{technical}")
    else: score -= config["technical_penalty"]; risks.append("趋势尚未确认，避免把反弹当趋势。")
    if capital >= config["capital_threshold"]: score += config["capital_bonus"]; evidence.append(f"资金面得分：{capital}")
    else: risks.append("资金连续性需要复核。")
    if theme and theme.stage in set(config["theme_stages"]): score += config["theme_bonus"]; evidence.append(f"题材阶段：{theme.stage}")
    if sentiment and sentiment.stage in set(config["sentiment_risk_stages"]): score -= config["sentiment_penalty"]; risks.append(f"情绪处于{sentiment.stage}，不宜把加速段当回踩机会。")
    if risk and risk.score < config["risk_threshold"]: score -= config["risk_penalty"]; risks.append("风险扫描未达趋势跟随底线。")
    return score, evidence, risks


def _growth_score(score, evidence, risks, technical, fundamental, capital, theme, risk, config):
    if fundamental >= config["fundamental_threshold"]: score += config["fundamental_bonus"]; evidence.append(f"基本面得分：{fundamental}")
    else: score -= config["fundamental_penalty"]; risks.append("盈利质量或预期证据不足。")
    if technical >= config["technical_threshold"]: score += config["technical_bonus"]
    else: risks.append("趋势未确认，需控制估值与时间成本。")
    if capital >= config["capital_threshold"]: score += config["capital_bonus"]
    if theme and theme.stage == config["theme_risk_stage"]: score -= config["theme_penalty"]; risks.append("题材高潮期会放大估值兑现风险。")
    if risk and risk.score >= config["risk_threshold"]: score += config["risk_bonus"]
    else: score -= config["risk_penalty"]; risks.append("风险扫描未达到机构研究底线。")
    return score, evidence, risks


def _value_score(score, evidence, risks, fundamental, technical, theme, risk, config):
    if fundamental >= config["fundamental_threshold"]: score += config["fundamental_bonus"]; evidence.append(f"基本面与现金流代理得分：{fundamental}")
    else: score -= config["fundamental_penalty"]; risks.append("财务质量不足以支撑价值/红利框架。")
    if risk and risk.score >= config["risk_threshold"]: score += config["risk_bonus"]; evidence.append(f"风险扫描：{risk.stage}")
    else: score -= config["risk_penalty"]; risks.append("高风险资产不应以价值标签放宽约束。")
    if theme and config["theme_keyword"] in " ".join(theme.evidence): score += config["theme_bonus"]
    if technical < config["technical_threshold"]: score -= config["technical_penalty"]; risks.append("趋势过弱，需防范价值陷阱与机会成本。")
    return score, evidence, risks
