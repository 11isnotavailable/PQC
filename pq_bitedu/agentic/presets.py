"""Prompt presets and canned scenario metadata for hosted simulations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, List

from .protocol import ProviderConfig
from .providers import default_provider_config


@dataclass(frozen=True)
class HostedAgentPreset:
    name: str
    role: str
    objective: str
    system_prompt: str
    bootstrap_balance: int
    temperature: float = 0.0
    max_tool_calls_per_turn: int = 4

    def provider_config(self, provider: str, model: str) -> ProviderConfig:
        return replace(
            default_provider_config(provider, model),
            temperature=self.temperature,
        )


def _base_system_prompt(identity: str) -> str:
    return (
        "你的身份是 {0}。\n"
        "你的唯一目标：在避免破产的前提下，最大化以人民币计的总收益和总净资产。\n"
        "你会直接看到完整规则、全局价格历史、所有智能体状态、外部资本买入规则，以及上一轮发生的关键事件。\n"
        "你可以自由决定买入、卖出、挖矿、转账或观望。\n"
        "如果选择卖出，请自己决定卖多少、报多少价；如果选择买入，也请自己判断仓位。\n"
        "任何智能体都可以挖矿，挖矿不是专属角色。\n"
        "就算完全不投资，每回合也会扣除生活成本，所以你需要主动考虑收益机会。\n"
        "外部资本会在每轮所有卖单中按报价从低到高优先买入，但每轮最多只买 100 枚。\n"
        "如果你的报价太高，或者额度被更低报价的卖单抢走，你会在下一轮从事件历史里看到明确原因。\n"
        "请始终用中文输出你的决策摘要。"
    ).format(identity)


def deepseek_market_agent_presets() -> List[HostedAgentPreset]:
    return [
        HostedAgentPreset(
            name="maker_mia",
            role="trader",
            objective="最大化以人民币计的总收益和总净资产。",
            system_prompt=_base_system_prompt("maker_mia"),
            bootstrap_balance=28,
        ),
        HostedAgentPreset(
            name="holder_han",
            role="trader",
            objective="最大化以人民币计的总收益和总净资产。",
            system_prompt=_base_system_prompt("holder_han"),
            bootstrap_balance=26,
        ),
        HostedAgentPreset(
            name="promoter_pia",
            role="trader",
            objective="最大化以人民币计的总收益和总净资产。",
            system_prompt=_base_system_prompt("promoter_pia"),
            bootstrap_balance=24,
        ),
    ]


def mixed_market_agent_presets() -> List[tuple[str, str, HostedAgentPreset]]:
    return [
        (
            "deepseek",
            "deepseek-v4-flash",
            HostedAgentPreset(
                name="deepseek_1",
                role="trader",
                objective="最大化以人民币计的总收益和总净资产。",
                system_prompt=_base_system_prompt("deepseek_1"),
                bootstrap_balance=28,
            ),
        ),
        (
            "deepseek",
            "deepseek-v4-flash",
            HostedAgentPreset(
                name="deepseek_2",
                role="trader",
                objective="最大化以人民币计的总收益和总净资产。",
                system_prompt=_base_system_prompt("deepseek_2"),
                bootstrap_balance=26,
            ),
        ),
        (
            "gemini",
            "gemini-2.5-flash",
            HostedAgentPreset(
                name="gemini_1",
                role="trader",
                objective="最大化以人民币计的总收益和总净资产。",
                system_prompt=_base_system_prompt("gemini_1"),
                bootstrap_balance=28,
            ),
        ),
        (
            "gemini",
            "gemini-2.5-flash",
            HostedAgentPreset(
                name="gemini_2",
                role="trader",
                objective="最大化以人民币计的总收益和总净资产。",
                system_prompt=_base_system_prompt("gemini_2"),
                bootstrap_balance=26,
            ),
        ),
    ]


def format_presets_for_console(presets: Iterable[HostedAgentPreset]) -> List[str]:
    return [
        "{0} [{1}] bootstrap={2} objective={3}".format(
            preset.name,
            preset.role,
            preset.bootstrap_balance,
            preset.objective,
        )
        for preset in presets
    ]
