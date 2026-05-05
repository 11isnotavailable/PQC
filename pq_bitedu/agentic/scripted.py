"""Local scripted controllers for simulation and testing."""

from __future__ import annotations

from typing import Dict, List

from .protocol import AgentController, AgentDecision, AgentObservation, ToolCall


class NoopController(AgentController):
    """Controller that always stays idle."""

    def plan_turn(self, observation: AgentObservation) -> AgentDecision:
        return AgentDecision(summary="{0} stays idle".format(observation.profile.name))


class MinerController(AgentController):
    """Controller that mines whenever it gets a turn."""

    def __init__(self, coinbase_prefix: str = "miner-turn") -> None:
        self.coinbase_prefix = coinbase_prefix

    def plan_turn(self, observation: AgentObservation) -> AgentDecision:
        return AgentDecision(
            summary="{0} mines the current mempool".format(observation.profile.name),
            tool_calls=(
                ToolCall(
                    tool_name="mine_block",
                    arguments={"coinbase_data": "{0}-{1}".format(self.coinbase_prefix, observation.tick)},
                ),
            ),
        )


class RoundRobinTraderController(AgentController):
    """Controller that cycles through peer agents and sends transfers when funded."""

    def __init__(
        self,
        amount: int,
        fee: int = 1,
        bundle_mode: str = "soibs",
        target_balance: int = 56,
        buy_amount: int = 10,
        reserve_cash_yuan: float = 2500.0,
        emergency_cash_yuan: float = 1800.0,
        emergency_sell_amount: int = 4,
    ) -> None:
        self.amount = amount
        self.fee = fee
        self.bundle_mode = bundle_mode
        self.target_balance = target_balance
        self.buy_amount = buy_amount
        self.reserve_cash_yuan = reserve_cash_yuan
        self.emergency_cash_yuan = emergency_cash_yuan
        self.emergency_sell_amount = emergency_sell_amount
        self._cursor_by_agent: Dict[str, int] = {}

    def plan_turn(self, observation: AgentObservation) -> AgentDecision:
        if observation.bankrupt:
            return AgentDecision(summary="bankrupt and inactive")
        peers = [
            snapshot for snapshot in observation.visible_agents if snapshot.name != observation.profile.name
        ]
        if not peers:
            return AgentDecision(summary="no peers available")
        if (
            observation.balance < self.target_balance
            and observation.fiat_balance_yuan
            >= observation.current_price_yuan * self.buy_amount + self.reserve_cash_yuan
        ):
            return AgentDecision(
                summary="{0} buys {1} PQC to increase profit exposure".format(
                    observation.profile.name,
                    self.buy_amount,
                ),
                tool_calls=(ToolCall(tool_name="buy_tokens", arguments={"amount": self.buy_amount}),),
            )
        if (
            observation.fiat_balance_yuan < self.emergency_cash_yuan
            and observation.balance >= max(self.amount + self.fee + 8, 16)
        ):
            sell_amount = self.emergency_sell_amount if observation.balance >= 24 else 2
            return AgentDecision(
                summary="{0} sells {1} PQC to raise emergency cash".format(
                    observation.profile.name,
                    sell_amount,
                ),
                tool_calls=(ToolCall(tool_name="sell_tokens", arguments={"amount": sell_amount}),),
            )
        if observation.balance < self.amount + self.fee:
            return AgentDecision(summary="balance too low for transfer")

        cursor = self._cursor_by_agent.get(observation.profile.name, 0) % len(peers)
        recipient = peers[cursor]
        self._cursor_by_agent[observation.profile.name] = cursor + 1
        return AgentDecision(
            summary="{0} transfers funds to {1} when no better market trade is obvious".format(
                observation.profile.name,
                recipient.name,
            ),
            tool_calls=(
                ToolCall(
                    tool_name="send_transaction",
                    arguments={
                        "recipient": recipient.name,
                        "amount": self.amount,
                        "fee": self.fee,
                        "bundle_mode": self.bundle_mode,
                    },
                ),
            ),
        )


class CompositeController(AgentController):
    """Runs a list of scripted policies and merges their tool calls."""

    def __init__(self, controllers: List[AgentController]) -> None:
        self.controllers = list(controllers)

    def plan_turn(self, observation: AgentObservation) -> AgentDecision:
        summaries: List[str] = []
        tool_calls: List[ToolCall] = []
        for controller in self.controllers:
            decision = controller.plan_turn(observation)
            if decision.summary:
                summaries.append(decision.summary)
            tool_calls.extend(decision.tool_calls)
        return AgentDecision(summary="; ".join(summaries), tool_calls=tuple(tool_calls))
