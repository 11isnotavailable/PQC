"""Dataclasses for transactions and blocks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..crypto.hashing import hash_hex
from ..serialization import canonical_json_bytes


COINBASE_TXID = "0" * 64


@dataclass(frozen=True)
class TxInput:
    prev_txid: str
    prev_vout: int
    sequence: int = 0xFFFFFFFF
    coinbase_data: Optional[str] = None

    def is_coinbase(self) -> bool:
        return self.prev_txid == COINBASE_TXID and self.prev_vout == -1

    def to_dict(self) -> Dict[str, object]:
        return {
            "prev_txid": self.prev_txid,
            "prev_vout": self.prev_vout,
            "sequence": self.sequence,
            "coinbase_data": self.coinbase_data,
        }


@dataclass(frozen=True)
class TxOutput:
    value: int
    pubkey_hash: str

    def to_dict(self) -> Dict[str, object]:
        return {"value": self.value, "pubkey_hash": self.pubkey_hash}


@dataclass(frozen=True)
class AuthBundle:
    scheme_name: str
    public_key: bytes
    input_indices: Tuple[int, ...]
    signature: bytes

    def to_dict(self) -> Dict[str, object]:
        return {
            "scheme_name": self.scheme_name,
            "public_key": self.public_key,
            "input_indices": list(self.input_indices),
            "signature": self.signature,
        }


@dataclass(frozen=True)
class Transaction:
    version: int
    inputs: Tuple[TxInput, ...]
    outputs: Tuple[TxOutput, ...]
    locktime: int = 0
    auth_bundles: Tuple[AuthBundle, ...] = field(default_factory=tuple)

    def is_coinbase(self) -> bool:
        return len(self.inputs) == 1 and self.inputs[0].is_coinbase()

    def to_dict(self, include_auth: bool = True, include_signatures: bool = True) -> Dict[str, object]:
        payload = {
            "version": self.version,
            "inputs": [tx_input.to_dict() for tx_input in self.inputs],
            "outputs": [tx_output.to_dict() for tx_output in self.outputs],
            "locktime": self.locktime,
        }
        if include_auth:
            payload["auth_bundles"] = [
                {
                    "scheme_name": bundle.scheme_name,
                    "public_key": bundle.public_key,
                    "input_indices": list(bundle.input_indices),
                    "signature": bundle.signature if include_signatures else b"",
                }
                for bundle in self.auth_bundles
            ]
        return payload

    def serialize(self) -> bytes:
        return canonical_json_bytes(self.to_dict(include_auth=True, include_signatures=True))

    @property
    def txid(self) -> str:
        return hash_hex(self.serialize())

    def signing_message(
        self,
        input_indices: Sequence[int],
        referenced_outputs: Sequence[TxOutput],
    ) -> bytes:
        ordered_references = [
            {
                "input_index": input_index,
                "value": referenced_output.value,
                "pubkey_hash": referenced_output.pubkey_hash,
            }
            for input_index, referenced_output in sorted(
                zip(input_indices, referenced_outputs), key=lambda item: item[0]
            )
        ]
        payload = {
            "tx": self.to_dict(include_auth=False),
            "bundle_input_indices": list(sorted(input_indices)),
            "referenced_outputs": ordered_references,
        }
        return canonical_json_bytes(payload)

    @staticmethod
    def coinbase(pubkey_hash: str, value: int, data: str) -> "Transaction":
        return Transaction(
            version=1,
            inputs=(TxInput(prev_txid=COINBASE_TXID, prev_vout=-1, coinbase_data=data),),
            outputs=(TxOutput(value=value, pubkey_hash=pubkey_hash),),
            locktime=0,
            auth_bundles=tuple(),
        )


@dataclass(frozen=True)
class BlockHeader:
    version: int
    prev_block_hash: str
    merkle_root: str
    timestamp: int
    target: int
    nonce: int
    height: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "version": self.version,
            "prev_block_hash": self.prev_block_hash,
            "merkle_root": self.merkle_root,
            "timestamp": self.timestamp,
            "target": self.target,
            "nonce": self.nonce,
            "height": self.height,
        }

    def serialize(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def block_hash(self) -> str:
        return hash_hex(self.serialize())


@dataclass(frozen=True)
class Block:
    header: BlockHeader
    transactions: Tuple[Transaction, ...]

    def to_dict(self) -> Dict[str, object]:
        return {
            "header": self.header.to_dict(),
            "transactions": [transaction.to_dict() for transaction in self.transactions],
        }

    @property
    def block_hash(self) -> str:
        return self.header.block_hash
