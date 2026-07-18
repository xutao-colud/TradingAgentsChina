from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.llm.config import DeepSeekConfig
from app.llm.prompt_contracts import (
    EXPLANATION_COMPLETE_MARKER,
    build_explanation_system_prompt,
    build_explanation_user_message,
)
from app.config.runtime import load_runtime_settings
from app.network.retry import is_outbound_access_denied
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
        request_config = load_runtime_settings().get("runtime", "llm_request")
        request_payload = {
            "model": self.model,
            "temperature": request_config["temperature"],
            "max_tokens": request_config["max_tokens"],
            "messages": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": _build_user_message(report, memory_context)},
            ],
        }
        try:
            content, metadata = _request_complete_explanation(
                url=f"{self.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                request_payload=request_payload,
                provider_name=self.provider_name,
                request_config=request_config,
                post_json=self._post_json,
            )
        except RuntimeError as exc:
            raise RuntimeError(f"{self.provider_name} model {self.model} request failed: {exc}") from exc
        return replace(report, model_interpretation=content, model_execution=metadata)


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

        request_config = load_runtime_settings().get("runtime", "llm_request")
        request_payload = {
            "model": self.config.model,
            "temperature": request_config["temperature"],
            "max_tokens": request_config["max_tokens"],
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
        try:
            content, metadata = _request_complete_explanation(
                url=f"{self.config.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                request_payload=request_payload,
                provider_name="DeepSeek",
                request_config=request_config,
                post_json=self._post_json,
            )
        except RuntimeError as exc:
            raise RuntimeError(f"DeepSeek model {self.config.model} request failed: {exc}") from exc
        return replace(report, model_interpretation=content, model_execution=metadata)


def _request_complete_explanation(
    url: str,
    *,
    headers: dict[str, str],
    request_payload: dict[str, Any],
    provider_name: str,
    request_config: dict[str, Any],
    post_json: PostJson,
) -> tuple[str, dict[str, Any]]:
    """Return only a structurally complete explanation, continuing only after truncation."""

    messages = list(request_payload["messages"])
    fragments: list[str] = []
    finish_reasons: list[str | None] = []
    completion_tokens = 0
    maximum_continuations = int(request_config["max_continuations"])

    for attempt in range(maximum_continuations + 1):
        payload = {**request_payload, "messages": messages}
        if attempt:
            payload["max_tokens"] = int(request_config["continuation_max_tokens"])
        response = post_json(url, headers, payload)
        content, finish_reason, used_tokens = _parse_completion(response, provider_name)
        fragments.append(content.strip())
        finish_reasons.append(finish_reason)
        completion_tokens += used_tokens
        combined = "\n".join(fragments).strip()
        if _is_complete(combined, finish_reason):
            rendered = combined.replace(EXPLANATION_COMPLETE_MARKER, "").rstrip()
            return rendered, {
                "complete": True,
                "finish_reason": finish_reason,
                "finish_reasons": finish_reasons,
                "continuations": attempt,
                "completion_tokens": completion_tokens or None,
                "output_characters": len(rendered),
            }
        if attempt >= maximum_continuations:
            break
        messages = [
            *messages,
            {"role": "assistant", "content": combined},
            {
                "role": "user",
                "content": (
                    "上次输出在完成标记前中断。只从断点继续，不要重复已完成内容；"
                    "补齐未完成句子和剩余小节，最后单独输出完成标记 "
                    f"{EXPLANATION_COMPLETE_MARKER}。"
                ),
            },
        ]

    reasons = ", ".join(reason or "missing" for reason in finish_reasons)
    raise RuntimeError(
        f"{provider_name} explanation remained incomplete after "
        f"{maximum_continuations + 1} request(s); finish_reason={reasons}"
    )


def _parse_completion(response: dict[str, Any], provider_name: str) -> tuple[str, str | None, int]:
    try:
        choice = response["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"{provider_name} response did not contain choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(f"{provider_name} returned an empty explanation")
    finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    raw_tokens = usage.get("completion_tokens", 0)
    completion_tokens = int(raw_tokens) if isinstance(raw_tokens, (int, float)) else 0
    return content, str(finish_reason) if finish_reason is not None else None, completion_tokens


def _is_complete(content: str, finish_reason: str | None) -> bool:
    return finish_reason not in {"length", "max_tokens"} and EXPLANATION_COMPLETE_MARKER in content


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
        with urlopen(request, timeout=load_runtime_settings().get("runtime", "llm_network_timeout_seconds")) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Model API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        if is_outbound_access_denied(exc.reason if isinstance(exc.reason, Exception) else exc):
            raise RuntimeError(
                "Outbound network access was denied by this device or network policy. "
                "Check firewall, endpoint security, proxy, or network egress before retrying the model request."
            ) from exc
        raise RuntimeError(f"Unable to reach external model API: {exc.reason}") from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Model API returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Model API returned a non-object response")
    return parsed
