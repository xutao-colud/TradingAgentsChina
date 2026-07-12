from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.llm.config import DeepSeekConfig
from app.llm.prompt_contracts import build_explanation_system_prompt, build_explanation_user_message
from app.schemas.report import AnalysisReport


PostJson = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]


class OpenAICompatibleClient:
    """Provider-neutral OpenAI-compatible explanation client."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        provider_name: str,
        post_json: PostJson | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.provider_name = provider_name
        self._post_json = post_json or _post_json

    def explain(self, report: AnalysisReport, memory_context: dict[str, Any]) -> AnalysisReport:
        response = self._post_json(
            f"{self.base_url.rstrip('/')}/chat/completions",
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            {
                "model": self.model,
                "temperature": 0.2,
                "max_tokens": 1200,
                "messages": [
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": _build_user_message(report, memory_context)},
                ],
            },
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"{self.provider_name} response did not contain choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f"{self.provider_name} returned an empty explanation")
        return replace(report, model_interpretation=content.strip())


class DeepSeekClient:
    """Optional explanation layer for deterministic A-share reports.

    The model receives market facts and personal-memory summaries as untrusted
    reference data. It never produces or overwrites numerical scores, risk
    gates, or executable trading instructions.
    """

    def __init__(self, config: DeepSeekConfig, post_json: PostJson | None = None) -> None:
        self.config = config
        self._post_json = post_json or _post_json

    def explain(self, report: AnalysisReport, memory_context: dict[str, Any]) -> AnalysisReport:
        if not self.config.is_configured():
            raise RuntimeError("DEEPSEEK_API_KEY is required when --deepseek-explain is enabled.")

        request_payload = {
            "model": self.config.model,
            "temperature": 0.2,
            "max_tokens": 1200,
            "messages": [
                {
                    "role": "system",
                    "content": _system_prompt(),
                },
                {
                    "role": "user",
                    "content": _build_user_message(report, memory_context),
                },
            ],
        }
        request_payload.update(self.config.extra_body())
        response = self._post_json(
            f"{self.config.base_url.rstrip('/')}/chat/completions",
            {
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            request_payload,
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("DeepSeek response did not contain choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("DeepSeek returned an empty explanation")
        return replace(report, model_interpretation=content.strip())


def _build_user_message(report: AnalysisReport, memory_context: dict[str, Any]) -> str:
    return build_explanation_user_message(report, memory_context)


def _system_prompt() -> str:
    return build_explanation_system_prompt()


def _post_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"DeepSeek API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Unable to reach DeepSeek API: {exc.reason}") from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("DeepSeek API returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("DeepSeek API returned a non-object response")
    return parsed
