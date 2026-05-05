"""Runnable demo for the local multi-agent simulation layer."""

from __future__ import annotations

from .agentic import MinerController, MultiAgentEnvironment, RoundRobinTraderController, default_provider_config


def main() -> None:
    environment = MultiAgentEnvironment()
    environment.register_agent(
        name="miner_1",
        controller=MinerController(),
        role="miner",
        objective="Mine blocks and collect rewards.",
        provider=default_provider_config("deepseek", "deepseek-chat"),
    )
    environment.register_agent(
        name="trader_a",
        controller=RoundRobinTraderController(amount=12, fee=1),
        role="trader",
        objective="Receive mining income and circulate the token.",
        provider=default_provider_config("deepseek", "deepseek-chat"),
    )
    environment.register_agent(
        name="trader_b",
        controller=RoundRobinTraderController(amount=7, fee=1),
        role="trader",
        objective="Trade with peers whenever balance allows.",
        provider=default_provider_config("gemini", "gemini-2.5-flash"),
    )

    environment.initialize_chain("miner_1", extra_reward_blocks=2)
    environment.transfer("miner_1", "trader_a", amount=40, fee=1)
    environment.mine("miner_1", coinbase_data="seed-distribution")
    environment.transfer("miner_1", "trader_b", amount=30, fee=1)
    environment.mine("miner_1", coinbase_data="seed-distribution-2")

    environment.run(rounds=4)

    print("height:", environment.blockchain.best_height())
    print("balances:", environment.balances())
    print("providers:", {profile.name: None if profile.provider is None else profile.provider.provider for profile in environment.agent_profiles()})
    print("recent events:")
    for event in environment.recent_events(limit=8):
        print("-", event.event_type, event.agent_name, event.payload)


if __name__ == "__main__":
    main()
