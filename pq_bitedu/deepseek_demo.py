"""Hosted DeepSeek smoke-test for the multi-agent environment."""

from __future__ import annotations

from .agentic import HostedAgentController, MinerController, MultiAgentEnvironment, build_hosted_adapter, default_provider_config


def build_environment() -> MultiAgentEnvironment:
    environment = MultiAgentEnvironment()
    miner_profile = default_provider_config("deepseek", "deepseek-v4-flash")
    trader_profile = default_provider_config("deepseek", "deepseek-v4-flash")
    trader_profile = trader_profile.__class__(**{**trader_profile.__dict__, "temperature": 0.0})

    environment.register_agent(
        name="miner_1",
        controller=MinerController(),
        role="miner",
        objective="Mine blocks and collect rewards.",
        provider=miner_profile,
    )
    environment.register_agent(
        name="deepseek_trader",
        controller=HostedAgentController(build_hosted_adapter(trader_profile)),
        role="trader",
        objective=(
            "Inspect the environment, then if you have enough balance send a small transfer "
            "to miner_1; otherwise stay idle."
        ),
        system_prompt=(
            "Prefer simple, valid tool calls. If your balance is below 6, do not attempt a transfer."
        ),
        provider=trader_profile,
        max_tool_calls_per_turn=4,
    )
    environment.initialize_chain("miner_1", extra_reward_blocks=2)
    environment.transfer("miner_1", "deepseek_trader", amount=20, fee=1)
    environment.mine("miner_1", coinbase_data="seed-deepseek")
    return environment


def main() -> None:
    environment = build_environment()
    hosted_runtime = environment._runtimes["deepseek_trader"]
    hosted_controller = hosted_runtime.controller
    adapter = hosted_controller.adapter
    print("ping:", adapter.ping())
    decision, results = environment.step_agent("deepseek_trader")
    print("decision:", decision.to_dict())
    print("results:", [result.to_dict() for result in results])
    print("balances_before_mining:", environment.balances())
    if environment.node.mempool:
        block = environment.mine("miner_1", coinbase_data="deepseek-followup")
        print("followup_block:", {"block_hash": block.block_hash, "height": block.header.height})
    print("balances_after_mining:", environment.balances())


if __name__ == "__main__":
    main()
