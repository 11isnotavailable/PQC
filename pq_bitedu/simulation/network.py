"""Toy multi-node network primitives for course demos."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from ..core.blockchain import Blockchain
from ..core.models import Block, Transaction
from ..core.validation import ValidationError
from ..core.wallet import Wallet
from ..node import Node


def clone_blockchain(source: Blockchain) -> Blockchain:
    """Clone chain history into a fresh Blockchain instance."""
    cloned = Blockchain(
        signature_schemes=source.signature_schemes,
        base_reward=source.base_reward,
        target=source.initial_target,
        halving_interval=source.halving_interval,
        difficulty_adjustment_interval=source.difficulty_adjustment_interval,
        target_block_time_seconds=source.target_block_time_seconds,
    )
    for block in source.best_chain():
        cloned.add_block(block)
    return cloned


@dataclass
class NetworkEvent:
    round_label: str
    event_type: str
    actor: str
    detail: str
    payload: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "round_label": self.round_label,
            "event_type": self.event_type,
            "actor": self.actor,
            "detail": self.detail,
            "payload": dict(self.payload),
        }


@dataclass
class NetworkNodeState:
    name: str
    wallet: Wallet
    blockchain: Blockchain
    node: Node

    @property
    def balance(self) -> int:
        return self.wallet.balance(self.blockchain)


class SimpleNetwork:
    """Single-process network that can replay blocks across several nodes."""

    def __init__(self) -> None:
        self.nodes: Dict[str, NetworkNodeState] = {}
        self.events: List[NetworkEvent] = []

    def register_node(self, name: str, wallet: Wallet, blockchain: Blockchain) -> NetworkNodeState:
        state = NetworkNodeState(name=name, wallet=wallet, blockchain=blockchain, node=Node(blockchain))
        self.nodes[name] = state
        return state

    def log(
        self,
        round_label: str,
        event_type: str,
        actor: str,
        detail: str,
        payload: Optional[Mapping[str, object]] = None,
    ) -> None:
        self.events.append(
            NetworkEvent(
                round_label=round_label,
                event_type=event_type,
                actor=actor,
                detail=detail,
                payload=dict(payload or {}),
            )
        )

    def submit_transaction(
        self,
        origin: str,
        transaction: Transaction,
        recipients: Sequence[str],
        round_label: str,
    ) -> List[str]:
        accepted: List[str] = []
        for recipient in recipients:
            try:
                self.nodes[recipient].node.submit_transaction(transaction)
                accepted.append(recipient)
            except ValidationError:
                continue
        self.log(
            round_label,
            "transaction_broadcast",
            origin,
            "广播交易到若干节点",
            {
                "txid": transaction.txid,
                "accepted_by": accepted,
                "recipient_count": len(recipients),
            },
        )
        return accepted

    def mine_pending(self, miner_name: str, round_label: str, coinbase_data: str) -> Block:
        state = self.nodes[miner_name]
        block = state.node.mine_pending(state.wallet.primary_pubkey_hash, coinbase_data=coinbase_data)
        self.log(
            round_label,
            "block_mined",
            miner_name,
            "节点打包待确认交易并出块",
            {
                "block_hash": block.block_hash,
                "height": block.header.height,
                "tx_count": len(block.transactions),
            },
        )
        return block

    def broadcast_block(
        self,
        origin: str,
        block: Block,
        recipients: Optional[Iterable[str]],
        round_label: str,
    ) -> List[str]:
        delivered: List[str] = []
        target_names = list(recipients) if recipients is not None else list(self.nodes.keys())
        included_txids = {transaction.txid for transaction in block.transactions}
        for recipient in target_names:
            state = self.nodes[recipient]
            if recipient == origin:
                if block.block_hash not in state.blockchain.blocks:
                    try:
                        state.blockchain.add_block(block)
                    except ValidationError:
                        continue
            else:
                try:
                    state.blockchain.add_block(block)
                except ValidationError:
                    continue
            state.node.mempool = [
                transaction
                for transaction in state.node.mempool
                if transaction.txid not in included_txids
            ]
            delivered.append(recipient)
        self.log(
            round_label,
            "block_broadcast",
            origin,
            "向网络广播新区块",
            {
                "block_hash": block.block_hash,
                "height": block.header.height,
                "recipients": delivered,
            },
        )
        return delivered

    def balances(self) -> Dict[str, int]:
        return {name: state.balance for name, state in self.nodes.items()}

    def best_heights(self) -> Dict[str, int]:
        return {name: state.blockchain.best_height() for name, state in self.nodes.items()}

    def best_tips(self) -> Dict[str, Optional[str]]:
        return {name: state.blockchain.best_tip for name, state in self.nodes.items()}

    def snapshot(self) -> Dict[str, object]:
        return {
            "balances": self.balances(),
            "best_heights": self.best_heights(),
            "best_tips": self.best_tips(),
            "events": [event.to_dict() for event in self.events],
        }
