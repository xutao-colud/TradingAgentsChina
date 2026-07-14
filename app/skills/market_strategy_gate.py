from __future__ import annotations

from app.schemas.report import SkillInsight


def select_market_eligible_playbooks(insights: list[SkillInsight]) -> SkillInsight:
    """Select research routes from market evidence before stock/playbook interpretation.

    This is a deterministic suitability gate, not a return forecast or a trade
    instruction. A user profile may narrow the routes further, but cannot
    override a market-risk exclusion.
    """
    by_skill = {item.skill: item for item in insights}
    data_readiness = next((item for item in insights if item.category == "data_quality"), None)
    if data_readiness and data_readiness.score < 70:
        return SkillInsight(
            skill="市场状态策略门槛",
            category="strategy_selection",
            stage="数据不足",
            score=0,
            conclusion="市场状态输入未通过数据就绪性审查，不能选择或排除任何战法。",
            strategy="先补齐同一日期的市场宽度、行情和资金来源，再进行市场状态与战法匹配。",
            evidence=[f"数据状态：{data_readiness.stage}", *data_readiness.evidence[:3]],
            risks=list(data_readiness.risks),
            details={"allowed_playbooks": [], "excluded_playbooks": [], "mode": "market_first_gate"},
        )
    temperature = by_skill.get("A股市场温度计")
    sentiment = by_skill.get("情绪周期识别")
    money_making = by_skill.get("赚钱效应分析")

    temperature_score = temperature.score if temperature else 50
    sentiment_stage = sentiment.stage if sentiment else "未知"
    money_making_score = money_making.score if money_making else 50
    evidence = [
        f"市场温度 {temperature_score}",
        f"情绪周期 {sentiment_stage}",
        f"赚钱效应 {money_making_score}",
    ]
    risks: list[str] = ["该门槛只决定研究路线是否适配；个股仍须通过证据链、风险和交易规则审查。"]

    if sentiment_stage == "数据不足":
        allowed = []
        excluded = ["hot_money_leader", "trend_core", "institutional_growth", "institutional_value_dividend"]
        stage = "数据不足"
        score = 0
        conclusion = "连续情绪观察不足，无法识别启动、加速或退潮；不应据单日市场统计选择战法。"
        strategy = "先补齐配置要求数量的连续情绪观察，再重新评估市场状态与研究路线。"
        risks.append("单日涨停、炸板或连板数据不能替代情绪周期判断。")
    elif sentiment_stage in {"退潮", "冰点"} or temperature_score < 45 or money_making_score < 45:
        allowed = ["institutional_value_dividend"]
        excluded = ["hot_money_leader", "trend_core", "institutional_growth"]
        stage = "防守优先"
        score = 35
        conclusion = "市场证据不支持进攻型研究路线；保留价值/防守型观察，等待情绪和承接修复。"
        strategy = "优先保留研究记录和失效条件，暂不把短线接力或趋势追随作为主路线。"
        risks.append("退潮或冰点阶段的反弹可能缺乏持续性。")
    elif sentiment_stage in {"启动", "发酵"} and temperature_score >= 55 and money_making_score >= 55:
        allowed = ["hot_money_leader", "trend_core", "institutional_growth", "institutional_value_dividend"]
        excluded: list[str] = []
        stage = "进攻窗口"
        score = 75
        conclusion = "市场状态允许比较进攻与趋势研究路线，但仍需以个股资金、风险和规则证据决定是否继续。"
        strategy = "先比较趋势、题材和成长路线的证据适配度；不将市场窗口解释为交易指令。"
    else:
        allowed = ["trend_core", "institutional_growth", "institutional_value_dividend"]
        excluded = ["hot_money_leader"]
        stage = "平衡观察"
        score = 58
        conclusion = "市场处于平衡或分歧阶段，优先趋势、成长和价值研究；不支持把高波动接力作为默认路线。"
        strategy = "先验证趋势与基本面条件，再根据用户画像选择已获市场许可的战法。"
        risks.append("市场分歧会使同一策略的执行结果分散。")

    return SkillInsight(
        skill="市场状态策略门槛",
        category="strategy_selection",
        stage=stage,
        score=score,
        conclusion=conclusion,
        strategy=strategy,
        evidence=evidence,
        risks=risks,
        details={
            "allowed_playbooks": allowed,
            "excluded_playbooks": excluded,
            "market_inputs": {
                "temperature_score": temperature_score,
                "sentiment_stage": sentiment_stage,
                "money_making_score": money_making_score,
            },
            "mode": "market_first_gate",
        },
    )
