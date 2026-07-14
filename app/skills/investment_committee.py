from __future__ import annotations

import re

from dataclasses import dataclass

from app.config.runtime import load_runtime_settings
from app.schemas.report import (
    AgentFinding,
    AshareMarketSignals,
    DataQualityReport,
    EvidenceSource,
    IntradaySnapshot,
    MoneyFlowSnapshot,
    SkillInsight,
)
from app.skills.common import clamp_score


@dataclass(frozen=True)
class FactionView:
    name: str
    route: str
    score: int
    rationale: list[str]
    risks: list[str]
    base_score: int
    score_adjustments: list[dict[str, object]]
    score_explanation: str


@dataclass(frozen=True)
class _CommitteeSignal:
    name: str
    status: str
    observed: str
    values: dict[str, float]
    as_of: str | None
    source_ids: list[str]
    quality_status: str
    limitations: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "observed": self.observed,
            "values": dict(self.values),
            "as_of": self.as_of,
            "source_ids": list(self.source_ids),
            "quality_status": self.quality_status,
            "limitations": list(self.limitations),
        }


def assess_investment_faction_committee(
    findings: list[AgentFinding],
    skill_insights: list[SkillInsight],
    invalid_conditions: list[str],
    user_question: str | None = None,
    *,
    analysis_date: str | None = None,
    market_signals: AshareMarketSignals | None = None,
    money_flow: MoneyFlowSnapshot | None = None,
    intraday: IntradaySnapshot | None = None,
    evidence_sources: list[EvidenceSource] | None = None,
    quality_reports: list[DataQualityReport] | None = None,
) -> SkillInsight:
    """Compare A-share investment schools under the same evidence set.

    The score is a deterministic evidence-fit score for research routing, not a
    forecast, a return claim, or a backtested win rate. It helps the product
    decide which playbook is currently the most persuasive for the user's next
    layer of analysis.
    """

    data_readiness = next((item for item in skill_insights if item.category == "data_quality"), None)
    if data_readiness and data_readiness.score < 70:
        topic = _normalize_topic(user_question)
        return SkillInsight(
            skill="投资流派委员会",
            category="committee",
            stage="证据不足",
            score=0,
            conclusion="委员会拒绝裁决：市场和个股输入未通过数据就绪性审查。",
            strategy="先补齐真实、同日期的关键来源；在此之前不选择领先流派或战法。",
            evidence=[f"研讨问题：{topic}", f"数据状态：{data_readiness.stage}", *data_readiness.evidence[:4]],
            risks=list(data_readiness.risks),
            details={
                "mode": "court",
                "user_question": topic,
                "judge": {"discussion_topic": topic, "verdict": "证据不足，拒绝裁决。", "action": "补齐数据后重新开庭。"},
                "factions": [],
                "cross_examination": [],
                "risk_challenge": {"role": "risk_challenge", "verdict": "关键数据不充分，禁止路线比较。"},
            },
        )

    agent_scores = {item.agent: item.score for item in findings}
    agent_details = {item.agent: item.details for item in findings}
    skills = {item.skill: item for item in skill_insights}
    topic = _normalize_topic(user_question)
    context = _Context(
        agent_scores=agent_scores,
        agent_details=agent_details,
        skills=skills,
        invalid_conditions=invalid_conditions,
        user_question=topic,
        analysis_date=analysis_date,
        market_signals=market_signals,
        money_flow=money_flow,
        intraday=intraday,
        evidence_sources=list(evidence_sources or []),
        quality_reports=list(quality_reports or []),
    )
    factions = sorted(
        [
            _aggressive_hot_money(context),
            _trend_capacity(context),
            _institutional_growth(context),
            _value_dividend(context),
            _policy_cycle(context),
            _reversal_low_absorption(context),
            _defensive_risk_control(context),
        ],
        key=lambda item: item.score,
        reverse=True,
    )
    winner = factions[0]
    runner_up = factions[1]
    score_gap = winner.score - runner_up.score
    if winner.score >= 72 and score_gap >= 6:
        stage = winner.name
        conclusion = f"当前证据对{winner.name}的适配度明显领先。"
    elif winner.score >= 62:
        stage = f"{winner.name}/分歧"
        conclusion = f"{winner.name}暂时领先，但与{runner_up.name}分歧不大。"
    else:
        stage = "无明显优势"
        conclusion = "各流派证据都不充分，当前不宜强行套用单一战法。"

    evidence = [
        f"研讨问题：{topic}",
        f"证据适配度排名：{_rank_line(factions)}",
        f"领先路线：{winner.name}（{winner.route}）",
        f"领先理由：{'；'.join(winner.rationale[:3])}",
        f"第二路线：{runner_up.name}（{runner_up.score}分）",
    ]
    if invalid_conditions:
        evidence.append(f"规则约束：{len(invalid_conditions)} 项否决/降级条件")
    risks = [
        "该分数是基于当前样例证据的路线选择信号，不代表战法因果有效或未来收益承诺。",
        "真实 SaaS 版本必须按市场阶段、持有期、交易成本和样本外结果继续验证。",
    ]
    risks.extend(winner.risks[:3])
    strategy = _strategy_for_winner(winner)
    details = {
        "mode": "court",
        "user_question": topic,
        "judge": {
            "winner": winner.name,
            "winner_route": winner.route,
            "runner_up": runner_up.name,
            "discussion_topic": topic,
            "score_gap": score_gap,
            "reliability": _reliability_label(winner.score, score_gap),
            "score_method": "分数 = 流派基础分 + 市场/技术/资金/题材/风险/规则约束加减分，最终限制在 0-100。",
            "score_summary": f"{winner.name} {winner.score} 分，{runner_up.name} {runner_up.score} 分，领先 {score_gap} 分。",
            "score_warning": "分数只代表当前证据对流派路线的适配度，不代表收益概率、胜率或买卖承诺。",
            "verdict": conclusion,
            "reason": winner.rationale[:3],
            "action": _judge_action_for_question(winner, topic, strategy),
        },
        "factions": [_faction_detail(item, item.name == winner.name, topic) for item in factions],
        "cross_examination": _court_cross_examination(factions),
        "risk_challenge": _risk_challenge(context, findings),
        "signal_evidence": {name: signal.to_dict() for name, signal in context.signals.items()},
        "decision_context": {
            "dragon_tiger_signal": context.dragon_tiger_signal.to_dict(),
            "northbound_days": context.northbound_days,
            "margin_trend": context.margin_trend,
            "tiered_money_flow": context.signal("tiered_money_flow").to_dict(),
        },
    }
    return SkillInsight(
        skill="投资流派委员会",
        category="committee",
        stage=stage,
        score=winner.score,
        conclusion=conclusion,
        strategy=strategy,
        evidence=evidence,
        risks=risks,
        details=details,
    )


@dataclass(frozen=True)
class _Context:
    agent_scores: dict[str, int]
    agent_details: dict[str, dict[str, object]]
    skills: dict[str, SkillInsight]
    invalid_conditions: list[str]
    user_question: str
    analysis_date: str | None
    market_signals: AshareMarketSignals | None
    money_flow: MoneyFlowSnapshot | None
    intraday: IntradaySnapshot | None
    evidence_sources: list[EvidenceSource]
    quality_reports: list[DataQualityReport]

    def agent(self, name: str, default: int = 50) -> int:
        return self.agent_scores.get(name, default)

    def agent_detail(self, name: str) -> dict[str, object]:
        return self.agent_details.get(name, {})

    def skill(self, name: str) -> SkillInsight | None:
        return self.skills.get(name)

    @property
    def source_ids(self) -> set[str]:
        return {item.id for item in self.evidence_sources}

    def quality_status(self, dataset: str, provider: str | None = None) -> str:
        reports = [
            item
            for item in self.quality_reports
            if item.dataset == dataset and (provider is None or item.provider == provider)
        ]
        if not reports:
            return "not_checked"
        if any(item.status == "failed" for item in reports):
            return "failed"
        if any(item.status == "warning" for item in reports):
            return "warning"
        return "passed"

    @property
    def signals(self) -> dict[str, _CommitteeSignal]:
        return {
            "dragon_tiger": _dragon_tiger_signal(self),
            "dragon_tiger_history": _dragon_tiger_history_signal(self),
            "margin_financing": _margin_signal(self),
            "northbound_holding": _northbound_signal(self),
            "tiered_money_flow": _tiered_money_flow_signal(self),
            "capital_flow_continuity": _capital_flow_continuity_signal(self),
            "intraday": _intraday_signal(self),
            "a_share_characteristics": _derived_skill_signal(
                self, "a_share_characteristics", "A股涨停结构", "market_sentiment", "market-001"
            ),
            "turnover_continuity": _derived_skill_signal(
                self, "turnover_continuity", "换手率连续变化", "daily_prices", "price-001"
            ),
            "ah_premium": _derived_skill_signal(
                self, "ah_premium", "AH股溢价观察", "ah_premium", "ah-premium-001"
            ),
        }

    def signal(self, name: str) -> _CommitteeSignal:
        return self.signals[name]

    @property
    def dragon_tiger_signal(self) -> _CommitteeSignal:
        return _dragon_tiger_signal(self)

    @property
    def northbound_days(self) -> int | None:
        return _continuity_streak(self, "northbound_streak_days")

    @property
    def margin_trend(self) -> int | None:
        return _continuity_streak(self, "margin_balance_streak_days")

    @property
    def risk_score(self) -> int:
        risk = self.skill("A股风险扫描器")
        return risk.score if risk else 60

    @property
    def sentiment_stage(self) -> str:
        sentiment = self.skill("情绪周期识别")
        return sentiment.stage if sentiment else "未知"

    @property
    def theme_stage(self) -> str:
        theme = self.skill("热点生命周期分析")
        return theme.stage if theme else "未知"

    @property
    def market_temperature(self) -> int:
        market = self.skill("A股市场温度计")
        return market.score if market else self.agent("市场周期 Agent")

    @property
    def money_making_score(self) -> int:
        money_making = self.skill("赚钱效应分析")
        return money_making.score if money_making else 50

    @property
    def main_force_stage(self) -> str:
        main_force = self.skill("主力资金行为识别")
        return main_force.stage if main_force else "未知"

    @property
    def invalid_penalty(self) -> int:
        return min(35, len(self.invalid_conditions) * 12)


def _dragon_tiger_signal(context: _Context) -> _CommitteeSignal:
    quality = context.quality_status("dragon_tiger")
    records = list(context.market_signals.dragon_tiger) if context.market_signals else []
    if context.market_signals is not None and context.market_signals.data_status != "verified":
        return _rejected_signal("dragon_tiger", quality, "市场扩展信号不是已核验生产数据，不进入委员会计分。")
    if quality != _committee_signal_config()["required_quality_status"]:
        return _rejected_signal("dragon_tiger", quality, "龙虎榜语义质量未通过，不进入委员会计分。")
    if not records:
        return _unavailable_signal("dragon_tiger", quality, "当日没有该股票的龙虎榜披露记录。")
    source_ids = _unique([item.source_id for item in records])
    trade_dates = _unique([item.trade_date for item in records])
    if not _dates_match(context.analysis_date, trade_dates) or not _sources_are_traceable(context, source_ids):
        return _rejected_signal("dragon_tiger", quality, "龙虎榜日期未对齐或来源不可追溯。", source_ids, trade_dates[-1] if trade_dates else None)
    net_amount = sum(item.net_buy_amount for item in records)
    institution_values = [item.institution_net_amount for item in records if item.institution_net_amount is not None]
    values = {"net_amount": net_amount}
    if institution_values:
        values["institution_net_amount"] = sum(institution_values)
    depth = context.agent_detail("龙虎榜 Agent")
    for key in ("buy_concentration", "sell_concentration"):
        value = depth.get(key)
        if isinstance(value, (int, float)):
            values[key] = float(value)
    seat_type_counts = depth.get("seat_type_counts")
    if isinstance(seat_type_counts, dict):
        for key, value in seat_type_counts.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values[f"seat_type_count:{key}"] = float(value)
    known_hot_money_seat_count = depth.get("known_hot_money_seat_count")
    if isinstance(known_hot_money_seat_count, (int, float)) and not isinstance(known_hot_money_seat_count, bool):
        values["known_hot_money_seat_count"] = float(known_hot_money_seat_count)
    return _CommitteeSignal(
        "dragon_tiger",
        "admitted",
        f"龙虎榜净额 {net_amount:.0f}，机构席位净额 {values.get('institution_net_amount', '未披露')}",
        values,
        trade_dates[-1],
        source_ids,
        quality,
        ["龙虎榜只覆盖触发披露条件的交易，不能代表全部短线资金。"],
    )


def _dragon_tiger_history_signal(context: _Context) -> _CommitteeSignal:
    current_signal = context.dragon_tiger_signal
    quality = context.quality_status("dragon_tiger_history")
    if current_signal.status != "admitted":
        return _unavailable_signal("dragon_tiger_history", quality, "当日龙虎榜席位证据未获准，历史后效不参与计分。")
    if quality != _committee_signal_config()["required_quality_status"]:
        return _rejected_signal("dragon_tiger_history", quality, "龙虎榜席位历史质量未通过，不进入委员会计分。")
    detail = context.agent_detail("龙虎榜 Agent")
    metrics = detail.get("seat_history_metrics")
    if not isinstance(metrics, dict):
        return _unavailable_signal("dragon_tiger_history", quality, "缺少结构化席位历史后效。")
    config = _committee_signal_config()["dragon_tiger_history"]
    horizon = str(int(config["horizon_days"]))
    minimum = int(config["minimum_observations"])
    admitted: list[tuple[int, float]] = []
    seat_count = 0
    for seat_metric in metrics.values():
        if not isinstance(seat_metric, dict) or seat_metric.get("seat_type") != "游资席位":
            continue
        horizons = seat_metric.get("horizons")
        horizon_metric = horizons.get(horizon) if isinstance(horizons, dict) else None
        if not isinstance(horizon_metric, dict):
            continue
        observations = horizon_metric.get("observations")
        positive_ratio = horizon_metric.get("positive_observation_ratio")
        if (
            isinstance(observations, int)
            and observations >= minimum
            and isinstance(positive_ratio, (int, float))
            and not isinstance(positive_ratio, bool)
        ):
            admitted.append((observations, float(positive_ratio)))
            seat_count += 1
    if not admitted:
        return _unavailable_signal(
            "dragon_tiger_history",
            quality,
            "已识别游资席位在配置观察期内没有达到最小样本要求的历史后效。",
        )
    observations = sum(item[0] for item in admitted)
    positive_ratio = sum(count * ratio for count, ratio in admitted) / observations
    source_ids = ["dragon-tiger-history-001"] if "dragon-tiger-history-001" in context.source_ids else []
    source = next((item for item in context.evidence_sources if item.id == "dragon-tiger-history-001"), None)
    as_of = source.as_of if source else None
    if not source_ids or not as_of or not _date_not_after(context.analysis_date, as_of):
        return _rejected_signal(
            "dragon_tiger_history",
            quality,
            "龙虎榜席位历史来源不可追溯或观察截止日未与分析日对齐。",
            source_ids,
            as_of,
        )
    return _CommitteeSignal(
        "dragon_tiger_history",
        "admitted",
        f"已识别游资席位 {seat_count} 个，{horizon}日后正收益观察占比 {positive_ratio:.0%}（席位事件 n={observations}）",
        {
            "seat_count": float(seat_count),
            "horizon_days": float(horizon),
            "observations": float(observations),
            "positive_observation_ratio": positive_ratio,
        },
        as_of,
        source_ids,
        quality,
        ["席位事件并非相互独立样本，历史后效是观察性证据，不代表因果、胜率或未来可复制性。"],
    )


def _margin_signal(context: _Context) -> _CommitteeSignal:
    quality = context.quality_status("margin_financing")
    record = context.market_signals.margin_financing if context.market_signals else None
    if context.market_signals is not None and context.market_signals.data_status != "verified":
        return _rejected_signal("margin_financing", quality, "市场扩展信号不是已核验生产数据，不进入委员会计分。")
    if quality != _committee_signal_config()["required_quality_status"]:
        return _rejected_signal("margin_financing", quality, "融资融券语义质量未通过，不进入委员会计分。")
    if record is None or context.money_flow is None or context.money_flow.margin_balance_change is None:
        return _unavailable_signal("margin_financing", quality, "缺少同日融资余额活动变化。")
    source_ids = [record.source_id]
    if not _dates_match(context.analysis_date, [record.trade_date]) or not _sources_are_traceable(context, source_ids):
        return _rejected_signal("margin_financing", quality, "融资融券日期未对齐或来源不可追溯。", source_ids, record.trade_date)
    change = float(context.money_flow.margin_balance_change)
    values = {"balance_activity_change_pct": change}
    if record.margin_balance is not None:
        values["margin_balance"] = float(record.margin_balance)
    return _CommitteeSignal(
        "margin_financing",
        "admitted",
        f"融资余额活动变化 {change:.2f}%",
        values,
        record.trade_date,
        source_ids,
        quality,
        ["该指标反映当日融资买入与偿还相对余额的活动变化，不等同于多日余额趋势。"],
    )


def _northbound_signal(context: _Context) -> _CommitteeSignal:
    record = context.market_signals.northbound_holding if context.market_signals else None
    provider = "akshare" if record and "akshare" in record.source_id else "tushare"
    quality = context.quality_status("northbound_holding", provider)
    if context.market_signals is not None and context.market_signals.data_status != "verified":
        return _rejected_signal("northbound_holding", quality, "市场扩展信号不是已核验生产数据，不进入委员会计分。")
    if quality != _committee_signal_config()["required_quality_status"]:
        return _rejected_signal("northbound_holding", quality, "北向持股语义质量未通过，不进入委员会计分。")
    if record is None or record.holding_change is None:
        return _unavailable_signal("northbound_holding", quality, "缺少北向持股变化。")
    source_ids = [record.source_id]
    if not _dates_match(context.analysis_date, [record.trade_date]) or not _sources_are_traceable(context, source_ids):
        return _rejected_signal("northbound_holding", quality, "北向持股日期未对齐或来源不可追溯。", source_ids, record.trade_date)
    change = float(record.holding_change)
    return _CommitteeSignal(
        "northbound_holding",
        "admitted",
        f"北向持股变化 {change:.0f}",
        {"holding_change": change},
        record.trade_date,
        source_ids,
        quality,
        ["持股数量变化未按自由流通市值标准化，只作为方向性机构证据。"],
    )


def _tiered_money_flow_signal(context: _Context) -> _CommitteeSignal:
    insight = context.skill("资金流分档分析")
    if insight is None or insight.stage in {"数据不足", "信号不足"}:
        return _unavailable_signal("tiered_money_flow", "not_checked", "资金流分档缺失或绝对流量不足。")
    source_ids = ["flow-001"] if "flow-001" in context.source_ids else []
    as_of = context.money_flow.as_of if context.money_flow else None
    if not _dates_match(context.analysis_date, [as_of] if as_of else []) or not source_ids:
        return _rejected_signal("tiered_money_flow", "not_checked", "资金流分档日期未对齐或来源不可追溯。", source_ids, as_of)
    values = {"score": float(insight.score)}
    values.update({key: float(value) for key, value in insight.details.items() if isinstance(value, (int, float))})
    return _CommitteeSignal(
        "tiered_money_flow",
        "admitted",
        f"{insight.stage}，证据适配分 {insight.score}",
        values,
        as_of,
        source_ids,
        "derived",
        list(insight.risks),
    )


def _capital_flow_continuity_signal(context: _Context) -> _CommitteeSignal:
    insight = context.skill("资金流连续性分析")
    quality = context.quality_status("capital_flow_history")
    if insight is None or insight.stage == "数据不足":
        return _unavailable_signal("capital_flow_continuity", quality, "多日资金历史不足，连续性信号不可用。")
    if quality != _committee_signal_config()["required_quality_status"]:
        return _rejected_signal("capital_flow_continuity", quality, "多日资金历史质量未通过，不进入委员会计分。")
    source_ids = [str(item) for item in insight.details.get("source_ids", [])]
    as_of = str(insight.details.get("as_of") or "")
    if not _dates_match(context.analysis_date, [as_of]) or not _sources_are_traceable(context, source_ids):
        return _rejected_signal(
            "capital_flow_continuity",
            quality,
            "多日资金历史日期未对齐或来源不可追溯。",
            source_ids,
            as_of or None,
        )
    values = {"score": float(insight.score)}
    for key in ("main_streak_days", "northbound_streak_days", "margin_balance_streak_days"):
        value = insight.details.get(key)
        if isinstance(value, (int, float)):
            values[key] = float(value)
    return _CommitteeSignal(
        "capital_flow_continuity",
        "admitted",
        insight.conclusion,
        values,
        as_of,
        source_ids,
        quality,
        list(insight.risks),
    )


def _continuity_streak(context: _Context, key: str) -> int | None:
    signal = _capital_flow_continuity_signal(context)
    value = signal.values.get(key) if signal.status == "admitted" else None
    return int(value) if isinstance(value, (int, float)) else None


def _intraday_signal(context: _Context) -> _CommitteeSignal:
    insight = context.skill("盘中分时盘口分析")
    imbalance = insight.details.get("order_book_imbalance") if insight else None
    if insight is None or context.intraday is None or insight.stage == "数据不足" or imbalance is None:
        return _unavailable_signal("intraday", "not_checked", "缺少可用的同日盘口委托不平衡。")
    source_ids = list(context.intraday.source_ids)
    if not _dates_match(context.analysis_date, [context.intraday.as_of]) or not _sources_are_traceable(context, source_ids):
        return _rejected_signal("intraday", "not_checked", "盘口日期未对齐或来源不可追溯。", source_ids, context.intraday.as_of)
    return _CommitteeSignal(
        "intraday",
        "admitted",
        f"盘口委托不平衡 {float(imbalance):.2%}，{insight.stage}",
        {"order_book_imbalance": float(imbalance), "score": float(insight.score)},
        context.intraday.as_of,
        source_ids,
        "derived",
        list(insight.risks),
    )


def _derived_skill_signal(
    context: _Context,
    name: str,
    skill_name: str,
    dataset: str,
    expected_source_id: str,
) -> _CommitteeSignal:
    insight = context.skill(skill_name)
    reports = [item for item in context.quality_reports if item.dataset == dataset]
    quality = "passed" if any(item.status == "passed" for item in reports) else context.quality_status(dataset)
    if insight is None or insight.details.get("admitted") is not True:
        return _unavailable_signal(name, quality, f"{skill_name}缺少可采信的同日观测。")
    source_ids = [str(item) for item in insight.details.get("source_ids", [])]
    as_of = str(insight.details.get("as_of") or "")
    if expected_source_id not in source_ids:
        return _rejected_signal(name, quality, f"{skill_name}缺少预期来源标识。", source_ids, as_of or None)
    if quality != _committee_signal_config()["required_quality_status"]:
        return _rejected_signal(name, quality, f"{skill_name}数据质量未通过，不进入委员会计分。", source_ids, as_of or None)
    if not _dates_match(context.analysis_date, [as_of]) or not _sources_are_traceable(context, source_ids):
        return _rejected_signal(name, quality, f"{skill_name}日期未对齐或来源不可追溯。", source_ids, as_of or None)
    values = {"score": float(insight.score)}
    values.update({
        str(key): float(value)
        for key, value in insight.details.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    })
    return _CommitteeSignal(
        name,
        "admitted",
        insight.conclusion,
        values,
        as_of,
        source_ids,
        quality,
        list(insight.risks),
    )


def _committee_signal_config() -> dict[str, object]:
    return load_runtime_settings().get("scoring", "committee_signals")


def _dates_match(analysis_date: str | None, observed_dates: list[str]) -> bool:
    return bool(analysis_date and observed_dates) and all(value.startswith(analysis_date) for value in observed_dates)


def _date_not_after(analysis_date: str | None, observed_date: str) -> bool:
    return bool(analysis_date and observed_date) and observed_date[:10] <= analysis_date


def _sources_are_traceable(context: _Context, source_ids: list[str]) -> bool:
    by_id = {item.id: item for item in context.evidence_sources}
    return bool(source_ids) and all(
        source_id in by_id
        and context.analysis_date is not None
        and by_id[source_id].as_of.startswith(context.analysis_date)
        for source_id in source_ids
    )


def _unavailable_signal(name: str, quality: str, reason: str) -> _CommitteeSignal:
    return _CommitteeSignal(name, "unavailable", reason, {}, None, [], quality, [reason])


def _rejected_signal(
    name: str,
    quality: str,
    reason: str,
    source_ids: list[str] | None = None,
    as_of: str | None = None,
) -> _CommitteeSignal:
    return _CommitteeSignal(name, "rejected", reason, {}, as_of, list(source_ids or []), quality, [reason])


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _directional_impact(value: float, magnitude: int) -> int:
    return magnitude if value > 0 else -magnitude if value < 0 else 0


def _continuous_impact(value: float, scale: float, maximum: int) -> int:
    if scale <= 0:
        return 0
    return int(round(max(-maximum, min(maximum, value / scale * maximum))))


def _score_signal_impact(score: float, neutral: float, span: float, maximum: int) -> int:
    if span <= 0:
        return 0
    return int(round(max(-maximum, min(maximum, (score - neutral) / span * maximum))))


def _signal_adjustment(
    item: str,
    signal: _CommitteeSignal,
    impact: int,
    reason: str,
    threshold: str,
) -> dict[str, object]:
    return _score_adjustment(
        item,
        impact,
        reason,
        observed=signal.observed,
        threshold=threshold,
        source=f"{signal.name} typed evidence",
        source_ids=signal.source_ids,
        as_of=signal.as_of,
        evidence_status=signal.status,
    )


def _append_signal_gap(risks: list[str], signal: _CommitteeSignal, label: str) -> None:
    if signal.status == "rejected":
        risks.append(f"{label}证据被质量或追溯门禁驳回：{signal.observed}")


def _append_skill_score_adjustment(
    context: _Context,
    adjustments: list[dict[str, object]],
    risks: list[str],
    signal_name: str,
    label: str,
    maximum_impact_key: str,
    reason: str,
) -> None:
    signal = context.signal(signal_name)
    if signal.status != "admitted":
        _append_signal_gap(risks, signal, label)
        return
    config = _committee_signal_config()[signal_name]
    impact = _score_signal_impact(
        signal.values["score"],
        float(config["neutral_score"]),
        float(config["score_span"]),
        int(config[maximum_impact_key]),
    )
    adjustments.append(_signal_adjustment(
        label,
        signal,
        impact,
        reason,
        "只采信同日、质量通过且来源可追溯的确定性 Skill；分数代表证据适配度，不是胜率。",
    ))


def _append_ah_premium_adjustment(
    context: _Context,
    adjustments: list[dict[str, object]],
    risks: list[str],
    maximum_impact_key: str,
) -> None:
    signal = context.signal("ah_premium")
    if signal.status != "admitted":
        _append_signal_gap(risks, signal, "AH股溢价")
        return
    config = _committee_signal_config()["ah_premium"]
    premium_delta = signal.values["premium_pct"] - float(config["neutral_premium_pct"])
    impact = _continuous_impact(
        -premium_delta,
        float(config["premium_scale_pct"]),
        int(config[maximum_impact_key]),
    )
    adjustments.append(_signal_adjustment(
        "AH股相对估值",
        signal,
        impact,
        "A股相对H股溢价越高，跨市场相对估值约束越强；该信号只使用小权重。",
        "溢价上升扣分、折价加分；不覆盖基本面、股东权利、流动性和汇率差异。",
    ))


def _append_continuity_adjustment(
    context: _Context,
    adjustments: list[dict[str, object]],
    risks: list[str],
    value_key: str,
    label: str,
    maximum_impact_key: str,
    reason: str,
) -> None:
    signal = context.signal("capital_flow_continuity")
    if signal.status != "admitted":
        _append_signal_gap(risks, signal, "资金流连续性")
        return
    config = _committee_signal_config()["capital_flow_continuity"]
    value = signal.values.get(value_key)
    if not isinstance(value, (int, float)):
        risks.append(f"{label}历史覆盖不足，未进入本流派计分。")
        return
    impact = _continuous_impact(float(value), float(config["streak_scale_days"]), int(config[maximum_impact_key]))
    adjustments.append(_signal_adjustment(
        label,
        signal,
        impact,
        reason,
        "正连续天数加分、负连续天数扣分；仅采信日期连续、来源可追溯且质量通过的历史。",
    ))


def _append_industry_prosperity_adjustment(
    context: _Context,
    adjustments: list[dict[str, object]],
    risks: list[str],
    maximum_impact_key: str,
    reason: str,
) -> None:
    insight = context.skill("行业景气度分析")
    if insight is None or not bool(insight.details.get("admissible")):
        risks.append("行业景气证据不足，未进入本流派计分。")
        return
    source_ids = [str(item) for item in insight.details.get("source_ids", [])]
    if not source_ids or not set(source_ids).issubset(context.source_ids):
        risks.append("行业景气来源不可完整追溯，委员会已驳回该项证据。")
        return
    config = _committee_signal_config()["industry_prosperity"]
    impact = _score_signal_impact(
        float(insight.score),
        float(config["neutral_score"]),
        float(config["score_span"]),
        int(config[maximum_impact_key]),
    )
    adjustments.append(_score_adjustment(
        "行业景气度",
        impact,
        reason,
        observed=f"{insight.stage}，证据适配分 {insight.score}",
        threshold="仅采纳已通过行业资金质量门禁且来源可追溯的确定性 Skill；该分数不是胜率",
        source="行业景气度分析 Skill",
        source_ids=source_ids,
        as_of=str(insight.details.get("as_of") or context.analysis_date or "unknown"),
        evidence_status="admitted",
    ))


def _aggressive_hot_money(context: _Context) -> FactionView:
    base = 30
    adjustments: list[dict[str, object]] = []
    rationale: list[str] = []
    risks: list[str] = []
    if context.sentiment_stage == "发酵":
        adjustments.append(_score_adjustment("情绪周期", 18, "发酵期更适合游资接力，市场承接通常更强。"))
        rationale.append("情绪进入发酵期")
    elif context.sentiment_stage == "启动":
        adjustments.append(_score_adjustment("情绪周期", 8, "启动期有试错窗口，但接力确定性还未充分展开。"))
        rationale.append(f"情绪处于{context.sentiment_stage}")
    else:
        adjustments.append(_score_adjustment("情绪周期", -18, f"情绪处于{context.sentiment_stage}，高位接力容错下降。"))
        risks.append(f"情绪处于{context.sentiment_stage}，接力容错下降")
    money_making_adj = _scaled(context.money_making_score, 60, 12)
    capital_adj = _scaled(context.agent("资金流 Agent"), 65, 10)
    theme_adj = _scaled(context.agent("题材热点 Agent"), 60, 6)
    adjustments.append(_score_adjustment("赚钱效应", money_making_adj, f"赚钱效应 {context.money_making_score} 分，决定短线资金是否愿意继续进攻。"))
    adjustments.append(_score_adjustment("资金流", capital_adj, f"资金流 Agent {context.agent('资金流 Agent')} 分，游资派要求资金连续。"))
    adjustments.append(_score_adjustment("题材强度", theme_adj, f"题材热点 Agent {context.agent('题材热点 Agent')} 分，题材越强接力越有共识。"))
    signal_config = _committee_signal_config()
    _append_continuity_adjustment(
        context, adjustments, risks, "main_streak_days", "主力资金连续性",
        "aggressive_main_max_impact", "主力净流入连续天数用于质证单日龙虎榜和分档资金是否获得延续。",
    )
    _append_skill_score_adjustment(context, adjustments, risks, "a_share_characteristics", "涨停结构", "aggressive_max_impact", "封板率、一字板和连板梯队共同质证短线情绪承接。")
    _append_skill_score_adjustment(context, adjustments, risks, "turnover_continuity", "换手连续性", "aggressive_max_impact", "多日换手变化用于区分资金活跃度延续与单日噪音。")
    dragon = context.dragon_tiger_signal
    if dragon.status == "admitted":
        impact = _directional_impact(
            dragon.values["net_amount"],
            int(signal_config["dragon_tiger"]["aggressive_direction_impact"]),
        )
        adjustments.append(_signal_adjustment("龙虎榜净额", dragon, impact, "龙虎榜公开净额只作为当日短线承接的方向性佐证。", "净买入加分、净卖出扣分；不据此识别具体游资身份"))
        concentration = max(dragon.values.get("buy_concentration", 0.0), dragon.values.get("sell_concentration", 0.0))
        depth_config = load_runtime_settings().get("domain_knowledge", "dragon_tiger_depth")
        if concentration >= float(depth_config["high_concentration_ratio"]):
            adjustments.append(_signal_adjustment(
                "龙虎榜席位集中度",
                dragon,
                -int(depth_config["concentration_risk_penalty"]),
                f"披露席位集中度 {concentration:.1%}，少数席位反向交易可能放大兑现波动。",
                "集中度只作流动性与兑现风险扣分，不推断席位操纵意图",
            ))
        hot_money_count = dragon.values.get("known_hot_money_seat_count", 0.0)
        if hot_money_count > 0:
            type_config = signal_config["dragon_tiger"]
            seat_impact = min(
                int(type_config["identified_hot_money_max_impact"]),
                int(round(hot_money_count * float(type_config["identified_hot_money_seat_impact"]))),
            )
            adjustments.append(_signal_adjustment(
                "龙虎榜席位类型",
                dragon,
                seat_impact,
                f"配置名录精确识别到 {int(hot_money_count)} 个游资席位，作为短线风格匹配证据。",
                "只有配置的可追溯精确席位名录可加分；普通券商营业部不推断为游资",
            ))
        rationale.append(dragon.observed)
    else:
        _append_signal_gap(risks, dragon, "龙虎榜")
    dragon_history = context.signal("dragon_tiger_history")
    if dragon_history.status == "admitted":
        config = signal_config["dragon_tiger_history"]
        impact = _continuous_impact(
            dragon_history.values["positive_observation_ratio"] - float(config["neutral_positive_ratio"]),
            float(config["positive_ratio_scale"]),
            int(config["aggressive_max_impact"]),
        )
        adjustments.append(_signal_adjustment(
            "龙虎榜游资席位历史后效",
            dragon_history,
            impact,
            "已识别游资席位的历史后效只用于质证当前短线风格是否有观察性支持。",
            "达到最小席位事件样本后才参与；正收益观察占比不是胜率，不代表因果",
        ))
    elif dragon_history.status == "rejected":
        _append_signal_gap(risks, dragon_history, "龙虎榜席位历史")
    tiered = context.signal("tiered_money_flow")
    if tiered.status == "admitted":
        config = signal_config["tiered_money_flow"]
        impact = _score_signal_impact(tiered.values["score"], float(config["neutral_score"]), float(config["score_span"]), int(config["aggressive_max_impact"]))
        adjustments.append(_signal_adjustment("资金流分档", tiered, impact, "大额与中小额订单的方向关系用于质证短线资金连续性。", "仅采信同日完整四档数据；不推断交易主体身份"))
    else:
        _append_signal_gap(risks, tiered, "资金流分档")
    intraday = context.signal("intraday")
    if intraday.status == "admitted":
        config = signal_config["intraday"]
        impact = _continuous_impact(intraday.values["order_book_imbalance"], float(config["imbalance_scale"]), int(config["aggressive_max_impact"]))
        adjustments.append(_signal_adjustment("盘口委托不平衡", intraday, impact, "盘口不平衡只用于验证当日承接，撤单风险保留为反证。", "买方不平衡加分、卖方不平衡扣分；必须与成交和 VWAP 交叉验证"))
    else:
        _append_signal_gap(risks, intraday, "盘口")
    if context.theme_stage in {"启动", "扩散"}:
        adjustments.append(_score_adjustment("题材阶段", 6, f"题材处于{context.theme_stage}，仍有扩散空间。"))
        rationale.append(f"题材处于{context.theme_stage}")
    if context.risk_score < 65:
        adjustments.append(_score_adjustment("风险底线", -25, f"风险扫描 {context.risk_score} 分，未达到激进交易底线。"))
        risks.append("风险扫描未达到激进交易底线")
    if context.invalid_penalty:
        adjustments.append(_score_adjustment("规则约束", -context.invalid_penalty, f"存在 {len(context.invalid_conditions)} 项否决/降级条件。"))
    rationale.append(f"资金面 {context.agent('资金流 Agent')} 分")
    return _finalize_faction("激进游资派", "情绪龙头/题材接力", base, adjustments, rationale, risks)


def _trend_capacity(context: _Context) -> FactionView:
    base = 42
    adjustments: list[dict[str, object]] = []
    rationale = [
        f"技术面 {context.agent('技术分析 Agent')} 分",
        f"资金面 {context.agent('资金流 Agent')} 分",
    ]
    risks: list[str] = []
    technical_adj = _scaled(context.agent("技术分析 Agent"), 55, 24)
    capital_adj = _scaled(context.agent("资金流 Agent"), 55, 18)
    risk_adj = _scaled(context.risk_score, 60, 12)
    adjustments.append(_score_adjustment("技术趋势", technical_adj, f"技术分析 Agent {context.agent('技术分析 Agent')} 分，趋势派最看重趋势确认。"))
    adjustments.append(_score_adjustment("资金承接", capital_adj, f"资金流 Agent {context.agent('资金流 Agent')} 分，决定趋势能否延续。"))
    adjustments.append(_score_adjustment("风险质量", risk_adj, f"风险扫描 {context.risk_score} 分，风险越低越能承载趋势仓位。"))
    signal_config = _committee_signal_config()
    _append_continuity_adjustment(
        context, adjustments, risks, "margin_balance_streak_days", "融资余额趋势",
        "trend_margin_max_impact", "融资余额连续变化方向用于验证杠杆资金是否持续配合趋势。",
    )
    _append_skill_score_adjustment(context, adjustments, risks, "turnover_continuity", "换手连续性", "trend_max_impact", "换手连续变化用于质证趋势是否获得持续参与。")
    _append_skill_score_adjustment(context, adjustments, risks, "a_share_characteristics", "涨停结构", "trend_max_impact", "市场封板结构只作为趋势风险偏好的低权重旁证。")
    margin = context.signal("margin_financing")
    if margin.status == "admitted":
        config = signal_config["margin_financing"]
        impact = _continuous_impact(margin.values["balance_activity_change_pct"], float(config["scale_pct"]), int(config["trend_max_impact"]))
        adjustments.append(_signal_adjustment("融资融券活动", margin, impact, "融资活动变化用于检验杠杆资金是否配合趋势。", "正向活动加分、负向活动扣分；不外推为多日余额趋势"))
        rationale.append(margin.observed)
    else:
        _append_signal_gap(risks, margin, "融资融券")
    tiered = context.signal("tiered_money_flow")
    if tiered.status == "admitted":
        config = signal_config["tiered_money_flow"]
        impact = _score_signal_impact(tiered.values["score"], float(config["neutral_score"]), float(config["score_span"]), int(config["trend_max_impact"]))
        adjustments.append(_signal_adjustment("资金流分档", tiered, impact, "分档资金方向用于验证趋势承接是否集中在大额订单。", "完整四档且绝对流量过门槛后才参与"))
    else:
        _append_signal_gap(risks, tiered, "资金流分档")
    intraday = context.signal("intraday")
    if intraday.status == "admitted":
        config = signal_config["intraday"]
        impact = _continuous_impact(intraday.values["order_book_imbalance"], float(config["imbalance_scale"]), int(config["trend_max_impact"]))
        adjustments.append(_signal_adjustment("盘口趋势确认", intraday, impact, "同日盘口承接用于质证趋势是否获得即时确认。", "委托不平衡必须与 VWAP、成交量同向才具有解释力"))
    else:
        _append_signal_gap(risks, intraday, "盘口")
    if context.theme_stage in {"启动", "扩散"}:
        adjustments.append(_score_adjustment("题材阶段", 9, f"题材处于{context.theme_stage}，对趋势延续有加成。"))
        rationale.append(f"题材处于{context.theme_stage}")
    if context.sentiment_stage in {"高潮", "退潮", "冰点"}:
        adjustments.append(_score_adjustment("情绪约束", -12, f"情绪处于{context.sentiment_stage}，趋势买点需要降低追价。"))
        risks.append(f"情绪处于{context.sentiment_stage}，趋势买点要降低追价")
    if context.invalid_penalty:
        adjustments.append(_score_adjustment("规则约束", -context.invalid_penalty, f"存在 {len(context.invalid_conditions)} 项否决/降级条件。"))
    return _finalize_faction("趋势容量派", "趋势确认/回踩低吸", base, adjustments, rationale, risks)


def _institutional_growth(context: _Context) -> FactionView:
    base = 40
    adjustments: list[dict[str, object]] = []
    rationale = [
        f"基本面 {context.agent('基本面 Agent')} 分",
        f"风险扫描 {context.risk_score} 分",
    ]
    risks: list[str] = []
    fundamental_adj = _scaled(context.agent("基本面 Agent"), 60, 26)
    risk_adj = _scaled(context.risk_score, 65, 18)
    technical_adj = _scaled(context.agent("技术分析 Agent"), 55, 10)
    adjustments.append(_score_adjustment("基本面质量", fundamental_adj, f"基本面 Agent {context.agent('基本面 Agent')} 分，成长派要求盈利和预期证据。"))
    adjustments.append(_score_adjustment("风险过滤", risk_adj, f"风险扫描 {context.risk_score} 分，机构成长不接受明显硬风险。"))
    adjustments.append(_score_adjustment("趋势配合", technical_adj, f"技术分析 Agent {context.agent('技术分析 Agent')} 分，用于判断资金是否认可成长逻辑。"))
    _append_industry_prosperity_adjustment(
        context,
        adjustments,
        risks,
        "institution_max_impact",
        "行业资金、估值和盈利增速差用于质证景气成长是否具有行业基础。",
    )
    signal_config = _committee_signal_config()
    _append_continuity_adjustment(
        context, adjustments, risks, "northbound_streak_days", "北向资金连续性",
        "institution_northbound_max_impact", "北向持股连续增减天数用于验证机构风格资金是否持续。",
    )
    _append_ah_premium_adjustment(context, adjustments, risks, "institution_max_impact")
    northbound = context.signal("northbound_holding")
    if northbound.status == "admitted":
        impact = _directional_impact(northbound.values["holding_change"], int(signal_config["northbound_holding"]["institution_direction_impact"]))
        adjustments.append(_signal_adjustment("北向持股变化", northbound, impact, "北向持股方向作为机构风格的观察性佐证，不替代基本面。", "持股增加加分、减少扣分；数量未标准化时仅使用方向"))
        rationale.append(northbound.observed)
    else:
        _append_signal_gap(risks, northbound, "北向持股")
    margin = context.signal("margin_financing")
    if margin.status == "admitted":
        config = signal_config["margin_financing"]
        impact = _continuous_impact(margin.values["balance_activity_change_pct"], float(config["scale_pct"]), int(config["institution_max_impact"]))
        adjustments.append(_signal_adjustment("融资融券活动", margin, impact, "融资活动用于观察增量风险偏好是否配合成长逻辑。", "正向活动加分、负向活动扣分；只代表同日活动"))
    else:
        _append_signal_gap(risks, margin, "融资融券")
    dragon = context.signal("dragon_tiger")
    if dragon.status == "admitted" and "institution_net_amount" in dragon.values:
        impact = _directional_impact(dragon.values["institution_net_amount"], int(signal_config["dragon_tiger"]["institution_direction_impact"]))
        adjustments.append(_signal_adjustment("龙虎榜机构席位", dragon, impact, "公开机构席位净额仅作为当日机构交易线索。", "机构席位净买入加分、净卖出扣分；单日披露不代表中期持仓"))
    elif dragon.status == "rejected":
        _append_signal_gap(risks, dragon, "龙虎榜机构席位")
    tiered = context.signal("tiered_money_flow")
    if tiered.status == "admitted":
        config = signal_config["tiered_money_flow"]
        impact = _score_signal_impact(tiered.values["score"], float(config["neutral_score"]), float(config["score_span"]), int(config["institution_max_impact"]))
        adjustments.append(_signal_adjustment("资金流分档", tiered, impact, "订单规模分布用于质证资金承接，不据此认定机构身份。", "完整四档数据才参与，影响低于基本面和风险过滤"))
    else:
        _append_signal_gap(risks, tiered, "资金流分档")
    if context.theme_stage == "高潮":
        adjustments.append(_score_adjustment("题材拥挤", -8, "题材高潮会放大估值兑现风险。"))
        risks.append("题材高潮会放大估值兑现风险")
    if context.agent("基本面 Agent") < 65:
        risks.append("盈利质量或预期证据不足")
    if context.invalid_penalty:
        penalty = min(18, context.invalid_penalty)
        adjustments.append(_score_adjustment("规则约束", -penalty, f"存在 {len(context.invalid_conditions)} 项否决/降级条件，成长派部分降权。"))
    return _finalize_faction("机构成长派", "景气成长/预期修正", base, adjustments, rationale, risks)


def _value_dividend(context: _Context) -> FactionView:
    base = 42
    adjustments: list[dict[str, object]] = []
    rationale = [
        f"基本面 {context.agent('基本面 Agent')} 分",
        f"风控质量 {context.risk_score} 分",
    ]
    risks: list[str] = []
    fundamental_adj = _scaled(context.agent("基本面 Agent"), 62, 24)
    risk_adj = _scaled(context.risk_score, 70, 20)
    adjustments.append(_score_adjustment("基本面安全垫", fundamental_adj, f"基本面 Agent {context.agent('基本面 Agent')} 分，价值派要求利润和现金流能支撑估值。"))
    adjustments.append(_score_adjustment("风控质量", risk_adj, f"风险扫描 {context.risk_score} 分，风险越低越符合价值持有。"))
    _append_industry_prosperity_adjustment(
        context,
        adjustments,
        risks,
        "value_max_impact",
        "行业估值分位和盈利增速差用于区分安全边际与价值陷阱。",
    )
    _append_ah_premium_adjustment(context, adjustments, risks, "value_max_impact")
    northbound = context.signal("northbound_holding")
    if northbound.status == "admitted":
        config = _committee_signal_config()["northbound_holding"]
        impact = _directional_impact(northbound.values["holding_change"], int(config["value_direction_impact"]))
        adjustments.append(_signal_adjustment("北向持股变化", northbound, impact, "北向持股方向只作为价值风格关注度的次级证据。", "方向性小权重；不能覆盖估值、现金流和公司治理证据"))
        rationale.append(northbound.observed)
    else:
        _append_signal_gap(risks, northbound, "北向持股")
    if context.agent("技术分析 Agent") < 45:
        adjustments.append(_score_adjustment("趋势陷阱", -10, f"技术分析 Agent {context.agent('技术分析 Agent')} 分，趋势过弱需防价值陷阱。"))
        risks.append("趋势过弱，需防范价值陷阱")
    if context.agent("题材热点 Agent") >= 60:
        adjustments.append(_score_adjustment("市场关注", 5, f"题材热点 Agent {context.agent('题材热点 Agent')} 分，价值/红利线有一定关注。"))
        rationale.append("价值/红利主题有一定市场关注")
    if context.invalid_penalty:
        penalty = min(18, context.invalid_penalty)
        adjustments.append(_score_adjustment("规则约束", -penalty, f"存在 {len(context.invalid_conditions)} 项否决/降级条件，价值派部分降权。"))
    return _finalize_faction("价值红利派", "现金流/估值约束", base, adjustments, rationale, risks)


def _policy_cycle(context: _Context) -> FactionView:
    base = 39
    adjustments: list[dict[str, object]] = []
    rationale = [
        f"题材热点 {context.agent('题材热点 Agent')} 分",
        f"市场温度 {context.market_temperature} 分",
    ]
    risks: list[str] = []
    theme_adj = _scaled(context.agent("题材热点 Agent"), 55, 24)
    market_adj = _scaled(context.market_temperature, 55, 14)
    capital_adj = _scaled(context.agent("资金流 Agent"), 50, 10)
    adjustments.append(_score_adjustment("政策/题材强度", theme_adj, f"题材热点 Agent {context.agent('题材热点 Agent')} 分，政策派看主线共识。"))
    adjustments.append(_score_adjustment("市场温度", market_adj, f"市场温度 {context.market_temperature} 分，决定政策线能否扩散。"))
    adjustments.append(_score_adjustment("资金扩散", capital_adj, f"资金流 Agent {context.agent('资金流 Agent')} 分，用于验证政策线是否有真实资金承接。"))
    _append_industry_prosperity_adjustment(
        context,
        adjustments,
        risks,
        "policy_max_impact",
        "产业链节点资金传导用于质证政策主题是否扩散到真实行业环节。",
    )
    if context.sentiment_stage == "退潮":
        adjustments.append(_score_adjustment("情绪退潮", -12, "退潮期政策线也容易高开低走。"))
        risks.append("退潮期政策线也容易高开低走")
    if context.risk_score < 60:
        adjustments.append(_score_adjustment("个股风险", -12, f"风险扫描 {context.risk_score} 分，个股风险会削弱政策贝塔。"))
        risks.append("个股风险会削弱政策贝塔")
    if context.invalid_penalty:
        penalty = min(22, context.invalid_penalty)
        adjustments.append(_score_adjustment("规则约束", -penalty, f"存在 {len(context.invalid_conditions)} 项否决/降级条件，政策派降权。"))
    return _finalize_faction("政策周期派", "产业政策/板块轮动", base, adjustments, rationale, risks)


def _reversal_low_absorption(context: _Context) -> FactionView:
    base = 36
    adjustments: list[dict[str, object]] = []
    rationale: list[str] = []
    risks: list[str] = []
    if context.sentiment_stage in {"冰点", "退潮"}:
        adjustments.append(_score_adjustment("情绪位置", 18, f"情绪处于{context.sentiment_stage}，具备修复观察价值。"))
        rationale.append(f"情绪处于{context.sentiment_stage}，具备反转观察价值")
    elif context.sentiment_stage == "启动":
        adjustments.append(_score_adjustment("情绪位置", 8, "情绪刚启动，可观察分歧后的低吸确认。"))
        rationale.append("情绪刚启动，可观察低吸确认")
    else:
        adjustments.append(_score_adjustment("情绪位置", -8, f"情绪处于{context.sentiment_stage}，低吸性价比不突出。"))
        risks.append(f"情绪处于{context.sentiment_stage}，低吸性价比不突出")
    technical = context.agent("技术分析 Agent")
    if 45 <= technical <= 68:
        adjustments.append(_score_adjustment("技术位置", 16, f"技术分析 Agent {technical} 分，未过热，适合等待确认。"))
        rationale.append("技术未过热，适合等待确认")
    elif technical > 75:
        adjustments.append(_score_adjustment("技术过热", -8, f"技术分析 Agent {technical} 分，已不属于低吸反转场景。"))
        risks.append("技术过热，不属于低吸反转场景")
    else:
        adjustments.append(_score_adjustment("趋势破坏", -10, f"技术分析 Agent {technical} 分，趋势破坏过深，容易抄底过早。"))
        risks.append("趋势破坏过深，容易抄底过早")
    if "派发" in context.main_force_stage:
        adjustments.append(_score_adjustment("主力行为", -16, f"主力行为偏{context.main_force_stage}，低吸容易接派发盘。"))
        risks.append("主力行为偏派发")
    risk_adj = _scaled(context.risk_score, 65, 12)
    adjustments.append(_score_adjustment("风险质量", risk_adj, f"风险扫描 {context.risk_score} 分，低吸必须先排除硬风险。"))
    intraday = context.signal("intraday")
    if intraday.status == "admitted":
        config = _committee_signal_config()["intraday"]
        impact = _continuous_impact(intraday.values["order_book_imbalance"], float(config["imbalance_scale"]), int(config["reversal_max_impact"]))
        adjustments.append(_signal_adjustment("盘口承接确认", intraday, impact, "低吸反转需要买方承接确认，卖方不平衡构成反证。", "买方不平衡加分、卖方不平衡扣分；委托可撤销"))
        if impact > 0:
            rationale.append(intraday.observed)
        elif impact < 0:
            risks.append("盘口卖方压力未支持反转确认")
    else:
        _append_signal_gap(risks, intraday, "盘口")
    if context.invalid_penalty:
        penalty = min(22, context.invalid_penalty)
        adjustments.append(_score_adjustment("规则约束", -penalty, f"存在 {len(context.invalid_conditions)} 项否决/降级条件，低吸派降权。"))
    return _finalize_faction("低吸反转派", "冰点修复/恐慌低吸", base, adjustments, rationale, risks)


def _defensive_risk_control(context: _Context) -> FactionView:
    base = 48
    adjustments: list[dict[str, object]] = []
    rationale: list[str] = []
    risks: list[str] = []
    if context.risk_score < 60:
        adjustments.append(_score_adjustment("风险扫描", 24, f"风险扫描仅 {context.risk_score} 分，防守优先级上升。"))
        rationale.append(f"风险扫描仅 {context.risk_score} 分，防守优先")
    else:
        risk_adj = max(0, 12 - (context.risk_score - 60) // 3)
        adjustments.append(_score_adjustment("风险扫描", risk_adj, f"风险扫描 {context.risk_score} 分，仍保留一定风控权重。"))
        rationale.append(f"风险扫描 {context.risk_score} 分")
    if context.sentiment_stage in {"冰点", "退潮"}:
        adjustments.append(_score_adjustment("情绪防守", 18, f"情绪处于{context.sentiment_stage}，防守权重提高。"))
        rationale.append(f"情绪处于{context.sentiment_stage}")
    elif context.sentiment_stage == "高潮":
        adjustments.append(_score_adjustment("情绪兑现", 10, "情绪高潮，防守派关注兑现压力。"))
        rationale.append("情绪高潮，防守派关注兑现压力")
    else:
        adjustments.append(_score_adjustment("机会成本", -6, "市场仍有进攻窗口，过度防守有机会成本。"))
        risks.append("市场仍有进攻窗口，过度防守可能有机会成本")
    if context.invalid_conditions:
        adjustments.append(_score_adjustment("规则约束", 18, f"存在 {len(context.invalid_conditions)} 项否决/降级条件，防守派加权。"))
        rationale.append("存在规则否决/降级条件")
    market_adj = -_scaled(context.market_temperature, 70, 10)
    adjustments.append(_score_adjustment("市场温度反向项", market_adj, f"市场温度 {context.market_temperature} 分；温度越高，纯防守分越低。"))
    return _finalize_faction("防守风控派", "仓位控制/等待确认", base, adjustments, rationale, risks)


def _score_adjustment(
    item: str,
    impact: int,
    reason: str,
    observed: str | None = None,
    threshold: str | None = None,
    source: str | None = None,
    source_ids: list[str] | None = None,
    as_of: str | None = None,
    evidence_status: str = "admitted",
) -> dict[str, object]:
    return {
        "item": item,
        "impact": impact,
        "direction": "加分" if impact > 0 else "扣分" if impact < 0 else "中性",
        "observed": observed or _infer_observed(reason),
        "threshold": threshold or _threshold_for_item(item),
        "source": source or _source_for_item(item),
        "source_ids": list(source_ids or []),
        "as_of": as_of,
        "evidence_status": evidence_status,
        "reason": reason,
    }


def _finalize_faction(
    name: str,
    route: str,
    base_score: int,
    score_adjustments: list[dict[str, object]],
    rationale: list[str],
    risks: list[str],
) -> FactionView:
    raw_score = base_score + sum(int(item["impact"]) for item in score_adjustments)
    final_score = clamp_score(raw_score)
    net = raw_score - base_score
    explanation = f"基础分 {base_score}，净调整 {net:+d}，原始分 {raw_score}，限制到 0-100 后为 {final_score}。"
    return FactionView(name, route, final_score, rationale, risks, base_score, score_adjustments, explanation)


def _infer_observed(reason: str) -> str:
    score_match = re.search(r"((?:Agent|赚钱效应|风险扫描|市场温度)\s*\d+\s*分)", reason)
    if score_match:
        return score_match.group(1).replace("  ", " ")
    for stage in ["冰点", "启动", "发酵", "高潮", "退潮", "扩散"]:
        if f"{stage}期" in reason or f"刚{stage}" in reason or f"处于{stage}" in reason:
            return stage
    stage_match = re.search(r"(?:处于|偏)([^，。；]+)", reason)
    if stage_match:
        return stage_match.group(1)
    rule_match = re.search(r"存在\s*(\d+)\s*项", reason)
    if rule_match:
        return f"{rule_match.group(1)} 项规则约束"
    if "题材高潮" in reason:
        return "题材高潮"
    if "市场仍有进攻窗口" in reason:
        return "仍有进攻窗口"
    return "见证据链"


def _threshold_for_item(item: str) -> str:
    if "情绪" in item:
        return "启动/发酵加分；高潮/退潮/冰点按流派降权"
    if "赚钱" in item:
        return "60 分以上支持短线进攻"
    if "资金" in item or "承接" in item or "扩散" in item:
        return "55-65 分以上才说明资金连续"
    if "题材" in item or "政策" in item or "市场关注" in item:
        return "启动/扩散阶段优于高潮/退潮"
    if "风险" in item or "风控" in item or "个股风险" in item:
        return "65 分以上适合进攻；60 分以下优先降权"
    if "规则" in item:
        return "T+1/ST/停牌/涨跌停等硬约束优先"
    if "技术" in item or "趋势" in item:
        return "55 分以上趋势有效；45 分以下视为破坏"
    if "基本面" in item:
        return "60 分以上说明盈利/现金流证据尚可"
    if "市场温度" in item:
        return "55 分以上支持扩散；70 分以上降低纯防守"
    if "主力" in item:
        return "吸筹/拉升优于派发"
    if "机会成本" in item:
        return "市场仍有进攻窗口时防守派扣分"
    return "按当前证据强弱加减分"


def _source_for_item(item: str) -> str:
    if "情绪" in item:
        return "情绪周期识别 Skill"
    if "赚钱" in item:
        return "赚钱效应分析 Skill"
    if "资金" in item or "承接" in item or "扩散" in item:
        return "资金流 Agent"
    if "题材阶段" in item or "题材拥挤" in item:
        return "热点生命周期分析 Skill"
    if "题材" in item or "政策" in item or "市场关注" in item:
        return "题材热点 Agent"
    if "风险" in item or "风控" in item or "个股风险" in item:
        return "A股风险扫描器"
    if "规则" in item:
        return "A股交易规则"
    if "技术" in item or "趋势" in item:
        return "技术分析 Agent"
    if "基本面" in item:
        return "基本面 Agent"
    if "市场温度" in item:
        return "A股市场温度计"
    if "主力" in item:
        return "主力资金行为识别 Skill"
    if "机会成本" in item:
        return "市场温度/情绪周期组合"
    return "投资流派委员会规则"


def _scaled(value: int, threshold: int, weight: int) -> int:
    return int(round(max(-weight, min(weight, (value - threshold) / 25 * weight))))


def _rank_line(factions: list[FactionView]) -> str:
    return "；".join(f"{item.name}{item.score}" for item in factions[:4])


def _strategy_for_winner(winner: FactionView) -> str:
    mapping = {
        "激进游资派": "只在情绪未退潮、题材未高潮且资金连续验证时研究核心标的；不把涨停本身当入场理由。",
        "趋势容量派": "优先等待回踩不破、成交额确认和资金持续性，避免在加速段追价。",
        "机构成长派": "把财报质量、预期修正和趋势确认拆开复核，缺少业绩证据时降低置信度。",
        "价值红利派": "以现金流、估值和股东回报为主线，防范价值陷阱和机会成本。",
        "政策周期派": "跟踪政策级别、产业链受益顺序和资金扩散，避免在一致性过高时追后排。",
        "低吸反转派": "只在恐慌释放后等待修复确认，分批观察，不提前抄底。",
        "防守风控派": "降低进攻优先级，先保留研究记录，等待市场温度、资金或规则约束改善。",
    }
    return mapping.get(winner.name, "保留观察，等待更高质量证据。")


def _faction_detail(faction: FactionView, winner: bool, topic: str) -> dict[str, object]:
    return {
        "name": faction.name,
        "route": faction.route,
        "discussion_topic": topic,
        "score": faction.score,
        "base_score": faction.base_score,
        "score_basis": _score_basis(faction),
        "score_explanation": faction.score_explanation,
        "score_adjustments": faction.score_adjustments,
        "playbook_checks": _playbook_checks_for_faction(faction),
        "stance": _stance_for_score(faction.score),
        "rationale": faction.rationale,
        "risks": faction.risks,
        "recommendation": _recommendation_for_faction(faction),
        "question_response": _question_response(faction, topic),
        "cross_examination": _faction_cross_examination(faction),
        "winner": winner,
    }


def _faction_cross_examination(faction: FactionView) -> dict[str, list[str]]:
    supports = _adjustment_lines(faction, positive=True)
    challenges = _adjustment_lines(faction, positive=False)
    return {
        "claim": supports[:2] or ["未形成足够强的支持证据。"],
        "challenge": challenges[:2] or faction.risks[:2] or ["尚无明确硬性反证，仍需补充实时证据。"],
        "invalidation": _playbook_template(faction.name)["invalid_if"],
    }


def _court_cross_examination(factions: list[FactionView]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for faction in factions:
        cross = _faction_cross_examination(faction)
        rows.append(
            {
                "route": faction.name,
                "claim": cross["claim"],
                "challenge": cross["challenge"],
                "invalidation": cross["invalidation"],
            }
        )
    return rows


def _risk_challenge(context: _Context, findings: list[AgentFinding]) -> dict[str, object]:
    evidence_quality = next((item for item in context.skills.values() if item.category == "quality"), None)
    missing_boundaries = [item.agent for item in findings if not item.invalidation_conditions]
    return {
        "role": "risk_challenge",
        "rule_constraints": list(context.invalid_conditions),
        "evidence_quality": evidence_quality.score if evidence_quality else None,
        "evidence_risks": evidence_quality.risks if evidence_quality else [],
        "missing_invalidation_boundaries": missing_boundaries,
        "verdict": (
            "存在规则约束或证据边界缺失，法官只能给出观察性路线结论。"
            if context.invalid_conditions or missing_boundaries or (evidence_quality and evidence_quality.score < 70)
            else "未发现证据链硬缺口，但路线结论仍须随新公告、资金和市场状态复核。"
        ),
    }


def _score_basis(faction: FactionView) -> dict[str, object]:
    positive = sum(max(0, int(item["impact"])) for item in faction.score_adjustments)
    negative = sum(min(0, int(item["impact"])) for item in faction.score_adjustments)
    raw_score = faction.base_score + positive + negative
    strongest = sorted(faction.score_adjustments, key=lambda item: abs(int(item["impact"])), reverse=True)[:3]
    return {
        "base_score": faction.base_score,
        "positive_impact": positive,
        "negative_impact": negative,
        "raw_score": raw_score,
        "final_score": faction.score,
        "strongest_drivers": [
            f"{item['item']} {int(item['impact']):+d}：{item['reason']}" for item in strongest
        ],
    }


def _playbook_checks_for_faction(faction: FactionView) -> dict[str, object]:
    supports = _adjustment_lines(faction, positive=True)
    blocks = _adjustment_lines(faction, positive=False)
    template = _playbook_template(faction.name)
    return {
        "core_logic": template["core_logic"],
        "supports": supports or ["当前没有足够强的正向证据，只能保持观察。"],
        "blocks": blocks or ["当前没有显著硬性拖累，但仍需复核实时数据和公告。"],
        "must_confirm": template["must_confirm"],
        "invalid_if": template["invalid_if"],
    }


def _adjustment_lines(faction: FactionView, positive: bool) -> list[str]:
    rows: list[str] = []
    for item in faction.score_adjustments:
        impact = int(item["impact"])
        if (positive and impact <= 0) or (not positive and impact >= 0):
            continue
        rows.append(
            f"{item['item']} {impact:+d}：当前 {item['observed']}，阈值 {item['threshold']}，来源 {item['source']}。{item['reason']}"
        )
    return rows[:5]


def _playbook_template(faction_name: str) -> dict[str, list[str] | str]:
    templates: dict[str, dict[str, list[str] | str]] = {
        "激进游资派": {
            "core_logic": "验证情绪、题材、涨速和资金接力是否足以支持短线进攻。",
            "must_confirm": [
                "市场情绪不能进入退潮，赚钱效应不能明显走弱。",
                "所属题材处于启动/扩散，核心龙头不能炸板或补跌。",
                "资金流要连续，急拉后不能快速回落并放量流出。",
                "A股风险扫描至少不能触发硬性否决项。",
            ],
            "invalid_if": [
                "炸板率上升、连板高度下降或核心股转弱。",
                "主力净流入转负，且分时急拉后承接消失。",
                "题材进入高潮末端，后排补涨替代核心龙头。",
                "出现 ST、停牌、重大减持、监管问询等硬风险。",
            ],
        },
        "趋势容量派": {
            "core_logic": "验证价格趋势、成交量和资金承接是否能支持回踩低吸或放量突破。",
            "must_confirm": [
                "价格站稳关键均线或回踩支撑不破。",
                "成交额不能萎缩到失去流动性，突破需放量确认。",
                "资金流不能连续背离价格上涨。",
                "若短期急涨，需要等待缩量回踩或二次确认。",
            ],
            "invalid_if": [
                "跌破核心支撑且无法快速收回。",
                "上涨放量但资金持续流出，疑似诱多。",
                "市场情绪退潮导致趋势票集体补跌。",
                "规则/公告风险改变趋势假设。",
            ],
        },
        "机构成长派": {
            "core_logic": "验证盈利质量、预期修正和行业景气是否足以支持成长定价。",
            "must_confirm": [
                "营收/利润/ROE 至少有一项形成持续改善证据。",
                "公告或一致预期不能出现下修。",
                "行业景气与公司竞争位置要能对应到利润。",
                "趋势配合只能作为资金认可证据，不能替代基本面。",
            ],
            "invalid_if": [
                "业绩预告、现金流或毛利率恶化。",
                "题材炒作脱离业绩兑现，估值快速透支。",
                "机构资金撤退或调研热度明显下降。",
                "重大减持、商誉、质押、监管风险升温。",
            ],
        },
        "价值红利派": {
            "core_logic": "验证现金流、估值和股东回报是否提供足够安全边际。",
            "must_confirm": [
                "现金流质量和资产负债表不能恶化。",
                "估值需要相对历史/行业有安全垫。",
                "分红、回购或稳定盈利能支撑持有逻辑。",
                "价格下跌必须不是基本面永久损伤。",
            ],
            "invalid_if": [
                "低估值来自利润下滑或行业衰退。",
                "趋势持续破位且没有基本面修复证据。",
                "现金流转弱、负债率抬升或分红能力下降。",
                "短线题材波动掩盖长期价值风险。",
            ],
        },
        "政策周期派": {
            "core_logic": "验证政策级别、产业链传导和板块资金扩散是否形成主线。",
            "must_confirm": [
                "政策不是单日新闻刺激，而是能持续落地到产业链。",
                "板块龙头和中军要有资金承接，不能只有后排乱涨。",
                "题材处于启动/扩散优于高潮末端。",
                "个股必须能对应政策受益环节，不能只蹭概念。",
            ],
            "invalid_if": [
                "政策预期兑现后资金撤退。",
                "板块只剩后排补涨，龙头或中军走弱。",
                "公司公告无法证明真实受益。",
                "市场温度下降导致政策线高开低走。",
            ],
        },
        "低吸反转派": {
            "core_logic": "验证恐慌是否释放充分，以及修复信号是否已经出现。",
            "must_confirm": [
                "情绪冰点/退潮后出现止跌修复，而不是下跌中继。",
                "价格靠近关键支撑，且缩量企稳或资金回流。",
                "主力行为不能是派发。",
                "硬风险必须先排除，否则低吸会变成接刀。",
            ],
            "invalid_if": [
                "跌破支撑后继续放量下行。",
                "资金流持续为负，修复没有承接。",
                "情绪退潮尚未结束，强势股继续补跌。",
                "基本面或公告出现实质恶化。",
            ],
        },
        "防守风控派": {
            "core_logic": "验证是否应该先控制仓位、等待证据改善，而不是寻找进攻理由。",
            "must_confirm": [
                "先列出硬风险和规则约束，再讨论机会。",
                "市场温度、情绪周期和资金流至少有一项改善后再解除防守。",
                "若用户问短线入手，必须先明确止损和失效条件。",
                "所有结论只能是研究辅助，不给确定性买卖承诺。",
            ],
            "invalid_if": [
                "风险扫描改善且资金/趋势同时转强。",
                "市场从退潮转入启动，赚钱效应恢复。",
                "规则约束解除，公告风险被证伪。",
                "继续防守的机会成本高于风险暴露。",
            ],
        },
    }
    return templates.get(
        faction_name,
        {
            "core_logic": "验证当前证据是否足以支持该流派路线。",
            "must_confirm": ["等待更完整的市场、资金、公告和风险证据。"],
            "invalid_if": ["证据链断裂或关键风险升温。"],
        },
    )


def _stance_for_score(score: int) -> str:
    if score >= 72:
        return "强支持"
    if score >= 62:
        return "谨慎支持"
    if score >= 50:
        return "中性观察"
    return "反对/降权"


def _reliability_label(score: int, gap: int) -> str:
    if score >= 72 and gap >= 8:
        return "较高"
    if score >= 62 and gap >= 4:
        return "中等偏高"
    if score >= 55:
        return "中等"
    return "偏低"


def _recommendation_for_faction(faction: FactionView) -> str:
    base = {
        "激进游资派": "只看情绪和题材核心强度；如果炸板率上升或资金不连续，放弃接力。",
        "趋势容量派": "等待趋势确认后的回踩低吸或放量突破，不在单日急涨后追价。",
        "机构成长派": "优先核验业绩增速、预期修正和机构行为，缺少基本面证据时降低仓位假设。",
        "价值红利派": "只在估值、现金流和分红逻辑有安全垫时关注，防范价值陷阱。",
        "政策周期派": "跟踪政策级别、产业链传导和资金扩散顺序，只做主线受益方向。",
        "低吸反转派": "等待恐慌释放后的修复确认，分批观察，不提前抄底。",
        "防守风控派": "降低进攻优先级，保留观察记录，等待风险或资金信号改善。",
    }.get(faction.name, "保留观察，等待更高质量证据。")
    if faction.score < 50:
        return f"当前降权：{base}"
    return base


def _normalize_topic(user_question: str | None) -> str:
    topic = (user_question or "").strip()
    return topic if topic else "围绕当前个股是否值得继续研究与如何制定观察策略"


def _question_focus(topic: str) -> str:
    if any(keyword in topic for keyword in ["短线", "早盘", "打板", "追高", "急拉", "极速", "入手", "买入"]):
        return "shortline"
    if any(keyword in topic for keyword in ["低吸", "回踩", "等回调", "回落"]):
        return "pullback"
    if any(keyword in topic for keyword in ["风险", "亏", "止损", "能不能", "是否可以", "安全吗"]):
        return "risk"
    if any(keyword in topic for keyword in ["中线", "长期", "价值", "持有", "基本面"]):
        return "fundamental"
    return "general"


def _question_response(faction: FactionView, topic: str) -> str:
    focus = _question_focus(topic)
    if faction.score < 50:
        prefix = "本派对这个问题暂不支持直接执行"
    elif faction.score < 62:
        prefix = "本派认为这个问题只能继续观察"
    else:
        prefix = "本派认为这个问题具备讨论价值"

    if focus == "shortline":
        advice = {
            "激进游资派": "短线只看情绪、涨速和题材核心，资金不连续或炸板率抬升时不参与。",
            "趋势容量派": "短线入手也要等回踩不破或放量确认，单日急拉不是入场理由。",
            "机构成长派": "短线不是本派优势，除非业绩或预期出现明确催化，否则不因盘口波动入手。",
            "价值红利派": "不建议用短线问题驱动价值派决策，先确认估值和现金流安全垫。",
            "政策周期派": "短线可以围绕政策主线看资金扩散，但后排和一致性过高要降权。",
            "低吸反转派": "只接受恐慌释放后的修复确认，不追急拉。",
            "防守风控派": "若问题是短线入手，本派优先要求先明确止损位和失效条件。",
        }
    elif focus == "pullback":
        advice = {
            "激进游资派": "低吸不是本派主场，除非核心龙头分歧后快速修复。",
            "趋势容量派": "重点观察回踩 MA20/关键支撑不破、缩量企稳和资金回流。",
            "机构成长派": "低吸前要确认业绩预期没有变坏，否则可能是价值陷阱。",
            "价值红利派": "回调只有在估值和现金流安全垫明确时才有意义。",
            "政策周期派": "低吸要看政策线是否仍在扩散，不能只看价格便宜。",
            "低吸反转派": "等待情绪冰点或恐慌盘释放后再看修复，不提前抄底。",
            "防守风控派": "回踩若伴随资金大幅流出，仍按风险处理。",
        }
    elif focus == "risk":
        advice = {
            "激进游资派": "风险问题下本派权重降低，除非市场情绪极强且龙头确认。",
            "趋势容量派": "风险可控的前提是趋势不破、量能不失真、资金不持续流出。",
            "机构成长派": "风险判断优先看盈利质量、预期修正和行业景气是否恶化。",
            "价值红利派": "风险判断优先看现金流、估值和股东回报能否提供安全边际。",
            "政策周期派": "风险来自政策兑现低于预期或资金只做短炒不做产业链扩散。",
            "低吸反转派": "风险点在于过早抄底，必须等止跌和修复信号。",
            "防守风控派": "先列出否决条件，再决定是否继续研究，不能先有结论再找理由。",
        }
    elif focus == "fundamental":
        advice = {
            "激进游资派": "基本面问题不是本派核心，本派只作为情绪和资金辅助判断。",
            "趋势容量派": "中线持有需要趋势和资金共同确认，不能只靠基本面叙事。",
            "机构成长派": "重点看利润增速、ROE、预期修正和行业景气，缺一项都要降置信度。",
            "价值红利派": "重点看现金流、估值、分红和资产负债表，价格波动反而是次级变量。",
            "政策周期派": "中线要看政策是否能转化为订单、利润和行业景气。",
            "低吸反转派": "基本面稳定时才考虑低吸，否则下跌可能是基本面重估。",
            "防守风控派": "中线更要先排除财务、公告和流动性硬风险。",
        }
    else:
        advice = {
            "激进游资派": "从情绪和题材角度看，只在核心标的、资金连续、情绪未退潮时考虑。",
            "趋势容量派": "从趋势角度看，等待趋势确认和回踩/突破条件，不急于给交易结论。",
            "机构成长派": "从成长角度看，需补充业绩和预期证据后再提高置信度。",
            "价值红利派": "从价值角度看，需确认估值、现金流和安全边际。",
            "政策周期派": "从政策角度看，关注是否处在主线扩散早中期。",
            "低吸反转派": "从反转角度看，等待恐慌释放和修复确认。",
            "防守风控派": "从风控角度看，先明确失效条件和不可参与条件。",
        }
    return f"围绕「{topic}」，{prefix}：{advice.get(faction.name, '保留观察，等待更多证据。')}"


def _judge_action_for_question(winner: FactionView, topic: str, base_strategy: str) -> str:
    focus = _question_focus(topic)
    if focus == "shortline":
        return f"针对你的短线问题：{base_strategy} 同时必须看资金连续性、急拉是否回落、止损位是否清晰。"
    if focus == "pullback":
        return f"针对你的低吸/回踩问题：{base_strategy} 重点等待支撑不破、缩量企稳和资金回流。"
    if focus == "risk":
        return f"针对你的风险问题：{base_strategy} 先解释风险扫描器扣分项，再讨论任何参与条件。"
    if focus == "fundamental":
        return f"针对你的中长期/基本面问题：{base_strategy} 需要补充真实财报、公告和预期修正证据。"
    return f"针对你的问题：{base_strategy}"
