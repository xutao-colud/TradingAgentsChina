from __future__ import annotations

import os
from dataclasses import dataclass, field

from app.config.runtime import load_runtime_settings


def _deepseek_setting(key: str) -> object:
    providers = load_runtime_settings().get("providers", "models")
    provider = next((item for item in providers if item.get("id") == "deepseek"), {})
    return provider[key]


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str | None
    base_url: str = field(default_factory=lambda: str(_deepseek_setting("base_url")))
    model: str = field(default_factory=lambda: str(_deepseek_setting("default_model")))
    reasoning_effort: str = field(default_factory=lambda: str(_deepseek_setting("reasoning_effort")))
    thinking_enabled: bool = field(default_factory=lambda: bool(_deepseek_setting("thinking_enabled")))

    @classmethod
    def from_env(cls) -> "DeepSeekConfig":
        defaults = cls(api_key=None)
        return cls(
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
            base_url=os.environ.get("DEEPSEEK_BASE_URL", defaults.base_url),
            model=os.environ.get("DEEPSEEK_MODEL", defaults.model),
            reasoning_effort=os.environ.get("DEEPSEEK_REASONING_EFFORT", defaults.reasoning_effort),
            thinking_enabled=os.environ.get("DEEPSEEK_THINKING", "enabled").lower() != "disabled",
        )

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def extra_body(self) -> dict[str, object]:
        return {"thinking": {"type": "enabled" if self.thinking_enabled else "disabled"}}
