"""Wallet and transaction construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..crypto.signature import SignatureScheme, build_signature_schemes, default_scheme_name
from .blockchain import Blockchain
from .models import AuthBundle, Transaction, TxInput, TxOutput
from .validation import ValidationError, pubkey_hash


@dataclass
class WalletKey:
    label: str
    scheme_name: str
    public_key: bytes
    private_key: object
    pubkey_hash: str


class Wallet:
    """Stateful wallet that can create fresh addresses and sign SOIBS bundles."""

    def __init__(
        self,
        name: str,
        signature_scheme: Optional[SignatureScheme] = None,
        signature_schemes: Optional[Mapping[str, SignatureScheme]] = None,
    ) -> None:
        self.name = name
        if signature_scheme is not None:
            self.signature_schemes = {signature_scheme.name: signature_scheme}
            self.default_scheme_name = signature_scheme.name
        else:
            self.signature_schemes = dict(signature_schemes or build_signature_schemes())
            self.default_scheme_name = default_scheme_name(self.signature_schemes)
        self.keys: Dict[str, WalletKey] = {}
        self._key_counter = 0
        self.primary_pubkey_hash = self.new_address(label="primary")

    def new_address(self, label: Optional[str] = None, scheme_name: Optional[str] = None) -> str:
        scheme_name = scheme_name or self.default_scheme_name
        scheme = self.signature_schemes[scheme_name]
        keypair = scheme.keygen()
        key_hash = pubkey_hash(keypair.public_key)
        key_label = label or "addr-{0}".format(self._key_counter)
        self._key_counter += 1
        self.keys[key_hash] = WalletKey(
            label=key_label,
            scheme_name=scheme.name,
            public_key=keypair.public_key,
            private_key=keypair.private_key,
            pubkey_hash=key_hash,
        )
        return key_hash

    def known_pubkey_hashes(self) -> List[str]:
        return list(self.keys.keys())

    def balance(self, blockchain: Blockchain) -> int:
        return sum(
            tx_output.value
            for tx_output in blockchain.best_utxo_set().values()
            if tx_output.pubkey_hash in self.keys
        )

    def balance_from_utxo_view(self, utxo_view: Mapping[Tuple[str, int], TxOutput]) -> int:
        return sum(
            tx_output.value
            for tx_output in utxo_view.values()
            if tx_output.pubkey_hash in self.keys
        )

    def max_spendable_amount(
        self,
        blockchain: Blockchain,
        fee: int = 1,
        utxo_view: Optional[Mapping[Tuple[str, int], TxOutput]] = None,
    ) -> int:
        available = self.balance_from_utxo_view(utxo_view or blockchain.best_utxo_set())
        return max(0, available - fee)

    def create_transaction(
        self,
        blockchain: Blockchain,
        recipient_pubkey_hash: str,
        amount: int,
        fee: int = 1,
        change_pubkey_hash: Optional[str] = None,
        bundle_mode: str = "soibs",
        utxo_view: Optional[Mapping[Tuple[str, int], TxOutput]] = None,
    ) -> Transaction:
        required = amount + fee
        available_utxos = [
            (outpoint, tx_output)
            for outpoint, tx_output in (utxo_view or blockchain.best_utxo_set()).items()
            if tx_output.pubkey_hash in self.keys
        ]
        if not available_utxos:
            raise ValidationError("wallet has no spendable UTXOs")

        selected: List[Tuple[Tuple[str, int], TxOutput]] = []
        running_total = 0
        for outpoint, tx_output in sorted(available_utxos, key=lambda item: item[1].value):
            selected.append((outpoint, tx_output))
            running_total += tx_output.value
            if running_total >= required:
                break

        if running_total < required:
            raise ValidationError("wallet balance insufficient")

        tx_inputs = tuple(
            TxInput(prev_txid=outpoint[0], prev_vout=outpoint[1]) for outpoint, _tx_output in selected
        )
        tx_outputs: List[TxOutput] = [TxOutput(value=amount, pubkey_hash=recipient_pubkey_hash)]
        change = running_total - required
        if change > 0:
            change_hash = change_pubkey_hash or self.new_address(label="change")
            tx_outputs.append(TxOutput(value=change, pubkey_hash=change_hash))

        unsigned_transaction = Transaction(
            version=1,
            inputs=tx_inputs,
            outputs=tuple(tx_outputs),
            locktime=0,
            auth_bundles=tuple(),
        )
        referenced_outputs_by_index: Dict[int, TxOutput] = {}
        for input_index, (_outpoint, tx_output) in enumerate(selected):
            referenced_outputs_by_index[input_index] = tx_output
        return self.authorize_transaction(
            unsigned_transaction,
            referenced_outputs_by_index,
            bundle_mode=bundle_mode,
        )

    def authorize_transaction(
        self,
        unsigned_transaction: Transaction,
        referenced_outputs_by_index: Mapping[int, TxOutput],
        bundle_mode: str = "soibs",
    ) -> Transaction:
        if bundle_mode not in {"soibs", "per_input"}:
            raise ValueError("bundle_mode must be 'soibs' or 'per_input'")

        if bundle_mode == "soibs":
            owner_to_indices: Dict[str, List[int]] = {}
            for input_index, tx_output in referenced_outputs_by_index.items():
                owner_to_indices.setdefault(tx_output.pubkey_hash, []).append(input_index)
            groups = [tuple(sorted(indices)) for indices in owner_to_indices.values()]
        else:
            groups = [(input_index,) for input_index in sorted(referenced_outputs_by_index)]

        auth_bundles: List[AuthBundle] = []
        for ordered_indices in sorted(groups, key=lambda group: group[0]):
            owner_hash = referenced_outputs_by_index[ordered_indices[0]].pubkey_hash
            wallet_key = self.keys[owner_hash]
            referenced_outputs = [referenced_outputs_by_index[index] for index in ordered_indices]
            message = unsigned_transaction.signing_message(ordered_indices, referenced_outputs)
            scheme = self.signature_schemes[wallet_key.scheme_name]
            signature = scheme.sign(wallet_key.private_key, message)
            auth_bundles.append(
                AuthBundle(
                    scheme_name=wallet_key.scheme_name,
                    public_key=wallet_key.public_key,
                    input_indices=ordered_indices,
                    signature=signature,
                )
            )

        return Transaction(
            version=unsigned_transaction.version,
            inputs=unsigned_transaction.inputs,
            outputs=unsigned_transaction.outputs,
            locktime=unsigned_transaction.locktime,
            auth_bundles=tuple(auth_bundles),
        )
