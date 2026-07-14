from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.config.runtime import load_runtime_settings


@dataclass(frozen=True)
class RawDataSnapshot:
    schema_version: str
    snapshot_id: str
    provider: str
    interface: str
    requested_at: str
    analysis_date: str | None
    symbol: str | None
    request_params: dict[str, Any]
    records: list[dict[str, Any]]
    record_count: int
    source_record_count: int
    truncated: bool
    status: str
    error: str | None
    content_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RawSnapshotStore(Protocol):
    def save(self, snapshot: RawDataSnapshot) -> None: ...

    def list(self) -> list[RawDataSnapshot]: ...

    def get(self, snapshot_id: str) -> RawDataSnapshot | None: ...


class InMemoryRawSnapshotStore:
    def __init__(self) -> None:
        self._items: list[RawDataSnapshot] = []

    def save(self, snapshot: RawDataSnapshot) -> None:
        self._items.append(snapshot)

    def list(self) -> list[RawDataSnapshot]:
        return list(self._items)

    def get(self, snapshot_id: str) -> RawDataSnapshot | None:
        return next((item for item in self._items if item.snapshot_id == snapshot_id), None)


class LocalRawSnapshotStore:
    """Append-only local JSON snapshots with atomic writes and hash verification."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @classmethod
    def from_runtime(cls) -> "LocalRawSnapshotStore":
        settings = load_runtime_settings()
        config = settings.get("data_quality", "raw_snapshots")
        configured = os.getenv(config["directory_env"], config["directory"])
        root = Path(configured)
        if not root.is_absolute():
            root = Path(settings.source).resolve().parent.parent / root
        return cls(root)

    def save(self, snapshot: RawDataSnapshot) -> None:
        day = snapshot.requested_at[:10]
        directory = self.root / _safe_component(snapshot.provider) / _safe_component(snapshot.interface) / day
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{_safe_component(snapshot.snapshot_id)}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(snapshot.to_dict(), ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    def list(self) -> list[RawDataSnapshot]:
        if not self.root.exists():
            return []
        items: list[RawDataSnapshot] = []
        for path in sorted(self.root.rglob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            items.append(RawDataSnapshot(**payload))
        return items

    def get(self, snapshot_id: str) -> RawDataSnapshot | None:
        safe_id = _safe_component(snapshot_id)
        path = next(self.root.rglob(f"{safe_id}.json"), None) if self.root.exists() else None
        if path is None:
            return None
        return RawDataSnapshot(**json.loads(path.read_text(encoding="utf-8")))


def build_raw_snapshot(
    *,
    provider: str,
    interface: str,
    request_params: dict[str, object],
    records: list[dict[str, Any]],
    status: str,
    error: str | None = None,
    requested_at: datetime | None = None,
) -> RawDataSnapshot:
    config = load_runtime_settings().get("data_quality", "raw_snapshots")
    redacted_names = {str(item).lower() for item in config["redacted_parameter_names"]}
    safe_params = _redact_mapping(
        request_params,
        redacted_names=redacted_names,
        redaction_value=config["redaction_value"],
    )
    maximum = int(config["max_records_per_snapshot"])
    safe_records = [_json_safe(record) for record in records[:maximum]]
    timestamp = (requested_at or datetime.now(timezone.utc)).isoformat()
    analysis_date = _infer_analysis_date(safe_params)
    symbol = _infer_symbol(safe_params)
    content = {
        "schema_version": str(config["schema_version"]),
        "provider": provider,
        "interface": interface,
        "requested_at": timestamp,
        "analysis_date": analysis_date,
        "symbol": symbol,
        "request_params": safe_params,
        "records": safe_records,
        "record_count": len(safe_records),
        "source_record_count": len(records),
        "truncated": len(records) > len(safe_records),
        "status": status,
        "error": _redact_error(error, request_params, redacted_names, config["redaction_value"]),
    }
    digest = snapshot_digest(content)
    return RawDataSnapshot(
        **content,
        snapshot_id=f"{_safe_component(provider)}-{_safe_component(interface)}-{digest[:20]}",
        content_sha256=digest,
    )


def snapshot_digest(snapshot: RawDataSnapshot | dict[str, Any]) -> str:
    payload = snapshot.to_dict() if isinstance(snapshot, RawDataSnapshot) else dict(snapshot)
    payload.pop("snapshot_id", None)
    payload.pop("content_sha256", None)
    canonical = json.dumps(_json_safe(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def snapshot_is_intact(snapshot: RawDataSnapshot) -> bool:
    count_is_valid = (
        snapshot.record_count == len(snapshot.records)
        and snapshot.source_record_count >= snapshot.record_count
        and snapshot.truncated == (snapshot.source_record_count > snapshot.record_count)
    )
    return count_is_valid and snapshot.content_sha256 == snapshot_digest(snapshot)


def snapshot_matches(snapshot: RawDataSnapshot, symbol: str, analysis_date: str) -> bool:
    normalized_snapshot = (snapshot.symbol or "").split(".")[0]
    normalized_symbol = symbol.split(".")[0]
    symbol_matches = not normalized_snapshot or normalized_snapshot == normalized_symbol
    date_matches = snapshot.analysis_date in {None, analysis_date}
    return symbol_matches and date_matches


def _infer_analysis_date(params: dict[str, Any]) -> str | None:
    for key in ("trade_date", "end_date", "date"):
        value = str(params.get(key, ""))[:10]
        digits = value.replace("-", "")
        if len(digits) == 8 and digits.isdigit():
            try:
                return date.fromisoformat(f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}").isoformat()
            except ValueError:
                continue
    return None


def _infer_symbol(params: dict[str, Any]) -> str | None:
    for key in ("ts_code", "symbol", "code"):
        value = str(params.get(key, "")).strip()
        if value:
            return value.upper()
    return None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    item = getattr(value, "item", None)
    if callable(item):
        return _json_safe(item())
    return str(value)


def _redact_mapping(
    value: dict[str, object],
    *,
    redacted_names: set[str],
    redaction_value: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        text_key = str(key)
        if text_key.lower() in redacted_names:
            result[text_key] = redaction_value
        elif isinstance(item, dict):
            result[text_key] = _redact_mapping(
                item,
                redacted_names=redacted_names,
                redaction_value=redaction_value,
            )
        else:
            result[text_key] = _json_safe(item)
    return result


def _redact_error(
    error: str | None,
    request_params: dict[str, object],
    redacted_names: set[str],
    redaction_value: str,
) -> str | None:
    if error is None:
        return None
    sanitized = error
    for key, value in request_params.items():
        if str(key).lower() in redacted_names and value is not None and str(value) != "":
            sanitized = sanitized.replace(str(value), redaction_value)
    return sanitized


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    return cleaned or "unknown"
