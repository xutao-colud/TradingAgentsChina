from __future__ import annotations

import re

from dataclasses import dataclass

from app.schemas.report import AgentFinding, SkillInsight
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


def assess_investment_faction_committee(
    findings: list[AgentFinding],
    skill_insights: list[SkillInsight],
    invalid_conditions: list[str],
    user_question: str | None = None,
) -> SkillInsight:
    """Compare A-share investment schools under the same evidence set.

    The score is a deterministic "win-rate proxy" for research routing, not a
    promised or backtested return. It helps the product decide which playbook is
    currently the most persuasive for the user's next layer of analysis.
    """

    agent_scores = {item.agent: item.score for item in findings}
    skills = {item.skill: item for item in skill_insights}
    topic = _normalize_topic(user_question)
    context = _Context(agent_scores=agent_scores, skills=skills, invalid_conditions=invalid_conditions, user_question=topic)
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
        conclusion = f"当前最有说服力的是{winner.name}，胜率代理明显领先。"
    elif winner.score >= 62:
        stage = f"{winner.name}/分歧"
        conclusion = f"{winner.name}暂时领先，但与{runner_up.name}分歧不大。"
    else:
        stage = "无明显优势"
        conclusion = "各流派证据都不充分，当前不宜强行套用单一战法。"

    evidence = [
        f"研讨问题：{topic}",
        f"胜率代理排名：{_rank_line(factions)}",
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
            "score_warning": "分数只代表当前证据对流派路线的适配度，不代表收益概率或买卖承诺。",
            "verdict": conclusion,
            "reason": winner.rationale[:3],
            "action": _judge_action_for_question(winner, topic, strategy),
        },
        "factions": [_faction_detail(item, item.name == winner.name, topic) for item in factions],
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
    skills: dict[str, SkillInsight]
    invalid_conditions: list[str]
    user_question: str

    def agent(self, name: str, default: int = 50) -> int:
        return self.agent_scores.get(name, default)

    def skill(self, name: str) -> SkillInsight | None:
        return self.skills.get(name)

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
        risks.append(f"情绪处于{context.sentiment_stage}，接力胜率下降")
    money_making_adj = _scaled(context.money_making_score, 60, 12)
    capital_adj = _scaled(context.agent("资金流 Agent"), 65, 10)
    theme_adj = _scaled(context.agent("题材热点 Agent"), 60, 6)
    adjustments.append(_score_adjustment("赚钱效应", money_making_adj, f"赚钱效应 {context.money_making_score} 分，决定短线资金是否愿意继续进攻。"))
    adjustments.append(_score_adjustment("资金流", capital_adj, f"资金流 Agent {context.agent('资金流 Agent')} 分，游资派要求资金连续。"))
    adjustments.append(_score_adjustment("题材强度", theme_adj, f"题材热点 Agent {context.agent('题材热点 Agent')} 分，题材越强接力越有共识。"))
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
) -> dict[str, object]:
    return {
        "item": item,
        "impact": impact,
        "direction": "加分" if impact > 0 else "扣分" if impact < 0 else "中性",
        "observed": observed or _infer_observed(reason),
        "threshold": threshold or _threshold_for_item(item),
        "source": source or _source_for_item(item),
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
        "winner": winner,
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
