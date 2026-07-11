from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Playbook:
    id: str
    name: str
    group: str
    horizon: str
    summary: str
    required_signals: list[str]
    disqualifiers: list[str]
    optimization_focus: str
    backtest_hypothesis: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


PLAYBOOKS: dict[str, Playbook] = {
    "hot_money_leader": Playbook(
        id="hot_money_leader",
        name="情绪龙头确认",
        group="公开游资风格原型",
        horizon="1-5 个交易日",
        summary="只研究情绪启动/发酵期中流动性充足、资金与题材共振的核心标的；不把连板或涨停本身当作买入理由。",
        required_signals=["情绪周期非退潮", "赚钱效应良好", "资金流连续验证", "题材仍在启动/扩散"],
        disqualifiers=["退潮或冰点", "炸板率显著上升", "流动性不足", "监管/公告重大风险"],
        optimization_focus="先判市场和题材，再判个股；若只满足单日强势而无连续资金证据，记录为观察而非追高。",
        backtest_hypothesis="在情绪启动/发酵且市场赚钱效应良好时，资金与题材共振的高流动性核心股，其后续收益优于同题材非核心股。",
    ),
    "trend_core": Playbook(
        id="trend_core",
        name="趋势容量核心",
        group="公开游资/机构共振原型",
        horizon="5-20 个交易日",
        summary="研究趋势、成交额、主力资金与题材扩散同步的容量核心，强调回踩确认而不是加速段追价。",
        required_signals=["技术趋势偏多", "主力资金非明显流出", "题材处于启动/扩散", "风险扫描达标"],
        disqualifiers=["趋势跌破关键均线", "资金与价格背离", "题材进入高潮后负反馈", "高位公告风险"],
        optimization_focus="把入场条件从“上涨”改为“回踩不破 + 成交额确认”；复盘每次是否在加速段追价。",
        backtest_hypothesis="趋势偏多、资金温和流入且题材处于启动/扩散的个股，在回踩确认后介入的风险调整收益优于突破当日追价。",
    ),
    "institutional_growth": Playbook(
        id="institutional_growth",
        name="机构景气成长",
        group="大型机构公开研究原型",
        horizon="1-3 个月",
        summary="以盈利质量、预期修正、行业景气和趋势确认构建研究优先级，价格波动不能替代业绩验证。",
        required_signals=["基本面质量较强", "业绩/预期不恶化", "风险扫描达标", "技术趋势未破坏"],
        disqualifiers=["盈利增速显著下滑", "高估值且无预期支撑", "重大监管/减持风险", "趋势破坏"],
        optimization_focus="把每次结论拆为业绩、估值、趋势三项；缺少财报或预期数据时自动降低置信度。",
        backtest_hypothesis="盈利增速、ROE、现金流质量与预期修正同时改善的股票，在排除高风险公告后具有更好的中期风险调整表现。",
    ),
    "institutional_value_dividend": Playbook(
        id="institutional_value_dividend",
        name="机构价值红利",
        group="大型机构公开研究原型",
        horizon="1-6 个月",
        summary="以现金流、资产负债表、估值约束和股东回报为研究主线，避免把短线题材热度误当长期价值。",
        required_signals=["现金流与负债质量达标", "估值不过度透支", "高股息/价值主题有证据", "风险扫描达标"],
        disqualifiers=["现金流恶化", "高负债或商誉风险", "估值显著透支", "仅靠短线概念驱动"],
        optimization_focus="为每个候选设置估值与基本面双重否决线；定期复核股东回报是否由真实现金流支撑。",
        backtest_hypothesis="现金流质量较高、杠杆受控且估值不过度扩张的价值/红利股票，在较长持有期表现更稳定。",
    ),
}

DEFAULT_PLAYBOOK_ID = "trend_core"


def list_playbooks() -> list[Playbook]:
    return list(PLAYBOOKS.values())


def get_playbook(playbook_id: str) -> Playbook:
    try:
        return PLAYBOOKS[playbook_id]
    except KeyError as exc:
        raise ValueError(f"Unknown playbook: {playbook_id}") from exc
