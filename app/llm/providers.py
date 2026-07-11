from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ModelProviderSpec:
    id: str
    name: str
    base_url: str
    default_model: str
    env_key: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


PROVIDERS: dict[str, ModelProviderSpec] = {
    "deepseek": ModelProviderSpec("deepseek", "DeepSeek", "https://api.deepseek.com", "deepseek-v4-pro", "DEEPSEEK_API_KEY"),
    "glm": ModelProviderSpec("glm", "GLM（智谱）", "https://open.bigmodel.cn/api/paas/v4", "glm-5.1", "ZAI_API_KEY"),
    "qwen": ModelProviderSpec("qwen", "通义千问（百炼）", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus", "DASHSCOPE_API_KEY"),
}


def get_provider(provider_id: str) -> ModelProviderSpec:
    try:
        return PROVIDERS[provider_id]
    except KeyError as exc:
        raise ValueError(f"Unsupported model provider: {provider_id}") from exc


def list_providers() -> list[ModelProviderSpec]:
    return list(PROVIDERS.values())
