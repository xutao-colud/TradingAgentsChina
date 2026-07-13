from __future__ import annotations

from dataclasses import asdict, dataclass

from app.config.runtime import load_runtime_settings


@dataclass(frozen=True)
class ModelProviderSpec:
    id: str
    name: str
    base_url: str
    default_model: str
    env_key: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _providers() -> dict[str, ModelProviderSpec]:
    return {
        item["id"]: ModelProviderSpec(item["id"], item["name"], item["base_url"], item["default_model"], item["env_key"])
        for item in load_runtime_settings().get("providers", "models")
    }


def get_provider(provider_id: str) -> ModelProviderSpec:
    try:
        return _providers()[provider_id]
    except KeyError as exc:
        raise ValueError(f"Unsupported model provider: {provider_id}") from exc


def list_providers() -> list[ModelProviderSpec]:
    return list(_providers().values())
