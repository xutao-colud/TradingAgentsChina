from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.config.runtime import load_runtime_settings
from app.schemas.report import SkillInsight, StockProfile


@dataclass(frozen=True)
class ConvertibleBondSnapshot:
    symbol: str
    name: str
    as_of: str
    bond_price: float | None
    underlying_price: float | None
    conversion_price: float | None
    remaining_balance: float | None
    amount: float | None
    maturity_date: str | None = None
    source_ids: list[str] = field(default_factory=list)


def assess_listing_stage(profile: StockProfile, analysis_date: str) -> SkillInsight:
    config = load_runtime_settings().get("domain_knowledge", "special_instruments")
    if not profile.list_date:
        return SkillInsight(
            "新股/次新股规则", "special_instrument", "数据不足", 0,
            "缺少上市日期，不能判断新股或次新股阶段。", "补齐交易所或Tushare上市日期后再评估。",
            evidence=[f"证券：{profile.symbol}"], risks=["不得用股票代码或名称猜测上市阶段。"],
        )
    listed = date.fromisoformat(profile.list_date)
    current = date.fromisoformat(analysis_date)
    listed_days = (current - listed).days
    if listed_days < 0:
        stage = "尚未上市"
        score = 0
    elif listed_days <= config["new_stock_days"]:
        stage = "新股阶段"
        score = config["new_stock_score"]
    elif listed_days <= config["secondary_new_stock_days"]:
        stage = "次新股阶段"
        score = config["secondary_new_stock_score"]
    else:
        stage = "常规上市阶段"
        score = config["regular_stock_score"]
    risks = []
    if stage in {"新股阶段", "次新股阶段"}:
        risks.extend(["历史样本短，技术指标和回测统计不稳定。", "换手率、涨跌停规则、流通盘和限售安排需单独复核。"])
    return SkillInsight(
        "新股/次新股规则", "special_instrument", stage, score,
        f"截至分析日上市 {listed_days} 个自然日，处于{stage}。",
        "仅调整研究约束和数据置信度，不生成买卖指令。",
        evidence=[f"上市日期：{profile.list_date}", f"分析日期：{analysis_date}", f"上市自然日：{listed_days}"],
        risks=risks, details={"listed_days": listed_days},
    )


def assess_convertible_bond(snapshot: ConvertibleBondSnapshot) -> SkillInsight:
    config = load_runtime_settings().get("domain_knowledge", "special_instruments")
    parity = None
    premium = None
    if snapshot.underlying_price is not None and snapshot.conversion_price not in {None, 0}:
        parity = snapshot.underlying_price / snapshot.conversion_price * 100
    if snapshot.bond_price is not None and parity not in {None, 0}:
        premium = (snapshot.bond_price / parity - 1) * 100
    missing = []
    if premium is None:
        missing.append("缺少债价、正股价或转股价，无法计算转股溢价率。")
    if snapshot.remaining_balance is None:
        missing.append("缺少剩余规模，无法评价小规模波动风险。")
    if snapshot.amount is None:
        missing.append("缺少成交额，无法评价流动性。")
    if missing:
        return SkillInsight(
            "可转债研究", "special_instrument", "数据不足", 0,
            "可转债关键字段不完整，不能形成估值和流动性判断。", "补齐同一时点的债价、正股价、转股价、余额与成交额。",
            evidence=[f"数据时间：{snapshot.as_of}"], risks=missing, details={"source_ids": snapshot.source_ids},
        )
    risks = []
    if premium > config["convertible_bond_high_premium_pct"]:
        risks.append("转股溢价率偏高，债价可能脱离正股转股价值。")
    if snapshot.remaining_balance < config["convertible_bond_low_balance"]:
        risks.append("剩余规模较低，波动和流动性风险可能放大。")
    if snapshot.amount < config["convertible_bond_minimum_amount"]:
        risks.append("成交额低于配置的研究流动性门槛。")
    stage = "风险约束较多" if risks else "常规观察"
    return SkillInsight(
        "可转债研究", "special_instrument", stage, config["convertible_bond_risk_score"] if risks else config["convertible_bond_regular_score"],
        f"转股价值 {parity:.2f}，转股溢价率 {premium:.2f}%，当前为{stage}。",
        "结合赎回、回售、到期、余额和正股风险进行研究，不将溢价率单独用作交易指令。",
        evidence=[f"数据时间：{snapshot.as_of}", f"债价：{snapshot.bond_price}", f"转股价值：{parity:.2f}", f"转股溢价率：{premium:.2f}%", f"剩余规模：{snapshot.remaining_balance}", f"成交额：{snapshot.amount}"],
        risks=risks, details={"parity": parity, "premium_pct": premium, "source_ids": snapshot.source_ids},
    )
