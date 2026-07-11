from __future__ import annotations

import json
import os
import re
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

    def status(self) -> dict[str, Any]:
        settings = self._load_settings()
        active_id = settings["provider_id"]
        return {
            "active_provider": active_id,
            "active_model": settings["model"],
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
        self._session_keys[provider.id] = api_key
        self._save_settings({"provider_id": provider.id, "model": selected_model})
        return self.status()

    def clear_session_key(self, provider_id: str) -> dict[str, Any]:
        get_provider(provider_id)
        self._session_keys.pop(provider_id, None)
        return self.status()

    def explain(self, report: AnalysisReport, memory_context: dict[str, Any]) -> AnalysisReport:
        settings = self._load_settings()
        provider = get_provider(settings["provider_id"])
        api_key = self._resolve_key(provider.id)
        if not api_key:
            raise RuntimeError(f"{provider.name} is not configured. Add a session key or set {provider.env_key}.")
        client = OpenAICompatibleClient(
            api_key=api_key,
            base_url=provider.base_url,
            model=settings["model"],
            provider_name=provider.name,
            post_json=self._post_json,
        )
        return client.explain(report, memory_context)

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
        self.settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
