from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.config.runtime import load_runtime_settings
from app.market.morning_radar import MorningRadarSnapshot, SectorFlow
from app.schemas.report import IndustryFlowObservation


class IndustryFlowRankingSource(Protocol):
    def get_industry_flow_ranking(
        self,
        reference_date: str,
        calendar_lookback_days: int,
    ) -> tuple[str, list[IndustryFlowObservation]]: ...


class TushareIndustryRadarFallback:
    """Authenticated post-market sector-flow fallback for the intraday radar.

    It deliberately emits no fast-mover list because the documented upstream
    dataset is updated after market close, not during the session.
    """

    def __init__(self, source: IndustryFlowRankingSource) -> None:
        self._source = source

    def fetch_snapshot(self, limit: int, now: datetime) -> MorningRadarSnapshot | None:
        settings = load_runtime_settings().get("morning_radar", "tushare_eod_fallback")
        if not settings["enabled"]:
            return None
        as_of, flows = self._source.get_industry_flow_ranking(
            now.date().isoformat(),
            int(settings["calendar_lookback_days"]),
        )
        if len(flows) < int(settings["minimum_sector_rows"]):
            return None
        sectors = [
            SectorFlow(
                code=item.industry_code,
                name=item.industry,
                change_pct=item.pct_change,
                main_net_inflow=item.net_amount,
                main_net_inflow_ratio=None,
            )
            for item in flows
        ]
        inflow = sorted(
            (item for item in sectors if (item.main_net_inflow or 0) > 0),
            key=lambda item: item.main_net_inflow or 0,
            reverse=True,
        )[:limit]
        outflow = sorted(
            (item for item in sectors if (item.main_net_inflow or 0) < 0),
            key=lambda item: item.main_net_inflow or 0,
        )[:limit]
        if not inflow and not outflow:
            return None
        return MorningRadarSnapshot(
            as_of=as_of,
            source="tushare_moneyflow_ind_ths",
            data_status="latest_available",
            market_phase="最近完整交易日行业资金快照",
            top_inflow_sectors=inflow,
            top_outflow_sectors=outflow,
            fast_movers=[],
            shortline_read=(
                "当前展示 Tushare 同花顺行业资金流的最近完整交易日快照；"
                "它只可用于复盘与跨日观察，不得解释为当前盘中板块资金流。"
            ),
            risks=[
                "该备选源为盘后更新的行业资金流，不含当前盘中资金、涨速或盘口信息。",
                "不得据此生成盘中追涨、交易指令或对当前全市场短线情绪的判断。",
                "数据可用性取决于已配置且具备该接口权限的 Tushare 账户。",
            ],
        )
