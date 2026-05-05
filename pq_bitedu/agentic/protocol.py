"""Protocols and dataclasses for multi-agent simulation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


JsonDict = Dict[str, Any]


@dataclass(frozen=True)
class ProviderConfig:
    """Future-facing provider configuration for hosted LLM agents."""

    provider: str
    model: str
    api_key_env: str
    base_url: Optional[str] = None
    temperature: float = 0.2
    max_output_tokens: int = 2048
    supports_tool_calling: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "provider": self.provider,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "supports_tool_calling": self.supports_tool_calling,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AgentProfile:
    """Static metadata about an agent."""

    name: str
    role: str
    objective: str
    system_prompt: str = ""
    provider: Optional[ProviderConfig] = None
    max_tool_calls_per_turn: int = 2

    def to_dict(self) -> JsonDict:
        return {
            "name": self.name,
            "role": self.role,
            "objective": self.objective,
            "system_prompt": self.system_prompt,
            "provider": None if self.provider is None else self.provider.to_dict(),
            "max_tool_calls_per_turn": self.max_tool_calls_per_turn,
        }


@dataclass(frozen=True)
class AgentSnapshot:
    """Public state visible to all agents."""

    name: str
    role: str
    balance: int
    fiat_balance_yuan: float
    net_worth_yuan: float
    bankrupt: bool
    primary_pubkey_hash: str

    def to_dict(self) -> JsonDict:
        return {
            "name": self.name,
            "role": self.role,
            "balance": self.balance,
            "fiat_balance_yuan": self.fiat_balance_yuan,
            "net_worth_yuan": self.net_worth_yuan,
            "bankrupt": self.bankrupt,
            "primary_pubkey_hash": self.primary_pubkey_hash,
        }


@dataclass(frozen=True)
class SimulationEvent:
    """An append-only event emitted by the environment."""

    tick: int
    event_type: str
    agent_name: Optional[str]
    payload: JsonDict

    def to_dict(self) -> JsonDict:
        return {
            "tick": self.tick,
            "event_type": self.event_type,
            "agent_name": self.agent_name,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class ToolSpec:
    """Description of a callable agent tool."""

    name: str
    description: str
    arguments: JsonDict

    def to_dict(self) -> JsonDict:
        return {
            "name": self.name,
            "description": self.description,
            "arguments": self.arguments,
        }


@dataclass(frozen=True)
class ToolCall:
    """A requested tool invocation."""

    tool_name: str
    arguments: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {"tool_name": self.tool_name, "arguments": dict(self.arguments)}


@dataclass(frozen=True)
class ToolResult:
    """Result of a tool invocation."""

    tool_name: str
    ok: bool
    payload: JsonDict
    error: Optional[str] = None

    def to_dict(self) -> JsonDict:
        return {
            "tool_name": self.tool_name,
            "ok": self.ok,
            "payload": self.payload,
            "error": self.error,
        }


@dataclass(frozen=True)
class AgentObservation:
    """The state an agent sees at the start of a turn."""

    tick: int
    profile: AgentProfile
    balance: int
    fiat_balance_yuan: float
    net_worth_yuan: float
    current_price_yuan: float
    recent_price_history: Tuple[JsonDict, ...]
    price_change_1_round: float
    price_change_5_rounds: float
    trend_label: str
    living_cost_per_round_yuan: float
    bankrupt: bool
    mempool_size: int
    chain_height: int
    best_tip: Optional[str]
    visible_agents: Tuple[AgentSnapshot, ...]
    recent_events: Tuple[SimulationEvent, ...]
    initial_state: JsonDict
    current_state: JsonDict
    full_price_history: Tuple[JsonDict, ...]
    round_history: Tuple[JsonDict, ...]
    full_event_history: Tuple[JsonDict, ...]
    market_rules: JsonDict
    available_tools: Tuple[ToolSpec, ...]

    def to_dict(self) -> JsonDict:
        return {
            "tick": self.tick,
            "profile": self.profile.to_dict(),
            "balance": self.balance,
            "fiat_balance_yuan": self.fiat_balance_yuan,
            "net_worth_yuan": self.net_worth_yuan,
            "current_price_yuan": self.current_price_yuan,
            "recent_price_history": list(self.recent_price_history),
            "price_change_1_round": self.price_change_1_round,
            "price_change_5_rounds": self.price_change_5_rounds,
            "trend_label": self.trend_label,
            "living_cost_per_round_yuan": self.living_cost_per_round_yuan,
            "bankrupt": self.bankrupt,
            "mempool_size": self.mempool_size,
            "chain_height": self.chain_height,
            "best_tip": self.best_tip,
            "visible_agents": [snapshot.to_dict() for snapshot in self.visible_agents],
            "recent_events": [event.to_dict() for event in self.recent_events],
            "initial_state": dict(self.initial_state),
            "current_state": dict(self.current_state),
            "full_price_history": list(self.full_price_history),
            "round_history": list(self.round_history),
            "full_event_history": list(self.full_event_history),
            "market_rules": dict(self.market_rules),
            "available_tools": [tool.to_dict() for tool in self.available_tools],
        }


@dataclass(frozen=True)
class AgentDecision:
    """An agent's chosen actions for one turn."""

    summary: str = ""
    tool_calls: Tuple[ToolCall, ...] = field(default_factory=tuple)

    def to_dict(self) -> JsonDict:
        return {
            "summary": self.summary,
            "tool_calls": [tool_call.to_dict() for tool_call in self.tool_calls],
        }


class AgentController(ABC):
    """Decision maker for an agent turn."""

    @abstractmethod
    def plan_turn(self, observation: AgentObservation) -> AgentDecision:
        raise NotImplementedError
