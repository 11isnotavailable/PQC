"""Core blockchain implementation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..crypto.signature import (
    SignatureScheme,
    build_signature_schemes,
    default_scheme_name,
)
from .merkle import merkle_root
from .models import Block, BlockHeader, Transaction, TxOutput
from .validation import (
    UTXOSet,
    ValidationError,
    apply_transaction,
    block_work,
    validate_block,
    validate_transaction,
)


DEFAULT_TARGET = 1 << 248
GENESIS_PREV_HASH = "0" * 64
DEFAULT_HALVING_INTERVAL = 12
DEFAULT_DIFFICULTY_ADJUSTMENT_INTERVAL = 4
DEFAULT_TARGET_BLOCK_TIME_SECONDS = 1


@dataclass
class BlockRecord:
    block: Block
    parent_hash: Optional[str]
    height: int
    cumulative_work: int


class Blockchain:
    """Educational Bitcoin-like chain with pluggable PQ signatures."""

    def __init__(
        self,
        signature_schemes: Optional[Mapping[str, SignatureScheme]] = None,
        base_reward: int = 50,
        target: int = DEFAULT_TARGET,
        halving_interval: int = DEFAULT_HALVING_INTERVAL,
        difficulty_adjustment_interval: int = DEFAULT_DIFFICULTY_ADJUSTMENT_INTERVAL,
        target_block_time_seconds: int = DEFAULT_TARGET_BLOCK_TIME_SECONDS,
    ) -> None:
        if signature_schemes is None:
            signature_schemes = build_signature_schemes()
        self.signature_schemes: Dict[str, SignatureScheme] = dict(signature_schemes)
        self.default_scheme_name = default_scheme_name(self.signature_schemes)
        self.base_reward = base_reward
        self.target = target
        self.initial_target = target
        self.max_target = target
        self.halving_interval = max(1, halving_interval)
        self.difficulty_adjustment_interval = max(1, difficulty_adjustment_interval)
        self.target_block_time_seconds = max(1, target_block_time_seconds)
        self.blocks: Dict[str, BlockRecord] = {}
        self.best_tip: Optional[str] = None

    def create_genesis_block(self, miner_pubkey_hash: str, data: str = "genesis") -> Block:
        if self.best_tip is not None:
            raise RuntimeError("genesis block already exists")
        block = self.mine_block(miner_pubkey_hash, [], parent_hash=None, coinbase_data=data)
        self.add_block(block)
        return block

    def mine_block(
        self,
        miner_pubkey_hash: str,
        transactions: Sequence[Transaction],
        parent_hash: Optional[str] = None,
        coinbase_data: str = "",
    ) -> Block:
        parent_hash = self.best_tip if parent_hash is None else parent_hash
        parent_height = -1 if parent_hash is None else self.blocks[parent_hash].height
        parent_utxo = self._build_utxo_set(parent_hash)
        next_height = parent_height + 1
        target = self.target_for_next_block(parent_hash)
        subsidy = self.reward_for_height(next_height)

        included_transactions: List[Transaction] = []
        total_fees = 0
        working_utxo = dict(parent_utxo)
        for transaction in transactions:
            validated = validate_transaction(
                transaction,
                working_utxo,
                self.signature_schemes,
                allow_coinbase=False,
            )
            total_fees += validated.fee
            apply_transaction(validated, working_utxo)
            included_transactions.append(transaction)

        coinbase = Transaction.coinbase(
            pubkey_hash=miner_pubkey_hash,
            value=subsidy + total_fees,
            data=coinbase_data or "coinbase",
        )
        block_transactions = (coinbase,) + tuple(included_transactions)
        merkle = merkle_root(transaction.txid for transaction in block_transactions)
        nonce = 0
        timestamp = int(time.time())
        while True:
            header = BlockHeader(
                version=1,
                prev_block_hash=GENESIS_PREV_HASH if parent_hash is None else parent_hash,
                merkle_root=merkle,
                timestamp=timestamp,
                target=target,
                nonce=nonce,
                height=next_height,
            )
            if int(header.block_hash, 16) < target:
                return Block(header=header, transactions=block_transactions)
            nonce += 1

    def add_block(self, block: Block) -> str:
        parent_hash = None if block.header.prev_block_hash == GENESIS_PREV_HASH and block.header.height == 0 else block.header.prev_block_hash
        if parent_hash is not None and parent_hash not in self.blocks:
            raise ValidationError("parent block not known")
        if self.best_tip is None and block.header.height != 0:
            raise ValidationError("first block must be genesis")
        if self.best_tip is not None and block.block_hash in self.blocks:
            raise ValidationError("duplicate block")

        parent_record = None if parent_hash is None else self.blocks[parent_hash]
        utxo_set = self._build_utxo_set(parent_hash)
        previous_height = -1 if parent_record is None else parent_record.height
        validate_block(
            block,
            utxo_set,
            self.signature_schemes,
            self.reward_for_height(block.header.height),
            previous_height=previous_height,
            expected_target=self.target_for_next_block(parent_hash),
        )
        cumulative_work = block_work(block.header.target)
        if parent_record is not None:
            cumulative_work += parent_record.cumulative_work

        record = BlockRecord(
            block=block,
            parent_hash=parent_hash,
            height=block.header.height,
            cumulative_work=cumulative_work,
        )
        self.blocks[block.block_hash] = record
        if self.best_tip is None:
            self.best_tip = block.block_hash
        else:
            best_record = self.blocks[self.best_tip]
            if (
                record.cumulative_work > best_record.cumulative_work
                or (
                    record.cumulative_work == best_record.cumulative_work
                    and record.height > best_record.height
                )
            ):
                self.best_tip = block.block_hash
        return block.block_hash

    def best_height(self) -> int:
        if self.best_tip is None:
            return -1
        return self.blocks[self.best_tip].height

    def best_chain(self) -> List[Block]:
        if self.best_tip is None:
            return []
        ordered: List[Block] = []
        current_hash: Optional[str] = self.best_tip
        while current_hash is not None:
            record = self.blocks[current_hash]
            ordered.append(record.block)
            current_hash = record.parent_hash
        ordered.reverse()
        return ordered

    def best_utxo_set(self) -> Dict[Tuple[str, int], TxOutput]:
        return self._build_utxo_set(self.best_tip)

    def balance_for(self, pubkey_hash: str) -> int:
        return sum(
            tx_output.value
            for tx_output in self.best_utxo_set().values()
            if tx_output.pubkey_hash == pubkey_hash
        )

    def reward_for_height(self, height: int) -> int:
        if height < 0:
            raise ValueError("height must be non-negative")
        era = height // self.halving_interval
        return self.base_reward >> era

    def target_for_next_block(self, parent_hash: Optional[str]) -> int:
        if parent_hash is None:
            return self.initial_target
        parent_record = self.blocks[parent_hash]
        next_height = parent_record.height + 1
        parent_target = parent_record.block.header.target
        if (
            self.difficulty_adjustment_interval <= 1
            or next_height == 0
            or next_height % self.difficulty_adjustment_interval != 0
        ):
            return parent_target

        window_hashes = self._ancestor_hashes(parent_hash, self.difficulty_adjustment_interval)
        if len(window_hashes) < self.difficulty_adjustment_interval:
            return parent_target
        oldest_record = self.blocks[window_hashes[-1]]
        actual_span = max(
            1,
            parent_record.block.header.timestamp - oldest_record.block.header.timestamp,
        )
        expected_span = self.difficulty_adjustment_interval * self.target_block_time_seconds
        adjustment = actual_span / float(expected_span)
        adjustment = min(4.0, max(0.25, adjustment))
        next_target = int(parent_target * adjustment)
        return max(1, min(self.max_target, next_target))

    def difficulty_ratio_for_target(self, target: int) -> float:
        return round(self.initial_target / float(max(1, target)), 4)

    def difficulty_ratio_for_height(self, height: int) -> float:
        block = self.best_chain()[height]
        return self.difficulty_ratio_for_target(block.header.target)

    def current_difficulty_ratio(self) -> float:
        if self.best_tip is None:
            return 1.0
        best_target = self.blocks[self.best_tip].block.header.target
        return self.difficulty_ratio_for_target(best_target)

    def expected_hash_attempts_for_target(self, target: int) -> int:
        return max(1, ((1 << 256) // max(1, target)))

    def _build_utxo_set(self, tip_hash: Optional[str]) -> Dict[Tuple[str, int], TxOutput]:
        utxo_set: Dict[Tuple[str, int], TxOutput] = {}
        if tip_hash is None:
            return utxo_set
        chain_hashes: List[str] = []
        current_hash: Optional[str] = tip_hash
        while current_hash is not None:
            chain_hashes.append(current_hash)
            current_hash = self.blocks[current_hash].parent_hash
        chain_hashes.reverse()

        for block_hash in chain_hashes:
            block = self.blocks[block_hash].block
            for transaction in block.transactions:
                if not transaction.is_coinbase():
                    for tx_input in transaction.inputs:
                        del utxo_set[(tx_input.prev_txid, tx_input.prev_vout)]
                for output_index, tx_output in enumerate(transaction.outputs):
                    utxo_set[(transaction.txid, output_index)] = tx_output
        return utxo_set

    def _ancestor_hashes(self, tip_hash: str, limit: int) -> List[str]:
        hashes: List[str] = []
        current_hash: Optional[str] = tip_hash
        while current_hash is not None and len(hashes) < limit:
            hashes.append(current_hash)
            current_hash = self.blocks[current_hash].parent_hash
        return hashes
