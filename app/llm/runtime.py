from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.llm.deepseek_client import OpenAICompatibleClient, PostJson
from app.llm.providers import get_provider, list_providers
from app.schemas.report import AnalysisReport


_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,96}$")


class ModelRuntime:
    """Fixed-provider model runtime; session keys are intentionally never persisted."""

    def __init__(self, settings_path: str | Path, post_json: PostJson | None = None) -> None:
        self.settings_path = Path(settings_path)
        self._session_keys: dict[str, str] = {}
        self._post_json = post_json
        self._lock = threading.RLock()
        self._last_execution: dict[str, Any] | None = None
        self._configuration_revision = 0

    def status(self) -> dict[str, Any]:
        with self._lock:
            settings = self._load_settings()
            active_id = settings["provider_id"]
            return {
                "active_provider": active_id,
                "active_model": settings["model"],
                "last_execution": dict(self._last_execution) if self._last_execution else None,
                "providers": [
                    {
                        **provider.to_dict(),
                        "configured": self._key_source(provider.id) != "missing",
                        "key_source": self._key_source(provider.id),
                    }
                    for provider in list_providers()
                ],
            }

    def configure(self, provider_id: str, api_key: str, model: str | None = None) -> dict[str, Any]:
        provider = get_provider(provider_id)
        if not isinstance(api_key, str) or not 8 <= len(api_key) <= 512:
            raise ValueError("API key must contain 8 to 512 characters")
        selected_model = model.strip() if isinstance(model, str) and model.strip() else provider.default_model
        if not _MODEL_PATTERN.fullmatch(selected_model):
            raise ValueError("Model name contains unsupported characters")
        with self._lock:
            # A provider switch is one operation. Retaining another provider's
            # session key makes stale UI state needlessly ambiguous.
            self._session_keys.clear()
            self._session_keys[provider.id] = api_key
            self._save_settings({"provider_id": provider.id, "model": selected_model})
            self._last_execution = None
            self._configuration_revision += 1
        return self.status()

    def clear_session_key(self, provider_id: str) -> dict[str, Any]:
        get_provider(provider_id)
        with self._lock:
            self._session_keys.pop(provider_id, None)
        return self.status()

    def explain(
        self,
        report: AnalysisReport,
        memory_context: dict[str, Any],
        *,
        expected_provider_id: str | None = None,
        expected_model: str | None = None,
    ) -> AnalysisReport:
        with self._lock:
            settings = self._load_settings()
            provider = get_provider(settings["provider_id"])
            selected_model = settings["model"]
            expected_provider = get_provider(expected_provider_id) if expected_provider_id else provider
            expected_model_name = expected_model.strip() if expected_model else selected_model
            if not _MODEL_PATTERN.fullmatch(expected_model_name):
                raise ValueError("Model name contains unsupported characters")
            if expected_provider.id != provider.id or expected_model_name != selected_model:
                raise RuntimeError(
                    "模型选择尚未生效：本次研判选择 "
                    f"{expected_provider.name}/{expected_model_name}，后端当前配置为 "
                    f"{provider.name}/{selected_model}。请先保存模型配置后再开始研判。"
                )
            api_key = self._resolve_key(provider.id)
            if not api_key:
                raise RuntimeError(f"{provider.name} is not configured. Add a session key or set {provider.env_key}.")
            started_at = _utc_now()
            configuration_revision = self._configuration_revision
            self._last_execution = {
                "status": "running",
                "provider_id": provider.id,
                "provider_name": provider.name,
                "model": selected_model,
                "base_url": provider.base_url,
                "started_at": started_at,
            }
        client = OpenAICompatibleClient(
            api_key=api_key,
            base_url=provider.base_url,
            model=selected_model,
            provider_name=provider.name,
            post_json=self._post_json,
        )
        try:
            explained = client.explain(report, memory_context)
        except Exception as exc:
            with self._lock:
                self._last_execution = {
                    **(self._last_execution or {}),
                    "status": "failed",
                    "completed_at": _utc_now(),
                    "error": str(exc),
                }
            raise
        with self._lock:
            if configuration_revision != self._configuration_revision:
                self._last_execution = {
                    **(self._last_execution or {}),
                    "status": "discarded",
                    "completed_at": _utc_now(),
                    "error": "模型配置在研判过程中发生切换，旧模型结果已丢弃。",
                }
                raise RuntimeError("模型配置在研判过程中发生切换，本次旧模型结果已丢弃；请重新开始研判。")
        completed_at = _utc_now()
        completion_metadata = dict(explained.model_execution or {})
        execution = {
            "status": "succeeded",
            "provider_id": provider.id,
            "provider_name": provider.name,
            "model": selected_model,
            "base_url": provider.base_url,
            "started_at": started_at,
            "completed_at": completed_at,
            **completion_metadata,
        }
        with self._lock:
            self._last_execution = execution
        return replace(explained, model_execution=dict(execution))

    def _key_source(self, provider_id: str) -> str:
        if provider_id in self._session_keys:
            return "session"
        if os.environ.get(get_provider(provider_id).env_key):
            return "environment"
        return "missing"

    def _resolve_key(self, provider_id: str) -> str | None:
        return self._session_keys.get(provider_id) or os.environ.get(get_provider(provider_id).env_key)

    def _load_settings(self) -> dict[str, str]:
        default = {"provider_id": "deepseek", "model": get_provider("deepseek").default_model}
        if not self.settings_path.exists():
            return default
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            provider = get_provider(str(data.get("provider_id", default["provider_id"])))
            model = str(data.get("model", provider.default_model))
            return {"provider_id": provider.id, "model": model if _MODEL_PATTERN.fullmatch(model) else provider.default_model}
        except (OSError, ValueError, json.JSONDecodeError):
            return default

    def _save_settings(self, settings: dict[str, str]) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.settings_path.with_suffix(f"{self.settings_path.suffix}.tmp")
        temporary_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary_path, self.settings_path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
