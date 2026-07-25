from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.config.runtime import load_runtime_settings
from app.schemas.report import EvidenceSource


_PARENTHESIZED_SOURCE_REFERENCE = re.compile(
    r"[\(（]\s*(?:如|例如)?\s*"
    r"source[\s_-]*id\s*[:=：]\s*(?P<source_id>[A-Za-z0-9_.:-]+)"
    r"(?:\s*[,，]\s*as[\s_-]*of\s*[:=：]\s*[^)）]+)?\s*[\)）]",
    re.IGNORECASE,
)
_BARE_SOURCE_REFERENCE = re.compile(
    r"(?:source[\s_-]*id|来源\s*ID)\s*[:=：]\s*(?P<source_id>[A-Za-z0-9_.:-]+)"
    r"(?:\s*[,，]\s*(?:as[\s_-]*of|截止)\s*[:=：]\s*[0-9T: +.-]+)?",
    re.IGNORECASE,
)
_INTERNAL_SOURCE_ID_TOKEN = re.compile(
    r"\b[A-Za-z][A-Za-z0-9_.:-]*-(?:\d{3}|[a-f0-9]{12,})\b",
    re.IGNORECASE,
)


def public_evidence_citation(source: EvidenceSource) -> str:
    config = _config()
    return str(config["format"]).format(
        title=source.title or config["unknown_source"],
        provider=public_source_type(source.source_type),
        as_of=source.as_of or "时间待核验",
    )


def public_source_type(source_type: str) -> str:
    config = _config()
    normalized = str(source_type or "").strip()
    cache_prefix = "verified_cache:"
    if normalized.startswith(cache_prefix):
        original = public_source_type(normalized[len(cache_prefix):])
        return str(config["cache_provider_format"]).format(provider=original)
    labels = config["source_type_labels"]
    lowered = normalized.lower()
    for token in sorted(labels, key=len, reverse=True):
        if token.lower() in lowered:
            return str(labels[token])
    return str(config["unknown_provider"])


def sanitize_model_interpretation(
    content: str,
    sources: list[EvidenceSource],
) -> str:
    """Replace internal source syntax with user-facing, report-owned citations."""
    source_map = {source.id: source for source in sources}

    def replace_reference(match: re.Match[str]) -> str:
        source = source_map.get(match.group("source_id"))
        if source is None:
            return f"【{_config()['unknown_source']}】"
        return public_evidence_citation(source)

    rendered = _PARENTHESIZED_SOURCE_REFERENCE.sub(replace_reference, content)
    return _BARE_SOURCE_REFERENCE.sub(replace_reference, rendered)


def model_friendly_evidence(value: Any, source_map: Mapping[str, EvidenceSource]) -> Any:
    """Remove internal source identifiers from the model-facing evidence packet."""
    if isinstance(value, Mapping):
        if {"id", "title", "source_type", "as_of"} <= set(value):
            source = source_map.get(str(value["id"]))
            return {
                "citation": (
                    public_evidence_citation(source)
                    if source is not None
                    else f"【{_config()['unknown_source']}】"
                )
            }
        rendered: dict[str, Any] = {}
        for key, item in value.items():
            public_key = str(key)
            if public_key == "as_of":
                public_key = "data_date"
            if public_key.endswith("source_ids") and isinstance(item, list):
                public_key = f"{public_key[:-len('source_ids')]}source_citations"
                rendered[public_key] = [
                    public_evidence_citation(source_map[source_id])
                    for source_id in item
                    if source_id in source_map
                ]
            else:
                rendered[public_key] = model_friendly_evidence(item, source_map)
        return rendered
    if isinstance(value, list):
        return [model_friendly_evidence(item, source_map) for item in value]
    if isinstance(value, tuple):
        return [model_friendly_evidence(item, source_map) for item in value]
    if isinstance(value, str):
        rendered = value
        for source_id in sorted(source_map, key=len, reverse=True):
            rendered = rendered.replace(source_id, public_evidence_citation(source_map[source_id]))
        return _INTERNAL_SOURCE_ID_TOKEN.sub(
            lambda match: (
                public_evidence_citation(source_map[match.group(0)])
                if match.group(0) in source_map
                else f"【{_config()['unknown_source']}】"
            ),
            rendered,
        )
    return value


def _config() -> dict[str, Any]:
    return load_runtime_settings().get("reporting", "citations")
