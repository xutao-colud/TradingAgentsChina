from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
from datetime import date
from typing import Any, TypeVar

from app.config.runtime import load_runtime_settings
from app.data.raw_snapshots import RawDataSnapshot, snapshot_is_intact
from app.schemas.report import DataQualityIssue, DataQualityReport


T = TypeVar("T")


def validate_dataset_records(
    *,
    provider: str,
    dataset: str,
    records: list[T],
    analysis_date: str,
    snapshot_ids: list[str] | None = None,
) -> tuple[list[T], DataQualityReport]:
    """Validate normalized provider records using runtime-configured quality rules."""
    config = load_runtime_settings().get("data_quality", "datasets", dataset)
    issues: list[DataQualityIssue] = []
    valid: list[T] = []
    required_fields = tuple(config["required_fields"])
    non_negative_fields = tuple(config["non_negative_fields"])
    finite_fields = tuple(config["finite_fields"])
    date_field = config["date_field"]
    unique_fields = tuple(config["unique_fields"])
    seen_unique_keys: set[tuple[str, ...]] = set()

    for index, record in enumerate(records):
        row = _record_dict(record)
        record_issues: list[DataQualityIssue] = []
        if unique_fields:
            unique_key = tuple(str(row.get(field_name, "")) for field_name in unique_fields)
            if unique_key in seen_unique_keys:
                record_issues.append(
                    DataQualityIssue(
                        code="duplicate_record",
                        severity="error",
                        message=load_runtime_settings().get("data_quality", "issue_messages", "duplicate_record"),
                        record_index=index,
                    )
                )
            else:
                seen_unique_keys.add(unique_key)
        for field_name in required_fields:
            if _is_missing(row.get(field_name)):
                record_issues.append(_issue("missing_required_field", "error", field_name, index))
        for field_name in finite_fields:
            value = row.get(field_name)
            if value is not None and not _is_finite_number(value):
                record_issues.append(_issue("non_finite_number", "error", field_name, index))
        for field_name in non_negative_fields:
            value = row.get(field_name)
            if value is not None and (_as_float(value) is None or float(value) < 0):
                record_issues.append(_issue("negative_value", "error", field_name, index))

        raw_date = str(row.get(date_field, ""))
        parsed_date = _parse_iso_date(raw_date)
        if parsed_date is None:
            record_issues.append(_issue("invalid_date", "error", date_field, index))
        elif config["require_analysis_date_match"] and parsed_date.isoformat() != analysis_date:
            record_issues.append(
                DataQualityIssue(
                    code="analysis_date_mismatch",
                    severity="error",
                    message=f"{date_field}={parsed_date.isoformat()} does not match analysis_date={analysis_date}.",
                    field=date_field,
                    record_index=index,
                )
            )
        elif not config["allow_future_date"] and parsed_date > date.fromisoformat(analysis_date):
            record_issues.append(_issue("future_date", "error", date_field, index))

        ohlc = config.get("ohlc_fields")
        if ohlc:
            record_issues.extend(_validate_ohlc(row, ohlc, index))

        issues.extend(record_issues)
        if not any(item.severity == "error" for item in record_issues):
            valid.append(record)

    checked = len(records)
    minimum_records = int(config.get("minimum_records", 0))
    if checked == 0:
        empty_status = str(config["empty_status"])
        if empty_status != "passed":
            issues.append(
                DataQualityIssue(
                    code="empty_dataset",
                    severity="warning" if empty_status == "warning" else "error",
                    message=f"{provider}.{dataset} returned no records; no neutral fact was synthesized.",
                )
            )
        status = empty_status
        completeness = 0.0
    else:
        completeness = round(len(valid) / checked, 4)
        status = "failed" if len(valid) < checked else "passed"

    if len(valid) < minimum_records:
        issues.append(
            DataQualityIssue(
                code="insufficient_records",
                severity="error",
                message=(
                    f"{provider}.{dataset} has {len(valid)} valid records; "
                    f"at least {minimum_records} are required."
                ),
            )
        )
        status = "failed"

    return valid, DataQualityReport(
        provider=provider,
        dataset=dataset,
        status=status,
        checked_records=checked,
        valid_records=len(valid),
        completeness=completeness,
        as_of=analysis_date,
        snapshot_ids=list(snapshot_ids or []),
        issues=issues,
        blocking=bool(config["blocking"]),
    )


def validate_raw_snapshot(snapshot: RawDataSnapshot) -> DataQualityReport:
    issues: list[DataQualityIssue] = []
    if not snapshot_is_intact(snapshot):
        issues.append(
            DataQualityIssue(
                code="snapshot_integrity_failure",
                severity="error",
                message="Raw snapshot hash or record_count does not match its content.",
            )
        )
    if snapshot.status != "success":
        issues.append(
            DataQualityIssue(
                code="provider_request_failed",
                severity="error",
                message=snapshot.error or "Provider request failed without an error message.",
            )
        )
    if snapshot.truncated:
        issues.append(
            DataQualityIssue(
                code="snapshot_truncated",
                severity="warning",
                message=(
                    f"Snapshot stored {snapshot.record_count} of "
                    f"{snapshot.source_record_count} source records."
                ),
            )
        )
    status = (
        "failed"
        if any(item.severity == "error" for item in issues)
        else "warning"
        if issues
        else "passed"
    )
    return DataQualityReport(
        provider=snapshot.provider,
        dataset=f"raw:{snapshot.interface}",
        status=status,
        checked_records=snapshot.record_count,
        valid_records=snapshot.record_count if status != "failed" else 0,
        completeness=(
            round(snapshot.record_count / snapshot.source_record_count, 4)
            if status != "failed" and snapshot.source_record_count
            else 1.0
            if status != "failed"
            else 0.0
        ),
        as_of=snapshot.analysis_date,
        snapshot_ids=[snapshot.snapshot_id],
        issues=issues,
        blocking=False,
    )


def _record_dict(record: object) -> dict[str, Any]:
    if isinstance(record, dict):
        return record
    if is_dataclass(record):
        return asdict(record)
    raise TypeError("Quality validation accepts dictionaries or dataclass records")


def _validate_ohlc(row: dict[str, Any], fields: dict[str, str], index: int) -> list[DataQualityIssue]:
    values = {name: _as_float(row.get(field_name)) for name, field_name in fields.items()}
    if any(value is None for value in values.values()):
        return []
    open_price = values["open"]
    high = values["high"]
    low = values["low"]
    close = values["close"]
    if high < max(open_price, close) or low > min(open_price, close) or high < low:
        return [
            DataQualityIssue(
                code="invalid_ohlc_range",
                severity="error",
                message="OHLC values violate high/low price invariants.",
                record_index=index,
            )
        ]
    return []


def _issue(code: str, severity: str, field_name: str, index: int) -> DataQualityIssue:
    messages = load_runtime_settings().get("data_quality", "issue_messages")
    template = messages[code]
    return DataQualityIssue(
        code=code,
        severity=severity,
        message=template.format(field=field_name),
        field=field_name,
        record_index=index,
    )


def _is_missing(value: object) -> bool:
    return value is None or str(value).strip().lower() in {"", "none", "nan"}


def _is_finite_number(value: object) -> bool:
    parsed = _as_float(value)
    return parsed is not None and math.isfinite(parsed)


def _as_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
