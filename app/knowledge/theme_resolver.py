from __future__ import annotations

from dataclasses import dataclass

from app.config.runtime import load_runtime_settings
from app.schemas.report import StockProfile


@dataclass(frozen=True)
class ThemeMatch:
    theme: str
    source: str
    matched_value: str


def resolve_themes(profile: StockProfile, market_themes: list[str]) -> list[ThemeMatch]:
    """Match active market themes to company concepts before industry defaults."""
    config = load_runtime_settings().get("domain_knowledge", "theme")
    canonical_market = {_canonical(value, config["aliases"]): value for value in market_themes}
    profile_concepts = {_canonical(value, config["aliases"]): value for value in profile.concepts}
    industry_defaults = {_canonical(value, config["aliases"]) for value in config["industry_defaults"].get(profile.industry, [])}
    universal = {_canonical(value, config["aliases"]) for value in config["market_wide_themes"]}
    matches: list[ThemeMatch] = []
    for canonical, market_label in canonical_market.items():
        if canonical in profile_concepts:
            matches.append(ThemeMatch(market_label, "provider_concept", profile_concepts[canonical]))
        elif canonical in industry_defaults:
            matches.append(ThemeMatch(market_label, "configured_industry_default", profile.industry))
        elif canonical in universal:
            matches.append(ThemeMatch(market_label, "configured_market_wide", market_label))
    return matches


def _canonical(value: str, aliases: dict[str, list[str]]) -> str:
    normalized = value.strip().lower()
    for canonical, variants in aliases.items():
        if normalized == canonical.lower() or normalized in {item.lower() for item in variants}:
            return canonical
    return value.strip()
