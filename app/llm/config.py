from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str | None
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-pro"
    reasoning_effort: str = "high"
    thinking_enabled: bool = True

    @classmethod
    def from_env(cls) -> "DeepSeekConfig":
        return cls(
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
            base_url=os.environ.get("DEEPSEEK_BASE_URL", cls.base_url),
            model=os.environ.get("DEEPSEEK_MODEL", cls.model),
            reasoning_effort=os.environ.get("DEEPSEEK_REASONING_EFFORT", cls.reasoning_effort),
            thinking_enabled=os.environ.get("DEEPSEEK_THINKING", "enabled").lower() != "disabled",
        )

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def extra_body(self) -> dict[str, object]:
        return {"thinking": {"type": "enabled" if self.thinking_enabled else "disabled"}}

