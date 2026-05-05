from __future__ import annotations

import unittest

from pq_bitedu.live_dashboard import LiveSimulationRunner, build_market_quotes


class LiveDashboardTests(unittest.TestCase):
    def test_quote_generation_has_bid_ask(self) -> None:
        runner = LiveSimulationRunner(mode="scripted", model="deepseek-v4-flash", interval_sec=1.0, max_rounds=1)
        quotes = build_market_quotes(runner.environment, current_price=12.0, round_index=0)
        self.assertGreaterEqual(len(quotes), 3)
        for quote in quotes:
            self.assertLessEqual(float(quote["bid"]), float(quote["ask"]))
            self.assertIn("agent", quote)
            self.assertIn("stance", quote)

    def test_snapshot_updates_after_step(self) -> None:
        runner = LiveSimulationRunner(mode="scripted", model="deepseek-v4-flash", interval_sec=1.0, max_rounds=2)
        before = runner.snapshot()
        self.assertEqual(before["live"]["current_round"], -1)
        advanced = runner.step_once()
        self.assertTrue(advanced)
        after = runner.snapshot()
        self.assertEqual(after["live"]["current_round"], 0)
        self.assertIn("current_quotes", after)
        self.assertGreaterEqual(len(after["current_quotes"]), 1)
        self.assertIn("economics", after)


if __name__ == "__main__":
    unittest.main()
