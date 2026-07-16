from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from app.config.runtime import load_runtime_settings


T = TypeVar("T")


class VerifiedDatasetCache:
    """Durable last-known-good cache for normalized, quality-checked facts.

    This cache is deliberately separate from raw provider snapshots: raw
    failures are useful for audit, but only normalized values accepted by the
    production router may enter this store.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        config = load_runtime_settings().get("providers", "high_availability", "verified_cache")
        configured = root or os.getenv(config["directory_env"], config["directory"])
        path = Path(configured)
        if not path.is_absolute():
            path = Path(load_runtime_settings().source).resolve().parent.parent / path
        self.root = path
        self.schema_version = str(config["schema_version"])

    def save(self, dataset: str, key: str, value: object, *, source_type: str, as_of: str) -> str:
        if not is_dataclass(value) and not isinstance(value, list):
            raise TypeError("Verified cache accepts dataclasses or lists of dataclasses")
        payload_value = _json_value(value)
        content = {
            "schema_version": self.schema_version,
            "dataset": dataset,
            "key": key,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "source_type": source_type,
            "as_of": as_of,
            "payload": payload_value,
        }
        digest = _digest(content)
        envelope = {**content, "sha256": digest}
        path = self._path(dataset, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        temporary.replace(path)
        return digest

    def load(
        self,
        dataset: str,
        key: str,
        factory: Callable[[dict[str, Any]], T],
    ) -> tuple[T, dict[str, str]] | None:
        path = self._path(dataset, key)
        if not path.exists():
            return None
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            digest = str(envelope.pop("sha256"))
            if envelope.get("schema_version") != self.schema_version or _digest(envelope) != digest:
                return None
            raw = envelope["payload"]
            if not isinstance(raw, dict):
                return None
            value = factory(raw)
            metadata = {
                "source_type": str(envelope["source_type"]),
                "as_of": str(envelope["as_of"]),
                "saved_at": str(envelope["saved_at"]),
                "sha256": digest,
            }
            return value, metadata
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def load_list(
        self,
        dataset: str,
        key: str,
        factory: Callable[[dict[str, Any]], T],
    ) -> tuple[list[T], dict[str, str]] | None:
        path = self._path(dataset, key)
        if not path.exists():
            return None
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            digest = str(envelope.pop("sha256"))
            if envelope.get("schema_version") != self.schema_version or _digest(envelope) != digest:
                return None
            raw = envelope["payload"]
            if not isinstance(raw, list):
                return None
            values = [factory(item) for item in raw if isinstance(item, dict)]
            metadata = {
                "source_type": str(envelope["source_type"]),
                "as_of": str(envelope["as_of"]),
                "saved_at": str(envelope["saved_at"]),
                "sha256": digest,
            }
            return values, metadata
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def is_fresh(self, dataset: str, metadata: dict[str, str]) -> bool:
        config = load_runtime_settings().get("providers", "high_availability", "verified_cache")
        maximum = int(config["fresh_seconds"].get(dataset, 0))
        if maximum <= 0:
            return False
        try:
            saved_at = datetime.fromisoformat(metadata["saved_at"])
            if saved_at.tzinfo is None:
                saved_at = saved_at.replace(tzinfo=timezone.utc)
            return 0 <= (datetime.now(timezone.utc) - saved_at).total_seconds() <= maximum
        except (KeyError, ValueError):
            return False

    def _path(self, dataset: str, key: str) -> Path:
        safe_dataset = _safe(dataset)
        safe_key = _safe(key)
        return self.root / safe_dataset / f"{safe_key}.json"


class NullVerifiedDatasetCache:
    """No-op cache used by dependency-injected unit providers."""

    def save(self, *args: object, **kwargs: object) -> str:
        return ""

    def load(self, *args: object, **kwargs: object) -> None:
        return None

    def load_list(self, *args: object, **kwargs: object) -> None:
        return None

    def is_fresh(self, *args: object, **kwargs: object) -> bool:
        return False


def _json_value(value: object) -> Any:
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if is_dataclass(value):
        return asdict(value)
    return value


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _safe(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    return cleaned or "unknown"
