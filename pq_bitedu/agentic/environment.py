"""Local multi-agent simulation environment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..core.blockchain import Blockchain
from ..core.models import Block, Transaction, TxOutput
from ..core.wallet import Wallet
from ..node import Node
from ..core.validation import apply_transaction, validate_transaction
from .protocol import (
    AgentController,
    AgentDecision,
    AgentObservation,
    AgentProfile,
    AgentSnapshot,
    SimulationEvent,
    ToolResult,
)
from .tools import AgentToolbox, resolve_agent_recipient


@dataclass
class AgentRuntime:
    profile: AgentProfile
    controller: AgentController
    wallet: Wallet


class MultiAgentEnvironment:
    """Single-process sandbox for blockchain-native multi-agent experiments."""

    def __init__(
        self,
        blockchain: Optional[Blockchain] = None,
        node: Optional[Node] = None,
        recent_event_window: int = 12,
        initial_cash_yuan: float = 10000.0,
        living_cost_per_round_yuan: float = 100.0,
        bankruptcy_floor_yuan: float = -10000.0,
        starting_price_yuan: float = 12.0,
        external_buy_budget_yuan: Optional[float] = None,
        external_capital_strategy: str = "strategy_mix",
        initial_market_fiat_reserve_yuan: float = 50000.0,
        market_liquidity_tokens: int = 160,
        market_liquidity_floor_tokens: int = 40,
        external_price_tolerance_ratio: float = 0.01,
        external_max_buy_tokens_per_round: int = 100,
    ) -> None:
        self.blockchain = blockchain or Blockchain()
        self.node = node or Node(self.blockchain)
        self.recent_event_window = recent_event_window
        self.initial_cash_yuan = initial_cash_yuan
        self.living_cost_per_round_yuan = living_cost_per_round_yuan
        self.bankruptcy_floor_yuan = bankruptcy_floor_yuan
        self.current_price_yuan = starting_price_yuan
        self.external_buy_budget_yuan = external_buy_budget_yuan
        self.external_capital_strategy = external_capital_strategy
        self.external_price_tolerance_ratio = external_price_tolerance_ratio
        self.external_max_buy_tokens_per_round = external_max_buy_tokens_per_round
        self.market_fiat_reserve_yuan = initial_market_fiat_reserve_yuan
        self.market_liquidity_tokens = market_liquidity_tokens
        self.market_liquidity_floor_tokens = market_liquidity_floor_tokens
        self.external_current_round_budget_yuan: Optional[float] = None
        self.external_remaining_budget_yuan: Optional[float] = None
        self.external_remaining_token_capacity: int = self.external_max_buy_tokens_per_round
        self.external_budget_strategy_label = external_capital_strategy
        self.external_budget_reason = ""
        self._planned_external_token_fills: Dict[Tuple[str, int], int] = {}
        self._active_tool_execution_key: Optional[Tuple[str, int]] = None
        self.tick = 0
        self._runtime_order: List[str] = []
        self._runtimes: Dict[str, AgentRuntime] = {}
        self.wallets: Dict[str, Wallet] = {}
        self.events: List[SimulationEvent] = []
        self.cash_balances_yuan: Dict[str, float] = {}
        self.bankrupt_agents: set[str] = set()
        self.price_history: List[Dict[str, object]] = [
            {"round": -1, "label": "启动", "price": self.current_price_yuan}
        ]
        self.round_history: List[Dict[str, object]] = []
        self.initial_state_snapshot: Optional[Dict[str, object]] = None
        self.market_wallet = Wallet("market_pool", signature_schemes=self.blockchain.signature_schemes)
        self.bootstrap_wallet = Wallet("bootstrap_system", signature_schemes=self.blockchain.signature_schemes)
        self.external_sink_wallet = Wallet(
            "external_sink",
            signature_schemes=self.blockchain.signature_schemes,
        )

    def register_agent(
        self,
        name: str,
        controller: AgentController,
        role: str,
        objective: str,
        system_prompt: str = "",
        provider=None,
        max_tool_calls_per_turn: int = 2,
    ) -> AgentProfile:
        if name in self._runtimes:
            raise ValueError("agent already registered: {0}".format(name))
        profile = AgentProfile(
            name=name,
            role=role,
            objective=objective,
            system_prompt=system_prompt,
            provider=provider,
            max_tool_calls_per_turn=max_tool_calls_per_turn,
        )
        wallet = Wallet(name, signature_schemes=self.blockchain.signature_schemes)
        runtime = AgentRuntime(profile=profile, controller=controller, wallet=wallet)
        self._runtime_order.append(name)
        self._runtimes[name] = runtime
        self.wallets[name] = wallet
        self.cash_balances_yuan[name] = float(self.initial_cash_yuan)
        self._emit("agent_registered", name, {"role": role, "objective": objective})
        return profile

    def initialize_chain(self, genesis_miner: str, extra_reward_blocks: int = 1) -> None:
        wallet = self.wallets[genesis_miner]
        if self.blockchain.best_tip is not None:
            raise RuntimeError("chain already initialized")
        self.blockchain.create_genesis_block(wallet.primary_pubkey_hash, data="genesis")
        self._emit("genesis_created", genesis_miner, {"height": self.blockchain.best_height()})
        for reward_index in range(extra_reward_blocks):
            block = self.node.mine_pending(wallet.primary_pubkey_hash, coinbase_data="bootstrap-{0}".format(reward_index))
            self._emit(
                "block_mined",
                genesis_miner,
                {
                    "block_hash": block.block_hash,
                    "height": block.header.height,
                    "bootstrap": True,
                },
            )
        available_liquidity = max(0, wallet.balance(self.blockchain) - 1)
        seed_amount = min(self.market_liquidity_tokens, available_liquidity)
        if seed_amount > 0:
            bootstrap_tx = wallet.create_transaction(
                self.blockchain,
                self.market_wallet.primary_pubkey_hash,
                amount=seed_amount,
                fee=1,
            )
            self.node.submit_transaction(bootstrap_tx)
            self._emit(
                "market_seeded",
                genesis_miner,
                {
                    "txid": bootstrap_tx.txid,
                    "amount": seed_amount,
                },
            )
            self.mine(genesis_miner, coinbase_data="market-seed")

    def initialize_bootstrap_chain(self, extra_reward_blocks: int = 1) -> None:
        if self.blockchain.best_tip is not None:
            raise RuntimeError("chain already initialized")
        self.blockchain.create_genesis_block(self.bootstrap_wallet.primary_pubkey_hash, data="genesis")
        self._emit("genesis_created", "bootstrap_system", {"height": self.blockchain.best_height()})
        for reward_index in range(extra_reward_blocks):
            self._mine_to_pubkey_hash(
                miner_label="bootstrap_system",
                recipient_pubkey_hash=self.bootstrap_wallet.primary_pubkey_hash,
                coinbase_data="bootstrap-{0}".format(reward_index),
            )
        available_liquidity = max(0, self.bootstrap_wallet.balance(self.blockchain) - 1)
        seed_amount = min(self.market_liquidity_tokens, available_liquidity)
        if seed_amount > 0:
            bootstrap_tx = self.bootstrap_wallet.create_transaction(
                self.blockchain,
                self.market_wallet.primary_pubkey_hash,
                amount=seed_amount,
                fee=1,
            )
            self.node.submit_transaction(bootstrap_tx)
            self._emit(
                "market_seeded",
                "bootstrap_system",
                {
                    "txid": bootstrap_tx.txid,
                    "amount": seed_amount,
                },
            )
            self._mine_to_pubkey_hash(
                miner_label="bootstrap_system",
                recipient_pubkey_hash=self.bootstrap_wallet.primary_pubkey_hash,
                coinbase_data="market-seed",
            )

    def bootstrap_transfer(self, recipient: str, amount: int, fee: int = 1) -> Transaction:
        if amount <= 0:
            raise ValueError("amount must be positive")
        recipient_hash = resolve_agent_recipient(self, recipient)
        if recipient_hash is None:
            raise ValueError("unknown recipient: {0}".format(recipient))
        transaction = self.bootstrap_wallet.create_transaction(
            self.blockchain,
            recipient_hash,
            amount=amount,
            fee=fee,
            utxo_view=self._working_utxo_set(),
        )
        self.node.submit_transaction(transaction)
        self._emit(
            "bootstrap_transfer",
            "bootstrap_system",
            {
                "txid": transaction.txid,
                "recipient": recipient,
                "amount": amount,
                "fee": fee,
            },
        )
        return transaction

    def agent_profiles(self) -> Tuple[AgentProfile, ...]:
        return tuple(self._runtimes[name].profile for name in self._runtime_order)

    def agent_snapshots(self) -> Tuple[AgentSnapshot, ...]:
        working_utxo = self._working_utxo_set()
        return tuple(
            AgentSnapshot(
                name=name,
                role=self._runtimes[name].profile.role,
                balance=self.wallets[name].balance_from_utxo_view(working_utxo),
                fiat_balance_yuan=round(self.cash_balances_yuan[name], 2),
                net_worth_yuan=round(self.net_worth_yuan(name), 2),
                bankrupt=self.is_bankrupt(name),
                primary_pubkey_hash=self.wallets[name].primary_pubkey_hash,
            )
            for name in self._runtime_order
        )

    def balances(self) -> Dict[str, int]:
        return {snapshot.name: snapshot.balance for snapshot in self.agent_snapshots()}

    def recent_events(self, limit: Optional[int] = None) -> Tuple[SimulationEvent, ...]:
        window = self.recent_event_window if limit is None else max(0, limit)
        return tuple(self.events[-window:])

    def _ensure_initial_state_snapshot(self) -> None:
        if self.initial_state_snapshot is not None:
            return
        self.initial_state_snapshot = {
            "tick": self.tick,
            "chain_height": self.blockchain.best_height(),
            "best_tip": self.blockchain.best_tip,
            "current_price_yuan": self.current_price_yuan,
            "market_pool_balance": self.market_pool_balance(),
            "market_fiat_reserve_yuan": round(self.market_fiat_reserve_yuan, 2),
            "external_capital_strategy": self.external_capital_strategy,
            "agents": [snapshot.to_dict() for snapshot in self.agent_snapshots()],
            "cash_balances_yuan": {
                name: round(balance, 2) for name, balance in self.cash_balances_yuan.items()
            },
            "token_balances": self.balances(),
        }

    def _market_rules(self) -> Dict[str, object]:
        return {
            "living_cost_per_round_yuan": self.living_cost_per_round_yuan,
            "bankruptcy_floor_yuan": self.bankruptcy_floor_yuan,
            "external_capital_strategy": self.external_capital_strategy,
            "external_buy_budget_yuan": self.external_buy_budget_yuan,
            "external_buy_budget_unlimited": self.external_budget_is_unlimited(),
            "external_max_buy_tokens_per_round": self.external_max_buy_tokens_per_round,
            "external_price_tolerance_ratio": self.external_price_tolerance_ratio,
            "external_fill_rule": (
                "若卖出报价不高于当前市场价上浮 1% 的外部资本接盘上限，"
                "外部资本会在本轮所有卖单中按报价从低到高优先买入，但总计不超过每轮额度。"
            ),
            "market_pool_buy_rule": "买入默认按当前市场价从市场池成交。",
            "market_pool_sell_rule": "卖出默认按当前市场价卖给市场池，或在满足条件时优先卖给外部资本。",
            "mining_rule": "任何智能体都可以选择调用 mine_block 挖矿领取区块奖励。",
            "round_rule": (
                "本回合采用同步决策：所有智能体先基于同一个回合起点状态提交方案，"
                "等全部提交后才统一执行。"
            ),
        }

    def _current_world_state(self) -> Dict[str, object]:
        return {
            "tick": self.tick,
            "chain_height": self.blockchain.best_height(),
            "best_tip": self.blockchain.best_tip,
            "mempool_size": len(self.node.mempool),
            "current_price_yuan": self.current_price_yuan,
            "market_pool_balance": self.market_pool_balance(),
            "market_fiat_reserve_yuan": round(self.market_fiat_reserve_yuan, 2),
            "external_current_round_budget_yuan": self.external_current_round_budget_yuan,
            "external_remaining_budget_yuan": self.external_remaining_budget_yuan,
            "external_remaining_token_capacity": self.external_remaining_token_capacity,
            "external_bid_ceiling_yuan": self.external_bid_ceiling_yuan(),
            "agents": [snapshot.to_dict() for snapshot in self.agent_snapshots()],
            "cash_balances_yuan": {
                name: round(balance, 2) for name, balance in self.cash_balances_yuan.items()
            },
            "token_balances": self.balances(),
        }

    def build_observation(self, agent_name: str) -> AgentObservation:
        self._ensure_initial_state_snapshot()
        runtime = self._runtimes[agent_name]
        toolbox = AgentToolbox(self, agent_name)
        working_utxo = self._working_utxo_set()
        working_balance = runtime.wallet.balance_from_utxo_view(working_utxo)
        recent_price_history = tuple(self.price_history[-6:])
        previous_price = (
            float(self.price_history[-2]["price"])
            if len(self.price_history) >= 2
            else self.current_price_yuan
        )
        older_price = (
            float(self.price_history[-6]["price"])
            if len(self.price_history) >= 6
            else float(self.price_history[0]["price"])
        )
        price_change_1_round = round(self.current_price_yuan - previous_price, 2)
        price_change_5_rounds = round(self.current_price_yuan - older_price, 2)
        if price_change_5_rounds > 0.05:
            trend_label = "up"
        elif price_change_5_rounds < -0.05:
            trend_label = "down"
        else:
            trend_label = "flat"
        return AgentObservation(
            tick=self.tick,
            profile=runtime.profile,
            balance=working_balance,
            fiat_balance_yuan=round(self.cash_balances_yuan[agent_name], 2),
            net_worth_yuan=round(float(self.cash_balances_yuan[agent_name]) + working_balance * self.current_price_yuan, 2),
            current_price_yuan=self.current_price_yuan,
            recent_price_history=recent_price_history,
            price_change_1_round=price_change_1_round,
            price_change_5_rounds=price_change_5_rounds,
            trend_label=trend_label,
            living_cost_per_round_yuan=self.living_cost_per_round_yuan,
            bankrupt=self.is_bankrupt(agent_name),
            mempool_size=len(self.node.mempool),
            chain_height=self.blockchain.best_height(),
            best_tip=self.blockchain.best_tip,
            visible_agents=self.agent_snapshots(),
            recent_events=self.recent_events(),
            initial_state=dict(self.initial_state_snapshot or {}),
            current_state=self._current_world_state(),
            full_price_history=tuple(self.price_history),
            round_history=tuple(self.round_history),
            full_event_history=tuple(event.to_dict() for event in self.events),
            market_rules=self._market_rules(),
            available_tools=tuple(toolbox.available_tools()),
        )

    def is_bankrupt(self, agent_name: str) -> bool:
        return agent_name in self.bankrupt_agents

    def net_worth_yuan(self, agent_name: str) -> float:
        token_value = self.wallets[agent_name].balance(self.blockchain) * self.current_price_yuan
        return float(self.cash_balances_yuan[agent_name]) + token_value

    def market_pool_balance(self) -> int:
        return sum(
            tx_output.value
            for tx_output in self._working_utxo_set().values()
            if tx_output.pubkey_hash in self.market_wallet.keys
        )

    def _working_utxo_set(self) -> Dict[Tuple[str, int], TxOutput]:
        working_utxo = self.blockchain.best_utxo_set()
        for existing in self.node.mempool:
            validated_existing = validate_transaction(
                existing,
                working_utxo,
                self.blockchain.signature_schemes,
                allow_coinbase=False,
            )
            apply_transaction(validated_existing, working_utxo)
        return working_utxo

    def transfer(
        self,
        sender_name: str,
        recipient: str,
        amount: int,
        fee: int = 1,
        bundle_mode: str = "soibs",
    ) -> Transaction:
        if self.is_bankrupt(sender_name):
            raise ValueError("bankrupt agent cannot transfer")
        if amount <= 0:
            raise ValueError("amount must be positive")
        if fee < 0:
            raise ValueError("fee cannot be negative")
        recipient_hash = resolve_agent_recipient(self, recipient)
        if recipient_hash is None:
            raise ValueError("unknown recipient: {0}".format(recipient))
        wallet = self.wallets[sender_name]
        transaction = wallet.create_transaction(
            self.blockchain,
            recipient_hash,
            amount=amount,
            fee=fee,
            bundle_mode=bundle_mode,
            utxo_view=self._working_utxo_set(),
        )
        self.node.submit_transaction(transaction)
        self._emit(
            "transaction_submitted",
            sender_name,
            {
                "txid": transaction.txid,
                "recipient": recipient,
                "amount": amount,
                "fee": fee,
                "bundle_mode": bundle_mode,
                "mempool_size": len(self.node.mempool),
            },
        )
        return transaction

    def buy_from_market(self, agent_name: str, amount: int, fee: int = 1) -> Transaction:
        if self.is_bankrupt(agent_name):
            raise ValueError("bankrupt agent cannot buy tokens")
        if amount <= 0:
            raise ValueError("amount must be positive")
        projected_cash = self.cash_balances_yuan[agent_name] - (amount * self.current_price_yuan)
        if projected_cash < self.bankruptcy_floor_yuan:
            raise ValueError("purchase would exceed bankruptcy floor")
        if self.market_pool_balance() < amount + fee:
            raise ValueError("market pool has insufficient token liquidity")
        transaction = self.market_wallet.create_transaction(
            self.blockchain,
            self.wallets[agent_name].primary_pubkey_hash,
            amount=amount,
            fee=fee,
            utxo_view=self._working_utxo_set(),
        )
        self.node.submit_transaction(transaction)
        value_yuan = round(amount * self.current_price_yuan, 2)
        self.cash_balances_yuan[agent_name] = round(projected_cash, 2)
        self.market_fiat_reserve_yuan = round(self.market_fiat_reserve_yuan + value_yuan, 2)
        self._emit(
            "market_buy",
            agent_name,
            {
                "txid": transaction.txid,
                "amount": amount,
                "price_yuan": self.current_price_yuan,
                "value_yuan": value_yuan,
                "cash_balance_yuan": self.cash_balances_yuan[agent_name],
            },
        )
        return transaction

    def sell_to_market(
        self,
        agent_name: str,
        amount: int,
        fee: int = 1,
        venue: str = "auto",
        quote_price_yuan: Optional[float] = None,
    ) -> Transaction:
        if venue in {"auto", "external_capital"}:
            ask_price_yuan = self.current_price_yuan if quote_price_yuan is None else float(quote_price_yuan)
            reserved_external_fill = self._reserved_external_fill_amount(agent_name)
            has_external_budget = (
                self.external_remaining_budget_yuan is None or self.external_remaining_budget_yuan > 0
            ) and self.external_remaining_token_capacity > 0
            if (
                ask_price_yuan <= self.external_bid_ceiling_yuan()
                and has_external_budget
                and reserved_external_fill > 0
            ):
                return self.sell_to_external_capital(
                    agent_name=agent_name,
                    amount=reserved_external_fill,
                    ask_price_yuan=ask_price_yuan,
                    fee=fee,
                )
            if venue == "external_capital":
                raise ValueError("external capital bid unavailable for requested quote")
        if self.is_bankrupt(agent_name):
            raise ValueError("bankrupt agent cannot sell tokens")
        if amount <= 0:
            raise ValueError("amount must be positive")
        payout_yuan = round(amount * self.current_price_yuan, 2)
        if payout_yuan > self.market_fiat_reserve_yuan:
            raise ValueError("market pool has insufficient fiat reserve")
        transaction = self.wallets[agent_name].create_transaction(
            self.blockchain,
            self.market_wallet.primary_pubkey_hash,
            amount=amount,
            fee=fee,
            utxo_view=self._working_utxo_set(),
        )
        self.node.submit_transaction(transaction)
        self.cash_balances_yuan[agent_name] = round(
            self.cash_balances_yuan[agent_name] + payout_yuan,
            2,
        )
        self.market_fiat_reserve_yuan = round(self.market_fiat_reserve_yuan - payout_yuan, 2)
        self._emit(
            "market_sell",
            agent_name,
            {
                "txid": transaction.txid,
                "amount": amount,
                "price_yuan": self.current_price_yuan,
                "value_yuan": payout_yuan,
                "cash_balance_yuan": self.cash_balances_yuan[agent_name],
            },
        )
        return transaction

    def sell_to_external_capital(
        self,
        agent_name: str,
        amount: int,
        ask_price_yuan: Optional[float] = None,
        fee: int = 1,
    ) -> Transaction:
        if self.is_bankrupt(agent_name):
            raise ValueError("bankrupt agent cannot sell tokens")
        if amount <= 0:
            raise ValueError("amount must be positive")
        quote_price = self.current_price_yuan if ask_price_yuan is None else float(ask_price_yuan)
        if quote_price <= 0:
            raise ValueError("quote price must be positive")
        bid_ceiling = self.external_bid_ceiling_yuan()
        if quote_price > bid_ceiling:
            raise ValueError("quote exceeds external capital bid ceiling")
        if amount > self.external_remaining_token_capacity:
            raise ValueError("external capital token capacity exhausted")
        payout_yuan = round(amount * quote_price, 2)
        if self.external_remaining_budget_yuan is not None and payout_yuan > self.external_remaining_budget_yuan:
            raise ValueError("external capital has insufficient remaining round budget")
        transaction = self.wallets[agent_name].create_transaction(
            self.blockchain,
            self.external_sink_wallet.primary_pubkey_hash,
            amount=amount,
            fee=fee,
            utxo_view=self._working_utxo_set(),
        )
        self.node.submit_transaction(transaction)
        self.cash_balances_yuan[agent_name] = round(
            self.cash_balances_yuan[agent_name] + payout_yuan,
            2,
        )
        self.external_remaining_token_capacity = max(0, self.external_remaining_token_capacity - amount)
        if self.external_remaining_budget_yuan is not None:
            self.external_remaining_budget_yuan = round(self.external_remaining_budget_yuan - payout_yuan, 2)
        self._emit(
            "external_capital_fill",
            agent_name,
            {
                "txid": transaction.txid,
                "amount": amount,
                "price_yuan": quote_price,
                "value_yuan": payout_yuan,
                "cash_balance_yuan": self.cash_balances_yuan[agent_name],
                "remaining_budget_yuan": self.external_remaining_budget_yuan,
                "remaining_token_capacity": self.external_remaining_token_capacity,
                "budget_unlimited": self.external_budget_is_unlimited(),
                "bid_ceiling_yuan": bid_ceiling,
                "strategy": self.external_budget_strategy_label,
                "reason": self.external_budget_reason,
            },
        )
        return transaction

    def mine(self, agent_name: str, coinbase_data: str = "agent-mined") -> Block:
        wallet = self.wallets[agent_name]
        return self._mine_to_pubkey_hash(
            miner_label=agent_name,
            recipient_pubkey_hash=wallet.primary_pubkey_hash,
            coinbase_data=coinbase_data,
        )

    def _mine_to_pubkey_hash(
        self,
        miner_label: str,
        recipient_pubkey_hash: str,
        coinbase_data: str = "agent-mined",
    ) -> Block:
        block = self.node.mine_pending(recipient_pubkey_hash, coinbase_data=coinbase_data)
        coinbase_value = sum(output.value for output in block.transactions[0].outputs)
        subsidy = self.blockchain.reward_for_height(block.header.height)
        fees_captured = max(0, coinbase_value - subsidy)
        self._emit(
            "block_mined",
            miner_label,
            {
                "block_hash": block.block_hash,
                "height": block.header.height,
                "transaction_count": len(block.transactions),
                "coinbase_value": coinbase_value,
                "subsidy": subsidy,
                "fees_captured": fees_captured,
                "target": block.header.target,
                "difficulty_ratio": self.blockchain.difficulty_ratio_for_target(block.header.target),
                "expected_hash_attempts": self.blockchain.expected_hash_attempts_for_target(
                    block.header.target
                ),
            },
        )
        return block

    def _plan_agent_from_observation(
        self,
        agent_name: str,
        observation: AgentObservation,
    ) -> AgentDecision:
        if self.is_bankrupt(agent_name):
            decision = AgentDecision(summary="{0} 已破产，本回合无法行动".format(agent_name))
            self._emit("agent_bankrupt_idle", agent_name, {"summary": decision.summary})
            return decision
        runtime = self._runtimes[agent_name]
        decision = runtime.controller.plan_turn(observation)
        if decision.summary or decision.tool_calls:
            self._emit(
                "agent_decision",
                agent_name,
                {
                    "summary": decision.summary,
                    "tool_calls": [tool_call.to_dict() for tool_call in decision.tool_calls],
                    "phase": "planned",
                },
            )
        return decision

    def _safe_plan_agent_from_observation(
        self,
        agent_name: str,
        observation: AgentObservation,
    ) -> AgentDecision:
        if self.is_bankrupt(agent_name):
            decision = AgentDecision(summary="{0} 已破产，本回合无法行动".format(agent_name))
            self._emit("agent_bankrupt_idle", agent_name, {"summary": decision.summary})
            return decision
        try:
            return self._plan_agent_from_observation(agent_name, observation)
        except Exception as exc:
            decision = AgentDecision(summary="{0} 本回合因模型或网络错误而跳过".format(agent_name))
            self._emit(
                "agent_plan_failed",
                agent_name,
                {
                    "error": str(exc),
                    "summary": decision.summary,
                },
            )
            self._emit(
                "agent_decision",
                agent_name,
                {
                    "summary": decision.summary,
                    "tool_calls": [],
                    "phase": "planned",
                },
            )
            return decision

    def _execute_decision(
        self,
        agent_name: str,
        decision: AgentDecision,
    ) -> Tuple[ToolResult, ...]:
        toolbox = AgentToolbox(self, agent_name)
        max_calls = self._runtimes[agent_name].profile.max_tool_calls_per_turn
        results: List[ToolResult] = []
        for tool_index, tool_call in enumerate(decision.tool_calls[:max_calls]):
            self._active_tool_execution_key = (agent_name, tool_index)
            result = toolbox.execute(tool_call)
            results.append(result)
        self._active_tool_execution_key = None
        for result in results:
            self._emit(
                "tool_executed",
                agent_name,
                {
                    "tool_name": result.tool_name,
                    "ok": result.ok,
                    "error": result.error,
                    "payload": result.payload,
                },
            )
        return tuple(results)

    def _reserved_external_fill_amount(self, agent_name: str) -> int:
        if self._active_tool_execution_key is None:
            return 0
        active_agent, tool_index = self._active_tool_execution_key
        if active_agent != agent_name:
            return 0
        return int(self._planned_external_token_fills.get((agent_name, tool_index), 0))

    def _plan_external_capital_allocations(
        self,
        decisions: Mapping[str, AgentDecision],
    ) -> None:
        self._planned_external_token_fills = {}
        remaining = self.external_max_buy_tokens_per_round
        bid_ceiling = self.external_bid_ceiling_yuan()
        candidates: List[Tuple[float, int, str, int, int, str]] = []
        reviews: List[Tuple[str, int, str, int, float, str, str, int]] = []
        for order_index, agent_name in enumerate(self._runtime_order):
            decision = decisions.get(agent_name, AgentDecision())
            for tool_index, tool_call in enumerate(decision.tool_calls):
                if tool_call.tool_name != "sell_tokens":
                    continue
                venue = str(tool_call.arguments.get("venue", "auto"))
                if venue not in {"auto", "external_capital"}:
                    continue
                amount = int(tool_call.arguments.get("amount", 0))
                if amount <= 0:
                    continue
                ask_price = float(tool_call.arguments.get("quote_price_yuan", self.current_price_yuan))
                if ask_price > bid_ceiling:
                    reviews.append(
                        (
                            agent_name,
                            tool_index,
                            venue,
                            amount,
                            ask_price,
                            "rejected_price_too_high",
                            "报价高于外部资本本轮接盘上限",
                            0,
                        )
                    )
                    continue
                candidates.append((ask_price, order_index, agent_name, tool_index, amount, venue))
        candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
        for ask_price, _order_index, agent_name, tool_index, amount, venue in candidates:
            if remaining <= 0:
                reviews.append(
                    (
                        agent_name,
                        tool_index,
                        venue,
                        amount,
                        ask_price,
                        "rejected_capacity_filled",
                        "本轮外部资本 100 枚额度已被更低报价的卖单占满",
                        0,
                    )
                )
                continue
            fill_amount = min(amount, remaining)
            if fill_amount > 0:
                self._planned_external_token_fills[(agent_name, tool_index)] = fill_amount
                remaining -= fill_amount
                if fill_amount == amount:
                    reviews.append(
                        (
                            agent_name,
                            tool_index,
                            venue,
                            amount,
                            ask_price,
                            "fully_selected",
                            "该卖单已被外部资本完整选中",
                            fill_amount,
                        )
                    )
                else:
                    reviews.append(
                        (
                            agent_name,
                            tool_index,
                            venue,
                            amount,
                            ask_price,
                            "partially_selected",
                            "该卖单只部分成交，剩余额度已被更低报价卖单占用",
                            fill_amount,
                        )
                    )
        self.external_remaining_token_capacity = remaining
        for agent_name, tool_index, venue, amount, ask_price, status, reason, planned_fill_amount in reviews:
            self._emit(
                "external_capital_order_review",
                agent_name,
                {
                    "tool_index": tool_index,
                    "venue": venue,
                    "asked_amount": amount,
                    "ask_price_yuan": ask_price,
                    "bid_ceiling_yuan": bid_ceiling,
                    "planned_fill_amount": planned_fill_amount,
                    "status": status,
                    "reason": reason,
                    "remaining_token_capacity_after_review": self.external_remaining_token_capacity,
                },
            )

    def step_agent(self, agent_name: str) -> Tuple[AgentDecision, Tuple[ToolResult, ...]]:
        observation = self.build_observation(agent_name)
        decision = self._safe_plan_agent_from_observation(agent_name, observation)
        results = self._execute_decision(agent_name, decision)
        return decision, results

    def step(self) -> Dict[str, Tuple[AgentDecision, Tuple[ToolResult, ...]]]:
        outcomes: Dict[str, Tuple[AgentDecision, Tuple[ToolResult, ...]]] = {}
        last_event_index = len(self.events)
        self._prepare_external_capital_round()
        self._ensure_initial_state_snapshot()
        observations = {
            agent_name: self.build_observation(agent_name) for agent_name in self._runtime_order
        }
        decisions = {
            agent_name: self._safe_plan_agent_from_observation(agent_name, observations[agent_name])
            for agent_name in self._runtime_order
        }
        self._plan_external_capital_allocations(decisions)
        for agent_name in self._runtime_order:
            results = self._execute_decision(agent_name, decisions[agent_name])
            outcomes[agent_name] = (decisions[agent_name], results)
        self._apply_round_costs()
        self._run_external_buyback()
        round_events = self.events[last_event_index:]
        next_price = self._update_market_price(round_events)
        self.price_history.append(
            {
                "round": self.tick,
                "label": "第 {0} 轮".format(self.tick + 1),
                "price": next_price,
            }
        )
        self.round_history.append(
            {
                "round": self.tick,
                "height": self.blockchain.best_height(),
                "balances": self.balances(),
                "cash_balances_yuan": {
                    name: round(balance, 2) for name, balance in self.cash_balances_yuan.items()
                },
                "price": next_price,
                "mempool_size": len(self.node.mempool),
                "event_count": len(round_events),
            }
        )
        self.tick += 1
        return outcomes

    def run(self, rounds: int) -> List[Dict[str, Tuple[AgentDecision, Tuple[ToolResult, ...]]]]:
        if rounds < 0:
            raise ValueError("rounds must be non-negative")
        history: List[Dict[str, Tuple[AgentDecision, Tuple[ToolResult, ...]]]] = []
        for _ in range(rounds):
            history.append(self.step())
        return history

    def _emit(self, event_type: str, agent_name: Optional[str], payload: Mapping[str, object]) -> None:
        self.events.append(
            SimulationEvent(
                tick=self.tick,
                event_type=event_type,
                agent_name=agent_name,
                payload=dict(payload),
            )
        )

    def _apply_round_costs(self) -> None:
        for agent_name in self._runtime_order:
            self.cash_balances_yuan[agent_name] = round(
                self.cash_balances_yuan[agent_name] - self.living_cost_per_round_yuan,
                2,
            )
            self._emit(
                "living_cost",
                agent_name,
                {
                    "cost_yuan": self.living_cost_per_round_yuan,
                    "cash_balance_yuan": self.cash_balances_yuan[agent_name],
                },
            )
            if (
                self.cash_balances_yuan[agent_name] <= self.bankruptcy_floor_yuan
                and agent_name not in self.bankrupt_agents
            ):
                self.bankrupt_agents.add(agent_name)
                self._emit(
                    "bankruptcy_declared",
                    agent_name,
                    {
                        "cash_balance_yuan": self.cash_balances_yuan[agent_name],
                        "net_worth_yuan": round(self.net_worth_yuan(agent_name), 2),
                    },
                )

    def _prepare_external_capital_round(self) -> None:
        self.external_current_round_budget_yuan = 0.0
        self.external_remaining_budget_yuan = 0.0
        self.external_remaining_token_capacity = self.external_max_buy_tokens_per_round
        self.external_budget_strategy_label = self.external_capital_strategy
        self.external_budget_reason = ""
        self._planned_external_token_fills = {}
        if self.external_buy_budget_yuan is not None and self.external_buy_budget_yuan <= 0:
            return
        orders = self._external_capital_orders()
        total_budget_yuan = 0.0
        strategy_names: List[str] = []
        reasons: List[str] = []
        unlimited = self.external_budget_is_unlimited()
        for strategy_name, budget_yuan, reason in orders:
            if budget_yuan is not None and budget_yuan <= 0:
                continue
            if budget_yuan is not None:
                total_budget_yuan += budget_yuan
            strategy_names.append(strategy_name)
            reasons.append("{0}: {1}".format(strategy_name, reason))
            self._emit(
                "external_capital_signal",
                "external_capital",
                {
                    "strategy": strategy_name,
                    "budget_yuan": None if budget_yuan is None else round(budget_yuan, 2),
                    "budget_unlimited": budget_yuan is None,
                    "reason": reason,
                },
            )
        if unlimited:
            self.external_current_round_budget_yuan = None
            self.external_remaining_budget_yuan = None
        else:
            self.external_current_round_budget_yuan = round(total_budget_yuan, 2)
            self.external_remaining_budget_yuan = round(total_budget_yuan, 2)
        self.external_budget_strategy_label = (
            "+".join(strategy_names) if strategy_names else self.external_capital_strategy
        )
        self.external_budget_reason = " | ".join(reasons)

    def _run_external_buyback(self) -> None:
        if self.external_remaining_budget_yuan is not None and self.external_remaining_budget_yuan <= 0:
            self._emit(
                "external_capital_skipped",
                "external_capital",
                {"reason": "no remaining external capital budget"},
            )
            return
        if self.external_remaining_token_capacity <= 0:
            self._emit(
                "external_capital_skipped",
                "external_capital",
                {"reason": "no remaining external capital token capacity"},
            )
            return

        if self.external_remaining_budget_yuan is None:
            affordable_amount = 10**12
        else:
            affordable_amount = int(self.external_remaining_budget_yuan // self.current_price_yuan)
        if affordable_amount <= 0:
            return
        available_amount = max(0, self.market_pool_balance() - self.market_liquidity_floor_tokens - 1)
        amount = min(affordable_amount, available_amount, self.external_remaining_token_capacity)
        if amount <= 0:
            self._emit(
                "external_capital_skipped",
                "external_capital",
                {"reason": "market pool out of liquidity"},
            )
            return
        transaction = self.market_wallet.create_transaction(
            self.blockchain,
            self.external_sink_wallet.primary_pubkey_hash,
            amount=amount,
            fee=1,
            utxo_view=self._working_utxo_set(),
        )
        self.node.submit_transaction(transaction)
        spent_yuan = round(amount * self.current_price_yuan, 2)
        if self.external_remaining_budget_yuan is not None:
            self.external_remaining_budget_yuan = round(self.external_remaining_budget_yuan - spent_yuan, 2)
        self.external_remaining_token_capacity = max(0, self.external_remaining_token_capacity - amount)
        self.market_fiat_reserve_yuan = round(self.market_fiat_reserve_yuan + spent_yuan, 2)
        self._emit(
            "external_capital_buy",
            "external_capital",
            {
                "txid": transaction.txid,
                "amount": amount,
                "price_yuan": self.current_price_yuan,
                "value_yuan": spent_yuan,
                "strategy": self.external_budget_strategy_label,
                "reason": self.external_budget_reason,
                "budget_yuan": None
                if self.external_current_round_budget_yuan is None
                else round(self.external_current_round_budget_yuan, 2),
                "remaining_budget_yuan": self.external_remaining_budget_yuan,
                "remaining_token_capacity": self.external_remaining_token_capacity,
                "budget_unlimited": self.external_budget_is_unlimited(),
            },
        )

    def external_bid_ceiling_yuan(self) -> float:
        return round(self.current_price_yuan * (1.0 + self.external_price_tolerance_ratio), 2)

    def external_budget_is_unlimited(self) -> bool:
        return self.external_buy_budget_yuan is None

    def _external_capital_orders(self) -> List[Tuple[str, Optional[float], str]]:
        strategy = self.external_capital_strategy
        if strategy == "strategy_mix":
            return [
                self._budget_for_fixed_dca(),
                self._budget_for_dip_buyer(),
                self._budget_for_trend_follower(),
            ]
        strategy_builders = {
            "fixed_dca": self._budget_for_fixed_dca,
            "dip_buyer": self._budget_for_dip_buyer,
            "trend_follower": self._budget_for_trend_follower,
        }
        builder = strategy_builders.get(strategy, self._budget_for_fixed_dca)
        return [builder()]

    def _budget_for_fixed_dca(self) -> Tuple[str, Optional[float], str]:
        if self.external_budget_is_unlimited():
            return ("fixed_dca", None, "unlimited recurring inflow")
        return ("fixed_dca", float(self.external_buy_budget_yuan), "fixed recurring inflow")

    def _budget_for_dip_buyer(self) -> Tuple[str, Optional[float], str]:
        if self.external_budget_is_unlimited():
            return ("dip_buyer", None, "unlimited dip buying")
        reference_window = self.price_history[-4:]
        reference_prices = [float(item["price"]) for item in reference_window]
        reference_price = sum(reference_prices) / max(1, len(reference_prices))
        if self.current_price_yuan <= reference_price * 0.95:
            multiplier = 1.8
            reason = "buying the dip below recent reference"
        elif self.current_price_yuan >= reference_price * 1.05:
            multiplier = 0.45
            reason = "price elevated above recent reference"
        else:
            multiplier = 1.0
            reason = "price near recent reference"
        return (
            "dip_buyer",
            round(self.external_buy_budget_yuan * multiplier, 2),
            reason,
        )

    def _budget_for_trend_follower(self) -> Tuple[str, Optional[float], str]:
        if self.external_budget_is_unlimited():
            return ("trend_follower", None, "unlimited trend following")
        previous_price = (
            float(self.price_history[-2]["price"])
            if len(self.price_history) >= 2
            else self.current_price_yuan
        )
        if self.current_price_yuan > previous_price:
            multiplier = 1.6
            reason = "following upward momentum"
        elif self.current_price_yuan < previous_price:
            multiplier = 0.5
            reason = "reducing size on downward momentum"
        else:
            multiplier = 1.0
            reason = "flat momentum"
        return (
            "trend_follower",
            round(self.external_buy_budget_yuan * multiplier, 2),
            reason,
        )

    def _update_market_price(self, round_events: Sequence[SimulationEvent]) -> float:
        market_buy_yuan = sum(
            float(event.payload.get("value_yuan", 0.0))
            for event in round_events
            if event.event_type in {"market_buy", "external_capital_buy", "external_capital_fill"}
        )
        market_sell_yuan = sum(
            float(event.payload.get("value_yuan", 0.0))
            for event in round_events
            if event.event_type == "market_sell"
        )
        tx_count = sum(
            1
            for event in round_events
            if event.event_type in {"transaction_submitted", "market_buy", "market_sell"}
        )
        block_count = sum(1 for event in round_events if event.event_type == "block_mined")
        active_agents = {
            event.agent_name
            for event in round_events
            if event.agent_name
            and event.agent_name not in {"external_capital"}
            and event.event_type in {"transaction_submitted", "market_buy", "market_sell", "block_mined"}
        }
        non_miner_balances = [
            self.wallets[name].balance(self.blockchain)
            for name in self._runtime_order
            if name != "miner_1" and not self.is_bankrupt(name)
        ]
        concentration = 0.0
        total_non_miner = sum(non_miner_balances)
        if total_non_miner > 0 and non_miner_balances:
            concentration = max(non_miner_balances) / float(total_non_miner)
        net_flow_signal = (market_buy_yuan - market_sell_yuan) / 10000.0
        bankrupt_penalty = 0.012 * len(self.bankrupt_agents)
        activity_bonus = 0.005 * len(active_agents) + 0.003 * block_count + 0.002 * tx_count
        drift = (0.08 * net_flow_signal) + activity_bonus - (0.025 * concentration) - bankrupt_penalty
        drift = max(-0.08, min(0.12, drift))
        self.current_price_yuan = round(max(0.5, self.current_price_yuan * (1.0 + drift)), 2)
        self._emit(
            "price_updated",
            "market",
            {
                "price_yuan": self.current_price_yuan,
                "drift": round(drift, 4),
                "market_buy_yuan": round(market_buy_yuan, 2),
                "market_sell_yuan": round(market_sell_yuan, 2),
            },
        )
        return self.current_price_yuan
