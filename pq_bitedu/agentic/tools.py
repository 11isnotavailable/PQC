"""Tool surface exposed to local or hosted agents."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

from .protocol import ToolCall, ToolResult, ToolSpec

if TYPE_CHECKING:
    from .environment import MultiAgentEnvironment


def default_tool_specs() -> List[ToolSpec]:
    return [
        ToolSpec(
            name="inspect_market",
            description="读取当前市场价格、现金规则、外部资本买入策略，以及外部资本的接盘上限价格。",
            arguments={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="inspect_chain",
            description="读取链的总体状态，例如区块高度、最新区块哈希、内存池大小、当前奖励和难度。",
            arguments={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="inspect_wallet",
            description="读取你自己的钱包状态、可花费持币量、现金余额、净资产和地址信息。",
            arguments={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="inspect_agents",
            description="列出当前可见智能体的身份、角色、余额和破产状态。",
            arguments={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="send_transaction",
            description="创建并提交一笔链上转账，收款方可以是已注册智能体，也可以是原始 pubkey hash。",
            arguments={
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "description": "收款智能体名称，或 64 位十六进制 pubkey hash。",
                    },
                    "amount": {
                        "type": "integer",
                        "description": "正整数转账数量。",
                    },
                    "fee": {
                        "type": "integer",
                        "description": "非负手续费，默认值为 1。",
                    },
                    "bundle_mode": {
                        "type": "string",
                        "enum": ["soibs", "per_input"],
                        "description": "签名见证组织方式。",
                    },
                },
                "required": ["recipient", "amount"],
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="buy_tokens",
            description="按当前市场价使用现金从市场池买入 PQC。",
            arguments={
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "integer",
                        "description": "要买入的正整数代币数量。",
                    }
                },
                "required": ["amount"],
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="sell_tokens",
            description="把 PQC 卖出换成现金。可以卖给市场池，也可以在报价满足条件时卖给本轮外部资本。",
            arguments={
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "integer",
                        "description": "要卖出的正整数代币数量。",
                    },
                    "venue": {
                        "type": "string",
                        "enum": ["auto", "market_pool", "external_capital"],
                        "description": "卖出场所。auto 会在可行时优先匹配外部资本。",
                    },
                    "quote_price_yuan": {
                        "type": "number",
                        "description": "可选卖价，单位为元。若不高于当前市场价上浮 1% 的外部资本接盘上限，则外部资本会买入。",
                    },
                },
                "required": ["amount"],
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="mine_block",
            description="把当前内存池交易打包进新区块并挖矿，成功后领取 coinbase 奖励。",
            arguments={
                "type": "object",
                "properties": {
                    "coinbase_data": {
                        "type": "string",
                        "description": "可选标签，会写入 coinbase 输入中。",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="noop",
            description="明确表示本回合不执行任何动作。",
            arguments={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        ),
    ]


def action_tool_specs() -> List[ToolSpec]:
    allowed = {"send_transaction", "buy_tokens", "sell_tokens", "mine_block", "noop"}
    return [tool for tool in default_tool_specs() if tool.name in allowed]


class AgentToolbox:
    """Dispatches tool calls against the shared simulation environment."""

    def __init__(self, environment: "MultiAgentEnvironment", agent_name: str) -> None:
        self.environment = environment
        self.agent_name = agent_name

    def available_tools(self) -> List[ToolSpec]:
        return action_tool_specs()

    def execute(self, tool_call: ToolCall) -> ToolResult:
        name = tool_call.tool_name
        arguments = dict(tool_call.arguments)
        handlers = {
            "inspect_market": self._inspect_market,
            "inspect_chain": self._inspect_chain,
            "inspect_wallet": self._inspect_wallet,
            "inspect_agents": self._inspect_agents,
            "send_transaction": self._send_transaction,
            "buy_tokens": self._buy_tokens,
            "sell_tokens": self._sell_tokens,
            "mine_block": self._mine_block,
            "noop": self._noop,
        }
        if name not in handlers:
            return ToolResult(tool_name=name, ok=False, payload={}, error="unknown tool")
        try:
            payload = handlers[name](arguments)
            return ToolResult(tool_name=name, ok=True, payload=payload)
        except Exception as exc:
            return ToolResult(tool_name=name, ok=False, payload={}, error=str(exc))

    def _inspect_chain(self, _arguments: Dict[str, object]) -> Dict[str, object]:
        next_height = self.environment.blockchain.best_height() + 1
        return {
            "height": self.environment.blockchain.best_height(),
            "best_tip": self.environment.blockchain.best_tip,
            "mempool_size": len(self.environment.node.mempool),
            "balances": self.environment.balances(),
            "current_price_yuan": self.environment.current_price_yuan,
            "current_block_subsidy_pqc": self.environment.blockchain.reward_for_height(next_height),
            "current_difficulty_ratio": self.environment.blockchain.current_difficulty_ratio(),
        }

    def _inspect_market(self, _arguments: Dict[str, object]) -> Dict[str, object]:
        recent_price_history = self.environment.price_history[-6:]
        previous_price = (
            float(self.environment.price_history[-2]["price"])
            if len(self.environment.price_history) >= 2
            else self.environment.current_price_yuan
        )
        older_price = (
            float(self.environment.price_history[-6]["price"])
            if len(self.environment.price_history) >= 6
            else float(self.environment.price_history[0]["price"])
        )
        price_change_1_round = round(self.environment.current_price_yuan - previous_price, 2)
        price_change_5_rounds = round(self.environment.current_price_yuan - older_price, 2)
        if price_change_5_rounds > 0.05:
            trend_label = "up"
        elif price_change_5_rounds < -0.05:
            trend_label = "down"
        else:
            trend_label = "flat"
        return {
            "current_price_yuan": self.environment.current_price_yuan,
            "recent_price_history": list(recent_price_history),
            "price_change_1_round": price_change_1_round,
            "price_change_5_rounds": price_change_5_rounds,
            "trend_label": trend_label,
            "market_pool_balance": self.environment.market_pool_balance(),
            "market_liquidity_floor_tokens": self.environment.market_liquidity_floor_tokens,
            "market_fiat_reserve_yuan": round(self.environment.market_fiat_reserve_yuan, 2),
            "external_buy_budget_yuan": self.environment.external_buy_budget_yuan,
            "external_buy_budget_unlimited": self.environment.external_budget_is_unlimited(),
            "external_max_buy_tokens_per_round": self.environment.external_max_buy_tokens_per_round,
            "external_capital_strategy": self.environment.external_capital_strategy,
            "external_budget_strategy_label": self.environment.external_budget_strategy_label,
            "external_budget_reason": self.environment.external_budget_reason,
            "external_current_round_budget_yuan": None
            if self.environment.external_current_round_budget_yuan is None
            else round(self.environment.external_current_round_budget_yuan, 2),
            "external_remaining_budget_yuan": None
            if self.environment.external_remaining_budget_yuan is None
            else round(self.environment.external_remaining_budget_yuan, 2),
            "external_remaining_token_capacity": self.environment.external_remaining_token_capacity,
            "external_bid_ceiling_yuan": self.environment.external_bid_ceiling_yuan(),
            "external_price_tolerance_ratio": self.environment.external_price_tolerance_ratio,
            "external_fill_rule": (
                "若你用 venue='external_capital' 或 venue='auto' 卖出，且 quote_price_yuan 不高于 "
                "external_bid_ceiling_yuan，则外部资本会在本轮所有卖单里按报价从低到高优先买入，"
                "但总计最多只买 external_max_buy_tokens_per_round 枚。"
            ),
            "living_cost_per_round_yuan": self.environment.living_cost_per_round_yuan,
            "idle_cost_warning": (
                "Even if you do not invest at all, your cash balance is reduced every round by "
                "living_cost_per_round_yuan."
            ),
            "bankruptcy_floor_yuan": self.environment.bankruptcy_floor_yuan,
        }

    def _inspect_wallet(self, _arguments: Dict[str, object]) -> Dict[str, object]:
        wallet = self.environment.wallets[self.agent_name]
        working_utxo = self.environment._working_utxo_set()
        spendable_balance = wallet.balance_from_utxo_view(working_utxo)
        default_fee = 1
        return {
            "agent_name": self.agent_name,
            "balance": spendable_balance,
            "fiat_balance_yuan": round(self.environment.cash_balances_yuan[self.agent_name], 2),
            "net_worth_yuan": round(
                float(self.environment.cash_balances_yuan[self.agent_name])
                + spendable_balance * self.environment.current_price_yuan,
                2,
            ),
            "bankrupt": self.environment.is_bankrupt(self.agent_name),
            "default_token_fee": default_fee,
            "max_sendable_tokens": wallet.max_spendable_amount(
                self.environment.blockchain,
                fee=default_fee,
                utxo_view=working_utxo,
            ),
            "max_sellable_tokens": wallet.max_spendable_amount(
                self.environment.blockchain,
                fee=default_fee,
                utxo_view=working_utxo,
            ),
            "primary_pubkey_hash": wallet.primary_pubkey_hash,
            "known_pubkey_hashes": wallet.known_pubkey_hashes(),
        }

    def _inspect_agents(self, _arguments: Dict[str, object]) -> Dict[str, object]:
        return {
            "agents": [snapshot.to_dict() for snapshot in self.environment.agent_snapshots()],
        }

    def _send_transaction(self, arguments: Dict[str, object]) -> Dict[str, object]:
        recipient = str(arguments["recipient"])
        amount = int(arguments["amount"])
        fee = int(arguments.get("fee", 1))
        bundle_mode = str(arguments.get("bundle_mode", "soibs"))
        transaction = self.environment.transfer(
            sender_name=self.agent_name,
            recipient=recipient,
            amount=amount,
            fee=fee,
            bundle_mode=bundle_mode,
        )
        return {
            "txid": transaction.txid,
            "inputs": len(transaction.inputs),
            "outputs": len(transaction.outputs),
            "bundle_count": len(transaction.auth_bundles),
        }

    def _buy_tokens(self, arguments: Dict[str, object]) -> Dict[str, object]:
        amount = int(arguments["amount"])
        transaction = self.environment.buy_from_market(agent_name=self.agent_name, amount=amount)
        return {
            "txid": transaction.txid,
            "amount": amount,
            "price_yuan": self.environment.current_price_yuan,
            "cash_balance_yuan": round(self.environment.cash_balances_yuan[self.agent_name], 2),
        }

    def _sell_tokens(self, arguments: Dict[str, object]) -> Dict[str, object]:
        amount = int(arguments["amount"])
        venue = str(arguments.get("venue", "auto"))
        quote_price_yuan = arguments.get("quote_price_yuan")
        transaction = self.environment.sell_to_market(
            agent_name=self.agent_name,
            amount=amount,
            venue=venue,
            quote_price_yuan=None if quote_price_yuan is None else float(quote_price_yuan),
        )
        return {
            "txid": transaction.txid,
            "amount": amount,
            "price_yuan": self.environment.current_price_yuan,
            "cash_balance_yuan": round(self.environment.cash_balances_yuan[self.agent_name], 2),
            "external_remaining_budget_yuan": None
            if self.environment.external_remaining_budget_yuan is None
            else round(self.environment.external_remaining_budget_yuan, 2),
        }

    def _mine_block(self, arguments: Dict[str, object]) -> Dict[str, object]:
        coinbase_data = str(arguments.get("coinbase_data", "agent-mined"))
        block = self.environment.mine(agent_name=self.agent_name, coinbase_data=coinbase_data)
        return {
            "block_hash": block.block_hash,
            "height": block.header.height,
            "transaction_count": len(block.transactions),
        }

    def _noop(self, _arguments: Dict[str, object]) -> Dict[str, object]:
        return {"status": "idle"}


def resolve_agent_recipient(environment: "MultiAgentEnvironment", recipient: str) -> Optional[str]:
    if recipient in environment.wallets:
        return environment.wallets[recipient].primary_pubkey_hash
    if len(recipient) == 64:
        return recipient
    return None
