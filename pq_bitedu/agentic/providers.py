"""Provider adapters for hosted multi-agent deployments."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
import os
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from urllib import error, parse, request

from ..config import load_env_file
from .protocol import (
    AgentController,
    AgentDecision,
    AgentObservation,
    ProviderConfig,
    ToolCall,
    ToolResult,
)


@dataclass(frozen=True)
class ProviderDescriptor:
    name: str
    transport: str
    default_api_key_env: str
    default_base_url: str | None = None
    notes: str = ""

    def build_config(self, model: str) -> ProviderConfig:
        return ProviderConfig(
            provider=self.name,
            model=model,
            api_key_env=self.default_api_key_env,
            base_url=self.default_base_url,
            metadata={"notes": self.notes},
        )


PROVIDER_DESCRIPTORS: Dict[str, ProviderDescriptor] = {
    "deepseek": ProviderDescriptor(
        name="deepseek",
        transport="openai-compatible",
        default_api_key_env="DEEPSEEK_API_KEY",
        default_base_url="https://api.deepseek.com",
        notes="OpenAI-compatible chat completions endpoint.",
    ),
    "gemini": ProviderDescriptor(
        name="gemini",
        transport="google-generative-language",
        default_api_key_env="GEMINI_API_KEY",
        default_base_url="https://generativelanguage.googleapis.com",
        notes="Gemini generateContent endpoint with function declarations.",
    ),
}


def default_provider_config(provider: str, model: str) -> ProviderConfig:
    normalized = provider.lower()
    if normalized not in PROVIDER_DESCRIPTORS:
        raise KeyError("unknown provider: {0}".format(provider))
    return PROVIDER_DESCRIPTORS[normalized].build_config(model)


class HostedModelAdapter(ABC):
    @abstractmethod
    def complete_turn(
        self,
        observation: AgentObservation,
        previous_results: Sequence[ToolResult],
    ) -> AgentDecision:
        raise NotImplementedError

    def ping(self) -> Mapping[str, Any]:
        return {"ok": True}


class PromptBuildingMixin:
    @staticmethod
    def build_system_prompt(observation: AgentObservation) -> str:
        profile = observation.profile
        return (
            "你正在参加 PQ-BitEdu 的多智能体链上市场模拟。\n"
            "你的任务是在可用工具范围内尽可能提高自己的总资产与利润。\n"
            "你会直接收到完整规则、初始状态、当前状态、全局历史价格、全局事件历史和其他智能体状态。\n"
            "本回合采用同步决策：所有智能体都会先提交自己的方案，等全部提交后才统一执行。\n"
            "你不需要额外分析步骤，请直接基于给定信息提交本回合行动方案。\n"
            "所有自然语言输出都必须使用简体中文，包括决策摘要、行动理由和对结果的解释。\n"
            "不要输出英文思考；必要术语可保留 PQC、API、JSON、noop。\n"
            "你的身份：{0}\n"
            "你的角色：{1}\n"
            "你的目标：{2}\n"
            "{3}"
        ).format(
            profile.name,
            profile.role,
            profile.objective,
            profile.system_prompt.strip(),
        )

    @staticmethod
    def build_user_prompt(
        observation: AgentObservation,
        previous_results: Sequence[ToolResult],
    ) -> str:
        payload = {
            "observation": observation.to_dict(),
            "previous_tool_results": [result.to_dict() for result in previous_results],
        }
        return (
            "下面是你本回合可见的完整数据。请直接基于这些数据，用中文给出你的本回合方案。\n"
            "方案可以包含买入、卖出、挖矿、转账或 noop；请自行判断数量、报价和成交场所。\n"
            "在所有智能体提交方案之前，不会有任何动作先执行。\n"
            "观察数据与历史工具结果如下（JSON）：\n"
            "{0}"
        ).format(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


class UnconfiguredHostedModelAdapter(HostedModelAdapter):
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def complete_turn(
        self,
        observation: AgentObservation,
        previous_results: Sequence[ToolResult],
    ) -> AgentDecision:
        raise RuntimeError(
            "Hosted provider '{0}' is not implemented yet.".format(self.config.provider)
        )


class OpenAICompatibleChatAdapter(PromptBuildingMixin, HostedModelAdapter):
    def __init__(self, config: ProviderConfig, timeout_seconds: float = 60.0) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds

    def ping(self) -> Mapping[str, Any]:
        response = self._request("/models", payload=None, method="GET")
        models = response.get("data", [])
        model_ids = [item.get("id") for item in models if isinstance(item, dict)]
        return {
            "ok": True,
            "provider": self.config.provider,
            "model": self.config.model,
            "available_models": model_ids[:10],
        }

    def complete_turn(
        self,
        observation: AgentObservation,
        previous_results: Sequence[ToolResult],
    ) -> AgentDecision:
        use_strict = bool(self.config.metadata.get("strict_tools")) or (
            (self.config.base_url or "").rstrip("/").endswith("/beta")
        )
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.build_system_prompt(observation)},
                {"role": "user", "content": self.build_user_prompt(observation, previous_results)},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.arguments,
                        **({"strict": True} if use_strict else {}),
                    },
                }
                for tool in observation.available_tools
            ],
            "tool_choice": "auto" if observation.available_tools else "none",
            "thinking": {"type": "disabled"},
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_output_tokens,
        }
        response = self._request("/chat/completions", payload=payload, method="POST")
        choice = response["choices"][0]
        message = choice["message"]
        summary = (message.get("content") or "").strip()
        tool_calls = []
        for raw_call in message.get("tool_calls") or []:
            function_payload = raw_call.get("function", {})
            arguments_text = function_payload.get("arguments", "{}")
            tool_calls.append(
                ToolCall(
                    tool_name=function_payload["name"],
                    arguments=json.loads(arguments_text) if arguments_text else {},
                )
            )
        return AgentDecision(summary=summary, tool_calls=tuple(tool_calls))

    def _request(
        self,
        path: str,
        payload: Optional[Mapping[str, Any]],
        method: str,
    ) -> Mapping[str, Any]:
        load_env_file()
        api_key = os.getenv(self.config.api_key_env)
        if not api_key:
            raise RuntimeError(
                "missing API key environment variable: {0}".format(self.config.api_key_env)
            )
        base_url = (self.config.base_url or "").rstrip("/")
        endpoint = base_url + path
        body = None if payload is None else json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers = {
            "Authorization": "Bearer {0}".format(api_key),
            "Content-Type": "application/json",
        }
        req = request.Request(endpoint, data=body, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            raw_error = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                "provider HTTP error {0}: {1}".format(exc.code, raw_error)
            ) from exc
        except error.URLError as exc:
            raise RuntimeError("provider connection failed: {0}".format(exc.reason)) from exc
        return json.loads(raw)


class GeminiGenerateContentAdapter(PromptBuildingMixin, HostedModelAdapter):
    def __init__(self, config: ProviderConfig, timeout_seconds: float = 60.0) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds

    def ping(self) -> Mapping[str, Any]:
        response = self._request(
            "/v1beta/models?key={0}".format(self._api_key()),
            payload=None,
            method="GET",
        )
        models = response.get("models", [])
        return {
            "ok": True,
            "provider": self.config.provider,
            "model": self.config.model,
            "available_models": [item.get("name") for item in models[:10] if isinstance(item, dict)],
        }

    def complete_turn(
        self,
        observation: AgentObservation,
        previous_results: Sequence[ToolResult],
    ) -> AgentDecision:
        endpoint = "/v1beta/models/{0}:generateContent?key={1}".format(
            parse.quote(self.config.model, safe=""),
            parse.quote(self._api_key(), safe=""),
        )
        payload: Dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": self.build_system_prompt(observation)}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": self.build_user_prompt(observation, previous_results),
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": self.config.temperature,
                "maxOutputTokens": self.config.max_output_tokens,
            },
        }
        if observation.available_tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": self._sanitize_parameters(tool.arguments),
                        }
                        for tool in observation.available_tools
                    ]
                }
            ]
            payload["toolConfig"] = {
                "functionCallingConfig": {
                    "mode": "AUTO",
                }
            }
        response = self._request(endpoint, payload=payload, method="POST")
        candidates = response.get("candidates", [])
        if not candidates:
            raise RuntimeError("gemini returned no candidates")
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        summary_parts = []
        tool_calls = []
        for part in parts:
            if "text" in part and str(part["text"]).strip():
                summary_parts.append(str(part["text"]).strip())
            if "functionCall" in part:
                function_call = part["functionCall"]
                tool_calls.append(
                    ToolCall(
                        tool_name=str(function_call["name"]),
                        arguments=dict(function_call.get("args", {})),
                    )
                )
        return AgentDecision(summary=" ".join(summary_parts).strip(), tool_calls=tuple(tool_calls))

    def _api_key(self) -> str:
        load_env_file()
        api_key = os.getenv(self.config.api_key_env)
        if not api_key:
            raise RuntimeError(
                "missing API key environment variable: {0}".format(self.config.api_key_env)
            )
        return api_key

    def _request(
        self,
        path: str,
        payload: Optional[Mapping[str, Any]],
        method: str,
    ) -> Mapping[str, Any]:
        base_url = (self.config.base_url or "").rstrip("/")
        endpoint = base_url + path
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        req = request.Request(endpoint, data=body, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            raw_error = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                "provider HTTP error {0}: {1}".format(exc.code, raw_error)
            ) from exc
        except error.URLError as exc:
            raise RuntimeError("provider connection failed: {0}".format(exc.reason)) from exc
        return json.loads(raw)

    def _sanitize_parameters(self, schema: Mapping[str, Any]) -> Dict[str, Any]:
        allowed = {"type", "properties", "required", "description", "enum", "items"}
        sanitized: Dict[str, Any] = {}
        for key, value in schema.items():
            if key not in allowed:
                continue
            if key == "properties" and isinstance(value, Mapping):
                sanitized[key] = {
                    str(prop_name): self._sanitize_parameters(prop_schema)
                    for prop_name, prop_schema in value.items()
                    if isinstance(prop_schema, Mapping)
                }
            elif key == "items" and isinstance(value, Mapping):
                sanitized[key] = self._sanitize_parameters(value)
            else:
                sanitized[key] = value
        return sanitized


class HostedAgentController(AgentController):
    def __init__(self, adapter: HostedModelAdapter) -> None:
        self.adapter = adapter

    def plan_turn(self, observation: AgentObservation) -> AgentDecision:
        return self.adapter.complete_turn(observation, previous_results=())

    def plan_turn_interactive(
        self,
        observation: AgentObservation,
        toolbox: Any,
        max_tool_calls: int,
    ) -> Tuple[AgentDecision, Tuple[ToolResult, ...]]:
        current_observation = observation
        summary_parts = []
        executed_tool_calls = []
        results = []
        remaining = max_tool_calls
        while remaining > 0:
            decision = self.adapter.complete_turn(
                current_observation,
                previous_results=tuple(results),
            )
            if decision.summary:
                summary_parts.append(decision.summary)
            if not decision.tool_calls:
                break
            any_executed = False
            for tool_call in decision.tool_calls[:remaining]:
                executed_tool_calls.append(tool_call)
                results.append(toolbox.execute(tool_call))
                remaining -= 1
                any_executed = True
                if remaining <= 0:
                    break
            if not any_executed:
                break
            current_observation = toolbox.environment.build_observation(toolbox.agent_name)
        return (
            AgentDecision(
                summary=" | ".join(part for part in summary_parts if part),
                tool_calls=tuple(executed_tool_calls),
            ),
            tuple(results),
        )


def build_hosted_adapter(config: ProviderConfig) -> HostedModelAdapter:
    provider = config.provider.lower()
    if provider == "deepseek":
        return OpenAICompatibleChatAdapter(config)
    if provider == "gemini":
        return GeminiGenerateContentAdapter(config)
    return UnconfiguredHostedModelAdapter(config)


def provider_summary() -> Mapping[str, Mapping[str, str | None]]:
    return {
        name: {
            "transport": descriptor.transport,
            "default_api_key_env": descriptor.default_api_key_env,
            "default_base_url": descriptor.default_base_url,
            "notes": descriptor.notes,
        }
        for name, descriptor in PROVIDER_DESCRIPTORS.items()
    }
