from __future__ import annotations

import unittest

from pq_bitedu.agentic import (
    AgentController,
    AgentDecision,
    AgentObservation,
    MinerController,
    MultiAgentEnvironment,
    NoopController,
    RoundRobinTraderController,
    ToolCall,
    default_provider_config,
    provider_summary,
)
from pq_bitedu.agentic.tools import AgentToolbox
from pq_bitedu.dashboard import _build_report_payload


class SubmitTxWhenPossibleController(AgentController):
    def plan_turn(self, observation: AgentObservation) -> AgentDecision:
        if observation.balance >= 2:
            return AgentDecision(
                summary="submit tx",
                tool_calls=(ToolCall(tool_name="send_transaction", arguments={"recipient": "miner", "amount": 1, "fee": 0}),),
            )
        return AgentDecision(summary="idle")


class MineOnlyIfMempoolNonEmptyController(AgentController):
    def plan_turn(self, observation: AgentObservation) -> AgentDecision:
        if observation.mempool_size > 0:
            return AgentDecision(
                summary="mine if mempool non-empty",
                tool_calls=(ToolCall(tool_name="mine_block", arguments={"coinbase_data": "conditional"}),),
            )
        return AgentDecision(summary="wait for mempool")


class FailingController(AgentController):
    def plan_turn(self, observation: AgentObservation) -> AgentDecision:
        raise RuntimeError("temporary provider unavailable")


class MultiAgentEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = MultiAgentEnvironment()
        self.environment.register_agent(
            name="miner",
            controller=MinerController(),
            role="miner",
            objective="Mine blocks.",
            provider=default_provider_config("deepseek", "deepseek-chat"),
        )
        self.environment.register_agent(
            name="alice",
            controller=RoundRobinTraderController(amount=10, fee=1),
            role="trader",
            objective="Trade with visible peers.",
            provider=default_provider_config("gemini", "gemini-2.5-flash"),
        )
        self.environment.register_agent(
            name="bob",
            controller=RoundRobinTraderController(amount=6, fee=1),
            role="trader",
            objective="Trade with visible peers.",
        )
        self.environment.initialize_chain("miner", extra_reward_blocks=1)
        self.environment.transfer("miner", "alice", amount=25, fee=1)
        self.environment.mine("miner", coinbase_data="seed-alice")
        self.environment.transfer("miner", "bob", amount=20, fee=1)
        self.environment.mine("miner", coinbase_data="seed-bob")

    def test_provider_summary_mentions_deepseek_and_gemini(self) -> None:
        summary = provider_summary()
        self.assertIn("deepseek", summary)
        self.assertIn("gemini", summary)

    def test_environment_step_executes_tool_calls(self) -> None:
        before_height = self.environment.blockchain.best_height()
        outcomes = self.environment.step()
        self.assertIn("miner", outcomes)
        self.assertIn("alice", outcomes)
        self.assertGreaterEqual(self.environment.blockchain.best_height(), before_height)
        self.assertGreater(len(self.environment.events), 0)
        self.assertLess(self.environment.cash_balances_yuan["alice"], self.environment.initial_cash_yuan)

    def test_market_buy_updates_cash_and_price_history(self) -> None:
        before_cash = self.environment.cash_balances_yuan["alice"]
        before_price_len = len(self.environment.price_history)
        self.environment.buy_from_market("alice", amount=2)
        self.assertLess(self.environment.cash_balances_yuan["alice"], before_cash)
        self.environment.mine("miner", coinbase_data="settle-market-buy")
        self.environment.step()
        self.assertGreater(len(self.environment.price_history), before_price_len)

    def test_inspect_market_exposes_external_capital_policy(self) -> None:
        self.environment._prepare_external_capital_round()
        toolbox = AgentToolbox(self.environment, "alice")
        result = toolbox.execute(ToolCall(tool_name="inspect_market", arguments={}))
        self.assertTrue(result.ok)
        self.assertIn("current_price_yuan", result.payload)
        self.assertIn("recent_price_history", result.payload)
        self.assertIn("price_change_1_round", result.payload)
        self.assertIn("trend_label", result.payload)
        self.assertIn("external_capital_strategy", result.payload)
        self.assertTrue(result.payload["external_buy_budget_unlimited"])
        self.assertEqual(result.payload["external_max_buy_tokens_per_round"], 100)
        self.assertIn("external_bid_ceiling_yuan", result.payload)
        self.assertIn("external_fill_rule", result.payload)
        self.assertIn("idle_cost_warning", result.payload)

    def test_inspect_wallet_exposes_max_sellable_tokens(self) -> None:
        toolbox = AgentToolbox(self.environment, "alice")
        result = toolbox.execute(ToolCall(tool_name="inspect_wallet", arguments={}))
        self.assertTrue(result.ok)
        self.assertIn("max_sellable_tokens", result.payload)
        self.assertIn("default_token_fee", result.payload)
        self.assertLessEqual(int(result.payload["max_sellable_tokens"]), int(result.payload["balance"]))

    def test_multiple_market_buys_can_coexist_in_same_mempool(self) -> None:
        tx_alice = self.environment.buy_from_market("alice", amount=2)
        tx_bob = self.environment.buy_from_market("bob", amount=2)
        self.assertNotEqual(tx_alice.txid, tx_bob.txid)
        self.assertGreaterEqual(len(self.environment.node.mempool), 2)

    def test_external_capital_can_buy_from_agent_within_tolerance(self) -> None:
        self.environment._prepare_external_capital_round()
        self.environment._planned_external_token_fills[("alice", 0)] = 2
        self.environment._active_tool_execution_key = ("alice", 0)
        before_cash = self.environment.cash_balances_yuan["alice"]
        before_budget = self.environment.external_remaining_budget_yuan
        before_token_capacity = self.environment.external_remaining_token_capacity
        quote_price = round(self.environment.current_price_yuan * 1.01, 2)
        transaction = self.environment.sell_to_market(
            "alice",
            amount=2,
            venue="external_capital",
            quote_price_yuan=quote_price,
        )
        self.environment._active_tool_execution_key = None
        self.assertIsNotNone(transaction.txid)
        self.assertGreater(self.environment.cash_balances_yuan["alice"], before_cash)
        self.assertEqual(self.environment.external_remaining_token_capacity, before_token_capacity - 2)
        self.assertIsNone(before_budget)
        self.assertIsNone(self.environment.external_remaining_budget_yuan)
        self.assertTrue(any(event.event_type == "external_capital_fill" for event in self.environment.recent_events(10)))

    def test_external_capital_prioritizes_lower_quotes_with_token_cap(self) -> None:
        self.environment.external_max_buy_tokens_per_round = 3
        self.environment._prepare_external_capital_round()
        decisions = {
            "alice": AgentDecision(
                summary="sell high",
                tool_calls=(ToolCall(tool_name="sell_tokens", arguments={"amount": 2, "venue": "external_capital", "quote_price_yuan": 12.11}),),
            ),
            "bob": AgentDecision(
                summary="sell low",
                tool_calls=(ToolCall(tool_name="sell_tokens", arguments={"amount": 2, "venue": "external_capital", "quote_price_yuan": 12.01}),),
            ),
            "miner": AgentDecision(summary="idle"),
        }
        self.environment._plan_external_capital_allocations(decisions)
        self.assertEqual(self.environment._planned_external_token_fills.get(("bob", 0)), 2)
        self.assertEqual(self.environment._planned_external_token_fills.get(("alice", 0)), 1)
        review_events = [
            event for event in self.environment.recent_events(20)
            if event.event_type == "external_capital_order_review"
        ]
        self.assertGreaterEqual(len(review_events), 2)
        bob_review = next(event for event in review_events if event.agent_name == "bob")
        alice_review = next(event for event in review_events if event.agent_name == "alice")
        self.assertEqual(bob_review.payload["status"], "fully_selected")
        self.assertEqual(alice_review.payload["status"], "partially_selected")

    def test_external_capital_emits_reason_when_quote_too_high(self) -> None:
        self.environment._prepare_external_capital_round()
        decisions = {
            "alice": AgentDecision(
                summary="sell too high",
                tool_calls=(ToolCall(tool_name="sell_tokens", arguments={"amount": 2, "venue": "external_capital", "quote_price_yuan": 99.0}),),
            ),
            "bob": AgentDecision(summary="idle"),
            "miner": AgentDecision(summary="idle"),
        }
        self.environment._plan_external_capital_allocations(decisions)
        review_events = [
            event for event in self.environment.recent_events(20)
            if event.event_type == "external_capital_order_review" and event.agent_name == "alice"
        ]
        self.assertEqual(review_events[-1].payload["status"], "rejected_price_too_high")

    def test_external_buyback_preserves_market_liquidity_floor(self) -> None:
        self.environment._prepare_external_capital_round()
        self.environment._run_external_buyback()
        self.assertGreaterEqual(
            self.environment.market_pool_balance(),
            self.environment.market_liquidity_floor_tokens,
        )

    def test_external_capital_strategies_adjust_budget(self) -> None:
        dip_env = MultiAgentEnvironment(external_capital_strategy="dip_buyer", external_buy_budget_yuan=600.0)
        dip_env.price_history = [
            {"round": -1, "label": "start", "price": 12.0},
            {"round": 0, "label": "r1", "price": 12.0},
            {"round": 1, "label": "r2", "price": 11.8},
            {"round": 2, "label": "r3", "price": 11.6},
        ]
        dip_env.current_price_yuan = 10.8
        _, dip_budget, _ = dip_env._budget_for_dip_buyer()
        self.assertGreater(dip_budget, dip_env.external_buy_budget_yuan)

        trend_env = MultiAgentEnvironment(external_capital_strategy="trend_follower", external_buy_budget_yuan=600.0)
        trend_env.price_history = [
            {"round": -1, "label": "start", "price": 12.0},
            {"round": 0, "label": "r1", "price": 13.0},
        ]
        trend_env.current_price_yuan = 13.8
        _, trend_budget, _ = trend_env._budget_for_trend_follower()
        self.assertGreater(trend_budget, trend_env.external_buy_budget_yuan)

    def test_run_produces_balances_and_recent_events(self) -> None:
        self.environment.run(rounds=3)
        balances = self.environment.balances()
        self.assertIn("miner", balances)
        self.assertIn("alice", balances)
        self.assertIn("bob", balances)
        self.assertGreater(self.environment.blockchain.best_height(), 0)
        self.assertTrue(any(event.event_type == "block_mined" for event in self.environment.recent_events(limit=20)))

    def test_step_emits_decision_and_tool_events(self) -> None:
        self.environment.step()
        event_types = [event.event_type for event in self.environment.recent_events(limit=40)]
        self.assertIn("agent_decision", event_types)
        self.assertIn("tool_executed", event_types)

    def test_observation_contains_price_history_and_living_cost(self) -> None:
        self.environment.step()
        observation = self.environment.build_observation("alice")
        self.assertGreaterEqual(len(observation.recent_price_history), 2)
        self.assertIn(observation.trend_label, {"up", "down", "flat"})
        self.assertEqual(observation.living_cost_per_round_yuan, self.environment.living_cost_per_round_yuan)
        self.assertIn("agents", observation.initial_state)
        self.assertIn("agents", observation.current_state)
        self.assertIn("round_rule", observation.market_rules)
        self.assertGreaterEqual(len(observation.full_price_history), len(observation.recent_price_history))
        self.assertGreaterEqual(len(observation.full_event_history), len(observation.recent_events))
        self.assertTrue(all(tool.name in {"send_transaction", "buy_tokens", "sell_tokens", "mine_block", "noop"} for tool in observation.available_tools))

    def test_step_is_synchronous_across_agents(self) -> None:
        environment = MultiAgentEnvironment()
        environment.register_agent(
            name="alice",
            controller=SubmitTxWhenPossibleController(),
            role="trader",
            objective="submit",
        )
        environment.register_agent(
            name="miner",
            controller=MineOnlyIfMempoolNonEmptyController(),
            role="trader",
            objective="mine only after seeing mempool",
        )
        environment.initialize_bootstrap_chain(extra_reward_blocks=2)
        environment.bootstrap_transfer("alice", amount=5, fee=1)
        environment._mine_to_pubkey_hash("bootstrap_system", environment.bootstrap_wallet.primary_pubkey_hash, "settle")

        before_height = environment.blockchain.best_height()
        outcomes = environment.step()
        self.assertEqual(outcomes["miner"][0].summary, "wait for mempool")
        self.assertEqual(environment.blockchain.best_height(), before_height)

    def test_plan_failure_does_not_crash_round(self) -> None:
        environment = MultiAgentEnvironment()
        environment.register_agent(
            name="broken",
            controller=FailingController(),
            role="trader",
            objective="fail",
        )
        environment.register_agent(
            name="steady",
            controller=NoopController(),
            role="trader",
            objective="stay steady",
        )
        outcomes = environment.step()
        self.assertIn("broken", outcomes)
        self.assertIn("steady", outcomes)
        self.assertIn("跳过", outcomes["broken"][0].summary)
        event_types = [event.event_type for event in environment.recent_events(20)]
        self.assertIn("agent_plan_failed", event_types)

    def test_dashboard_profit_uses_total_assets_minus_initial_cash(self) -> None:
        initial_balances = self.environment.balances()
        initial_cash = dict(self.environment.cash_balances_yuan)
        report = _build_report_payload(
            environment=self.environment,
            mode="scripted",
            model="test",
            rounds=0,
            initial_balances=initial_balances,
            initial_cash_balances=initial_cash,
            price_history=self.environment.price_history,
            round_history=self.environment.round_history,
        )
        alice = next(agent for agent in report["agents"] if agent["name"] == "alice")
        self.assertEqual(
            alice["estimated_pnl_yuan"],
            round(float(alice["net_worth_yuan"]) - float(self.environment.initial_cash_yuan), 2),
        )


if __name__ == "__main__":
    unittest.main()
