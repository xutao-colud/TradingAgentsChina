from __future__ import annotations

from app.agents.announcement_agent import analyze_announcements
from app.agents.bear_researcher import build_bear_case
from app.agents.bull_researcher import build_bull_case
from app.agents.capital_flow_agent import analyze_capital_flow
from app.agents.fundamental_agent import analyze_fundamentals
from app.agents.market_agent import analyze_market
from app.agents.portfolio_manager import decide_rating
from app.agents.risk_manager import assess_risk
from app.agents.technical_agent import analyze_technical
from app.agents.theme_agent import analyze_theme
from app.data.providers.base import MarketDataProvider
from app.data.providers.sample_provider import SampleMarketDataProvider
from app.graph.state import ResearchState
from app.memory.models import TradingProfile
from app.playbooks.evaluator import assess_active_playbook
from app.rules.trading_rules import invalid_conditions, normalize_symbol
from app.schemas.report import AnalysisReport
from app.skills.announcement_impact import analyze_announcement_impact
from app.skills.evidence_chain import assess_evidence_chain_quality
from app.skills.investment_committee import assess_investment_faction_committee
from app.skills.main_force_behavior import identify_main_force_behavior
from app.skills.market_temperature import assess_market_temperature
from app.skills.money_making_effect import assess_money_making_effect
from app.skills.profile_alignment import assess_profile_alignment
from app.skills.risk_scanner import scan_a_share_risks
from app.skills.sentiment_cycle import identify_sentiment_cycle
from app.skills.stock_score_model import score_stock_composite
from app.skills.theme_lifecycle import analyze_theme_lifecycle


class AShareResearchWorkflow:
    def __init__(self, provider: MarketDataProvider) -> None:
        self.provider = provider

    def run(
        self,
        symbol: str,
        analysis_date: str,
        trading_profile: TradingProfile | None = None,
        user_question: str | None = None,
    ) -> AnalysisReport:
        normalized_symbol = normalize_symbol(symbol)
        state = ResearchState(
            symbol=normalized_symbol,
            analysis_date=analysis_date,
            trading_profile=trading_profile,
            user_question=user_question,
        )
        self._collect_data(state)
        self._run_agents(state)
        self._run_domain_skills(state)
        return self._build_report(state)

    def _collect_data(self, state: ResearchState) -> None:
        state.profile = self.provider.get_stock_profile(state.symbol)
        state.prices = self.provider.get_daily_prices(state.symbol, state.analysis_date, lookback_days=30)
        state.fundamentals = self.provider.get_fundamentals(state.symbol)
        state.money_flow = self.provider.get_money_flow(state.symbol, state.analysis_date)
        state.announcements = self.provider.get_announcements(state.symbol, state.analysis_date)
        state.market_context = self.provider.get_market_context(state.analysis_date)
        state.evidence_sources = self.provider.get_evidence_sources(state.symbol, state.analysis_date)
        state.invalid_conditions = invalid_conditions(state.profile, state.prices)

    def _run_agents(self, state: ResearchState) -> None:
        if not all([state.profile, state.fundamentals, state.money_flow, state.market_context]):
            raise ValueError("Incomplete research state; provider returned missing data.")
        state.findings = [
            analyze_market(state.market_context),
            analyze_fundamentals(state.fundamentals),
            analyze_technical(state.prices),
            analyze_capital_flow(state.money_flow),
            analyze_announcements(state.announcements),
            analyze_theme(state.profile, state.market_context),
        ]

    def _run_domain_skills(self, state: ResearchState) -> None:
        if not all([state.profile, state.fundamentals, state.money_flow, state.market_context]):
            raise ValueError("Incomplete research state; cannot run domain skills.")
        base_insights = [
            assess_market_temperature(state.market_context),
            identify_sentiment_cycle(state.market_context),
            assess_money_making_effect(state.market_context),
            analyze_theme_lifecycle(state.profile, state.market_context),
            identify_main_force_behavior(state.prices, state.money_flow),
            analyze_announcement_impact(state.announcements),
            scan_a_share_risks(state.profile, state.fundamentals, state.invalid_conditions),
            assess_evidence_chain_quality(state.findings, state.evidence_sources),
        ]
        composite = score_stock_composite(state.findings, base_insights)
        profile_alignment = assess_profile_alignment(state.trading_profile, state.findings, base_insights + [composite])
        state.skill_insights = base_insights + [composite]
        if profile_alignment:
            state.skill_insights.append(profile_alignment)
        playbook_assessment = assess_active_playbook(state.trading_profile, state.findings, state.skill_insights)
        if playbook_assessment:
            state.skill_insights.append(playbook_assessment)
        state.skill_insights.append(
            assess_investment_faction_committee(
                state.findings,
                state.skill_insights,
                state.invalid_conditions,
                user_question=state.user_question,
            )
        )

    def _build_report(self, state: ResearchState) -> AnalysisReport:
        if not state.profile or not state.market_context:
            raise ValueError("Cannot build report before data collection.")
        conclusion, action_plan, confidence = decide_rating(state.findings, state.invalid_conditions, state.skill_insights)
        risk_level, risk_factors = assess_risk(state.findings, state.invalid_conditions, state.skill_insights)
        finding_by_agent = {item.agent: item for item in state.findings}
        return AnalysisReport(
            symbol=state.profile.symbol,
            name=state.profile.name,
            analysis_date=state.analysis_date,
            market_regime=state.market_context.hot_money_cycle,
            fundamental_score=finding_by_agent["基本面 Agent"].score,
            technical_score=finding_by_agent["技术分析 Agent"].score,
            capital_flow_score=finding_by_agent["资金流 Agent"].score,
            sentiment_score=finding_by_agent["新闻公告 Agent"].score,
            theme_score=finding_by_agent["题材热点 Agent"].score,
            risk_level=risk_level,
            conclusion=conclusion,
            confidence=confidence,
            action_plan=action_plan,
            bull_case=build_bull_case(state.findings),
            bear_case=build_bear_case(state.findings),
            risk_factors=risk_factors,
            invalid_conditions=state.invalid_conditions,
            agent_findings=state.findings,
            evidence_sources=state.evidence_sources,
            skill_insights=state.skill_insights,
            active_playbook=state.trading_profile.active_playbook if state.trading_profile else None,
            user_question=state.user_question,
        )


def build_default_workflow() -> AShareResearchWorkflow:
    return AShareResearchWorkflow(provider=SampleMarketDataProvider())
