from __future__ import annotations

import os
import unittest

from pq_bitedu.agentic import MinerController, MultiAgentEnvironment, RoundRobinTraderController
from pq_bitedu.agentic.presets import (
    deepseek_market_agent_presets,
    format_presets_for_console,
    mixed_market_agent_presets,
)
from pq_bitedu.config import load_env_file
from pq_bitedu.market_simulation import build_environment, summarize_outcomes


class MarketSimulationSupportTests(unittest.TestCase):
    def test_load_env_file_reads_dotenv(self) -> None:
        loaded = load_env_file()
        self.assertIn("DEEPSEEK_API_KEY", loaded)
        self.assertIn("GEMINI_API_KEY", loaded)
        self.assertEqual(os.environ.get("DEEPSEEK_API_KEY"), loaded["DEEPSEEK_API_KEY"])

    def test_presets_are_identity_only_and_profit_focused(self) -> None:
        presets = deepseek_market_agent_presets()
        mixed_presets = mixed_market_agent_presets()
        self.assertGreaterEqual(len(presets), 3)
        self.assertEqual(len(mixed_presets), 4)
        self.assertEqual(len({preset.name for preset in presets}), len(presets))
        self.assertEqual(len(format_presets_for_console(presets)), len(presets))
        self.assertEqual({preset.role for preset in presets}, {"trader"})
        for preset in presets:
            self.assertIn("收益", preset.objective)
            self.assertIn("挖矿", preset.system_prompt)

    def test_summary_counts_events(self) -> None:
        environment = MultiAgentEnvironment()
        environment.register_agent(
            name="trader_a",
            controller=RoundRobinTraderController(amount=5, fee=1),
            role="trader",
            objective="Trade with peers.",
        )
        environment.register_agent(
            name="miner_1",
            controller=MinerController(),
            role="miner",
            objective="Mine.",
        )
        environment.initialize_chain("miner_1", extra_reward_blocks=1)
        environment.transfer("miner_1", "trader_a", amount=10, fee=1)
        environment.mine("miner_1", coinbase_data="seed")
        summary = summarize_outcomes(environment)
        self.assertGreaterEqual(summary["height"], 0)
        self.assertGreaterEqual(summary["block_events"], 1)
        self.assertGreaterEqual(summary["submitted_transactions"], 1)
        self.assertIn("current_price_yuan", summary)
        self.assertIn("cash_balances_yuan", summary)

    def test_hosted_build_environment_has_two_vendors(self) -> None:
        environment = build_environment()
        roles = {profile.role for profile in environment.agent_profiles()}
        names = {profile.name for profile in environment.agent_profiles()}
        providers = {
            profile.provider.provider for profile in environment.agent_profiles() if profile.provider is not None
        }
        self.assertEqual(roles, {"trader"})
        self.assertNotIn("miner_1", names)
        self.assertTrue(environment.external_budget_is_unlimited())
        self.assertEqual(len(names), 4)
        self.assertEqual(providers, {"deepseek", "gemini"})


if __name__ == "__main__":
    unittest.main()
