"""Run a prompt-driven hosted multi-agent market simulation."""

from __future__ import annotations

from typing import Dict, List

from .agentic import HostedAgentController, MultiAgentEnvironment, build_hosted_adapter
from .agentic.presets import format_presets_for_console, mixed_market_agent_presets
from .config import load_env_file


def build_environment(
    model: str = "deepseek-v4-flash",
    gemini_model: str = "gemini-2.5-flash",
    external_capital_strategy: str = "strategy_mix",
) -> MultiAgentEnvironment:
    load_env_file()
    environment = MultiAgentEnvironment(
        recent_event_window=40,
        external_capital_strategy=external_capital_strategy,
    )
    preset_specs = mixed_market_agent_presets()

    for provider_name, default_model, preset in preset_specs:
        chosen_model = model if provider_name == "deepseek" else gemini_model
        if not chosen_model:
            chosen_model = default_model
        provider = preset.provider_config(provider_name, chosen_model)
        environment.register_agent(
            name=preset.name,
            controller=HostedAgentController(build_hosted_adapter(provider)),
            role=preset.role,
            objective=preset.objective,
            system_prompt=preset.system_prompt,
            provider=provider,
            max_tool_calls_per_turn=preset.max_tool_calls_per_turn,
        )

    environment.initialize_bootstrap_chain(extra_reward_blocks=3)

    for _provider_name, _default_model, preset in preset_specs:
        environment.bootstrap_transfer(preset.name, amount=preset.bootstrap_balance, fee=1)
        environment._mine_to_pubkey_hash(
            miner_label="bootstrap_system",
            recipient_pubkey_hash=environment.bootstrap_wallet.primary_pubkey_hash,
            coinbase_data="bootstrap-{0}".format(preset.name),
        )

    return environment


def summarize_outcomes(environment: MultiAgentEnvironment) -> Dict[str, object]:
    block_count = sum(1 for event in environment.events if event.event_type == "block_mined")
    tx_count = sum(
        1
        for event in environment.events
        if event.event_type in {"transaction_submitted", "market_buy", "market_sell"}
    )
    return {
        "height": environment.blockchain.best_height(),
        "balances": environment.balances(),
        "cash_balances_yuan": {name: round(balance, 2) for name, balance in environment.cash_balances_yuan.items()},
        "current_price_yuan": environment.current_price_yuan,
        "block_events": block_count,
        "submitted_transactions": tx_count,
        "recent_events": [event.to_dict() for event in environment.recent_events(limit=12)],
    }


def main(rounds: int = 3) -> None:
    preset_specs = mixed_market_agent_presets()
    presets = [item[2] for item in preset_specs]
    environment = build_environment()
    print("agent_presets:")
    for line in format_presets_for_console(presets):
        print("-", line)

    history: List[Dict[str, object]] = []
    for round_index in range(rounds):
        environment.step()
        history.append(
            {
                "round": round_index,
                "height": environment.blockchain.best_height(),
                "balances": environment.balances(),
                "cash_balances_yuan": {
                    name: round(balance, 2) for name, balance in environment.cash_balances_yuan.items()
                },
                "price_yuan": environment.current_price_yuan,
                "mempool_size": len(environment.node.mempool),
            }
        )

    print("round_history:")
    for entry in history:
        print("-", entry)

    summary = summarize_outcomes(environment)
    print("summary:", {key: value for key, value in summary.items() if key != "recent_events"})
    print("recent_events:")
    for event in summary["recent_events"]:
        print("-", event)


if __name__ == "__main__":
    main()
