"""Multi-agent simulation primitives for PQ-BitEdu."""

from .environment import MultiAgentEnvironment
from .presets import deepseek_market_agent_presets, format_presets_for_console, mixed_market_agent_presets
from .protocol import (
    AgentController,
    AgentDecision,
    AgentObservation,
    AgentProfile,
    AgentSnapshot,
    ProviderConfig,
    SimulationEvent,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from .providers import (
    GeminiGenerateContentAdapter,
    HostedAgentController,
    HostedModelAdapter,
    OpenAICompatibleChatAdapter,
    UnconfiguredHostedModelAdapter,
    build_hosted_adapter,
    default_provider_config,
    provider_summary,
)
from .scripted import CompositeController, MinerController, NoopController, RoundRobinTraderController

__all__ = [
    "AgentController",
    "AgentDecision",
    "AgentObservation",
    "AgentProfile",
    "AgentSnapshot",
    "CompositeController",
    "deepseek_market_agent_presets",
    "format_presets_for_console",
    "GeminiGenerateContentAdapter",
    "HostedAgentController",
    "HostedModelAdapter",
    "MinerController",
    "MultiAgentEnvironment",
    "mixed_market_agent_presets",
    "NoopController",
    "OpenAICompatibleChatAdapter",
    "ProviderConfig",
    "RoundRobinTraderController",
    "SimulationEvent",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "UnconfiguredHostedModelAdapter",
    "build_hosted_adapter",
    "default_provider_config",
    "provider_summary",
]
