"""Toy attacker that withholds a private fork and releases it later."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence

from ..core.blockchain import Blockchain
from ..core.models import Block, Transaction
from ..core.wallet import Wallet
from ..node import Node
from .network import SimpleNetwork, clone_blockchain


@dataclass
class PrivateForkAttacker:
    """Maintains a hidden fork that can later be published to the network."""

    name: str
    wallet: Wallet
    private_chain: Blockchain
    private_node: Node
    hidden_blocks: List[Block] = field(default_factory=list)

    @classmethod
    def from_public_chain(cls, name: str, wallet: Wallet, blockchain: Blockchain) -> "PrivateForkAttacker":
        private_chain = clone_blockchain(blockchain)
        return cls(
            name=name,
            wallet=wallet,
            private_chain=private_chain,
            private_node=Node(private_chain),
        )

    def create_transaction(self, recipient_pubkey_hash: str, amount: int, fee: int = 1) -> Transaction:
        return self.wallet.create_transaction(
            self.private_chain,
            recipient_pubkey_hash=recipient_pubkey_hash,
            amount=amount,
            fee=fee,
        )

    def mine_hidden_block(self, transactions: Sequence[Transaction], coinbase_data: str) -> Block:
        for transaction in transactions:
            self.private_node.submit_transaction(transaction)
        block = self.private_node.mine_pending(self.wallet.primary_pubkey_hash, coinbase_data=coinbase_data)
        self.hidden_blocks.append(block)
        return block

    def release_hidden_blocks(
        self,
        network: SimpleNetwork,
        round_label: str,
        recipients: Sequence[str],
    ) -> List[str]:
        delivered_hashes: List[str] = []
        for block in self.hidden_blocks:
            network.broadcast_block(
                origin=self.name,
                block=block,
                recipients=recipients,
                round_label=round_label,
            )
            delivered_hashes.append(block.block_hash)
        self.hidden_blocks.clear()
        return delivered_hashes
