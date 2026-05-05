"""Simple single-process node wrapper."""

from __future__ import annotations

from typing import List

from .core.blockchain import Blockchain
from .core.models import Block, Transaction
from .core.validation import ValidationError, validate_transaction, apply_transaction
from .core.wallet import Wallet


class Node:
    def __init__(self, blockchain: Blockchain) -> None:
        self.blockchain = blockchain
        self.mempool: List[Transaction] = []

    def submit_transaction(self, transaction: Transaction) -> None:
        working_utxo = self.blockchain.best_utxo_set()
        for existing in self.mempool:
            validated_existing = validate_transaction(
                existing,
                working_utxo,
                self.blockchain.signature_schemes,
                allow_coinbase=False,
            )
            apply_transaction(validated_existing, working_utxo)

        validate_transaction(
            transaction,
            working_utxo,
            self.blockchain.signature_schemes,
            allow_coinbase=False,
        )
        self.mempool.append(transaction)

    def mine_pending(self, miner_pubkey_hash: str, coinbase_data: str = "mined") -> Block:
        block = self.blockchain.mine_block(
            miner_pubkey_hash=miner_pubkey_hash,
            transactions=self.mempool,
            coinbase_data=coinbase_data,
        )
        self.blockchain.add_block(block)
        self.mempool = []
        return block
