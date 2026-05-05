from __future__ import annotations

import unittest

from pq_bitedu.simulation import (
    bootstrap_demo_network,
    run_double_spend_scenario,
    run_majority_reorg_scenario,
)


class SimulationScenarioTests(unittest.TestCase):
    def test_bootstrap_demo_network_creates_multiple_nodes(self) -> None:
        network, _wallets = bootstrap_demo_network()
        self.assertEqual(set(network.nodes.keys()), {"attacker", "merchant", "honest_1", "honest_2"})
        heights = set(network.best_heights().values())
        self.assertEqual(len(heights), 1)

    def test_double_spend_scenario_runs(self) -> None:
        report = run_double_spend_scenario()
        self.assertTrue(report.success)
        self.assertGreaterEqual(report.merchant_received_on_public_chain, 8)
        self.assertEqual(report.merchant_received_after_reorg, 0)
        self.assertTrue(any(event["event_type"] == "block_broadcast" for event in report.events))

    def test_majority_reorg_scenario_runs(self) -> None:
        report = run_majority_reorg_scenario()
        self.assertTrue(report.success)
        self.assertIn("final_tips", report.extra)
        self.assertEqual(report.extra["shared_tip_count"], 1)


if __name__ == "__main__":
    unittest.main()
