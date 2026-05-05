"""Transaction and block validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, MutableMapping, Sequence, Tuple

from ..crypto.hashing import hash_hex
from ..crypto.signature import SignatureScheme
from .merkle import merkle_root
from .models import AuthBundle, Block, COINBASE_TXID, Transaction, TxOutput


MAX_HASH = (1 << 256) - 1


class ValidationError(Exception):
    pass


UTXOSet = MutableMapping[Tuple[str, int], TxOutput]


@dataclass
class ValidatedTransaction:
    fee: int
    spent_outpoints: List[Tuple[str, int]]
    created_outputs: List[Tuple[Tuple[str, int], TxOutput]]


def pubkey_hash(public_key: bytes) -> str:
    return hash_hex(public_key)


def validate_transaction(
    transaction: Transaction,
    utxo_set: Mapping[Tuple[str, int], TxOutput],
    signature_schemes: Mapping[str, SignatureScheme],
    allow_coinbase: bool = False,
) -> ValidatedTransaction:
    if not transaction.inputs:
        raise ValidationError("transaction has no inputs")
    if not transaction.outputs:
        raise ValidationError("transaction has no outputs")
    if any(tx_output.value <= 0 for tx_output in transaction.outputs):
        raise ValidationError("transaction outputs must all be positive")

    if transaction.is_coinbase():
        if not allow_coinbase:
            raise ValidationError("coinbase transaction not allowed here")
        if len(transaction.auth_bundles) != 0:
            raise ValidationError("coinbase transaction cannot carry auth bundles")
        return ValidatedTransaction(
            fee=0,
            spent_outpoints=[],
            created_outputs=[((transaction.txid, index), tx_output) for index, tx_output in enumerate(transaction.outputs)],
        )

    if any(tx_input.is_coinbase() for tx_input in transaction.inputs):
        raise ValidationError("coinbase input found in normal transaction")

    seen_inputs = set()
    referenced_outputs: List[TxOutput] = []
    referenced_outpoints: List[Tuple[str, int]] = []
    input_total = 0

    for tx_input in transaction.inputs:
        outpoint = (tx_input.prev_txid, tx_input.prev_vout)
        if outpoint in seen_inputs:
            raise ValidationError("duplicate input within transaction")
        seen_inputs.add(outpoint)
        referenced_output = utxo_set.get(outpoint)
        if referenced_output is None:
            raise ValidationError("transaction references missing UTXO")
        referenced_outpoints.append(outpoint)
        referenced_outputs.append(referenced_output)
        input_total += referenced_output.value

    covered_indices = set()
    for bundle in transaction.auth_bundles:
        if not bundle.input_indices:
            raise ValidationError("auth bundle cannot be empty")
        if bundle.scheme_name not in signature_schemes:
            raise ValidationError("unknown signature scheme in auth bundle")

        bundle_indices = tuple(sorted(bundle.input_indices))
        if len(set(bundle_indices)) != len(bundle_indices):
            raise ValidationError("duplicate input index in auth bundle")

        if bundle_indices[0] < 0 or bundle_indices[-1] >= len(transaction.inputs):
            raise ValidationError("auth bundle input index out of range")

        if any(index in covered_indices for index in bundle_indices):
            raise ValidationError("input covered by multiple auth bundles")

        bundle_outputs = [referenced_outputs[index] for index in bundle_indices]
        owner_hash = bundle_outputs[0].pubkey_hash
        if any(output.pubkey_hash != owner_hash for output in bundle_outputs):
            raise ValidationError("SOIBS bundle mixes multiple owners")
        if pubkey_hash(bundle.public_key) != owner_hash:
            raise ValidationError("bundle public key hash mismatch")

        message = transaction.signing_message(bundle_indices, bundle_outputs)
        scheme = signature_schemes[bundle.scheme_name]
        if not scheme.verify(bundle.public_key, message, bundle.signature):
            raise ValidationError("bundle signature verification failed")
        covered_indices.update(bundle_indices)

    if covered_indices != set(range(len(transaction.inputs))):
        raise ValidationError("not all inputs are covered by auth bundles")

    output_total = sum(tx_output.value for tx_output in transaction.outputs)
    fee = input_total - output_total
    if fee < 0:
        raise ValidationError("transaction overspends inputs")

    return ValidatedTransaction(
        fee=fee,
        spent_outpoints=referenced_outpoints,
        created_outputs=[((transaction.txid, index), tx_output) for index, tx_output in enumerate(transaction.outputs)],
    )


def apply_transaction(validated_transaction: ValidatedTransaction, utxo_set: UTXOSet) -> None:
    for outpoint in validated_transaction.spent_outpoints:
        del utxo_set[outpoint]
    for outpoint, tx_output in validated_transaction.created_outputs:
        utxo_set[outpoint] = tx_output


def block_work(target: int) -> int:
    return MAX_HASH // max(1, target)


def validate_block(
    block: Block,
    utxo_set: UTXOSet,
    signature_schemes: Mapping[str, SignatureScheme],
    base_reward: int,
    previous_height: int,
    expected_target: int,
) -> int:
    if not block.transactions:
        raise ValidationError("block must include at least one transaction")
    if block.header.height != previous_height + 1:
        raise ValidationError("block height does not extend parent height")
    if merkle_root(transaction.txid for transaction in block.transactions) != block.header.merkle_root:
        raise ValidationError("merkle root mismatch")
    if block.header.target != expected_target:
        raise ValidationError("block target does not match expected difficulty")
    if int(block.block_hash, 16) >= block.header.target:
        raise ValidationError("block does not satisfy PoW target")

    first_transaction = block.transactions[0]
    if not first_transaction.is_coinbase():
        raise ValidationError("first transaction must be coinbase")
    if sum(1 for transaction in block.transactions if transaction.is_coinbase()) != 1:
        raise ValidationError("block may contain only one coinbase transaction")

    working_utxo = dict(utxo_set)
    total_fees = 0
    for transaction in block.transactions[1:]:
        validated = validate_transaction(transaction, working_utxo, signature_schemes, allow_coinbase=False)
        total_fees += validated.fee
        apply_transaction(validated, working_utxo)

    coinbase_validated = validate_transaction(
        first_transaction,
        working_utxo,
        signature_schemes,
        allow_coinbase=True,
    )
    coinbase_value = sum(tx_output.value for tx_output in first_transaction.outputs)
    if coinbase_value > base_reward + total_fees:
        raise ValidationError("coinbase claims more than reward plus fees")
    apply_transaction(coinbase_validated, working_utxo)

    utxo_set.clear()
    utxo_set.update(working_utxo)
    return total_fees
