"""Small helpers for measurements and document-aligned experiments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping

from .core.blockchain import Blockchain
from .core.models import Transaction, TxOutput
from .core.wallet import Wallet


@dataclass(frozen=True)
class TransactionAuthStats:
    tx_size: int
    auth_bundle_count: int
    verification_count: int
    public_key_bytes: int
    signature_bytes: int


def transaction_auth_stats(
    transaction: Transaction,
    signature_schemes: Mapping[str, object],
) -> TransactionAuthStats:
    public_key_bytes = 0
    signature_bytes = 0
    for bundle in transaction.auth_bundles:
        scheme = signature_schemes[bundle.scheme_name]
        public_key_bytes += scheme.estimate_public_key_size(bundle.public_key)
        signature_bytes += scheme.estimate_signature_size(bundle.signature)
    return TransactionAuthStats(
        tx_size=len(transaction.serialize()),
        auth_bundle_count=len(transaction.auth_bundles),
        verification_count=len(transaction.auth_bundles),
        public_key_bytes=public_key_bytes,
        signature_bytes=signature_bytes,
    )


def compare_bundle_modes(
    wallet: Wallet,
    blockchain: Blockchain,
    recipient_pubkey_hash: str,
    amount: int,
    fee: int = 1,
) -> Dict[str, TransactionAuthStats]:
    change_pubkey_hash = wallet.new_address(label="comparison-change")
    transactions = {
        "soibs": wallet.create_transaction(
            blockchain,
            recipient_pubkey_hash,
            amount=amount,
            fee=fee,
            change_pubkey_hash=change_pubkey_hash,
            bundle_mode="soibs",
        ),
        "per_input": wallet.create_transaction(
            blockchain,
            recipient_pubkey_hash,
            amount=amount,
            fee=fee,
            change_pubkey_hash=change_pubkey_hash,
            bundle_mode="per_input",
        ),
    }
    return {
        name: transaction_auth_stats(transaction, blockchain.signature_schemes)
        for name, transaction in transactions.items()
    }
