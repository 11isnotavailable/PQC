from __future__ import annotations

import time
import unittest

from pq_bitedu.core.blockchain import Blockchain
from pq_bitedu.core.models import AuthBundle, Block, BlockHeader, Transaction, TxOutput
from pq_bitedu.core.merkle import merkle_root
from pq_bitedu.core.validation import ValidationError
from pq_bitedu.core.wallet import Wallet
from pq_bitedu.crypto.signature import EducationalMLDSASignature
from pq_bitedu.experiments import compare_bundle_modes
from pq_bitedu.node import Node


class BlockchainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.blockchain = Blockchain()
        self.node = Node(self.blockchain)
        self.default_scheme = self.blockchain.signature_schemes[self.blockchain.default_scheme_name]
        self.miner = Wallet("miner", signature_schemes=self.blockchain.signature_schemes)
        self.alice = Wallet("alice", signature_schemes=self.blockchain.signature_schemes)
        self.blockchain.create_genesis_block(self.miner.primary_pubkey_hash, data="genesis")
        reward_block = self.blockchain.mine_block(self.miner.primary_pubkey_hash, [], coinbase_data="reward")
        self.blockchain.add_block(reward_block)

    def test_default_signature_backend_is_handwritten_mldsa(self) -> None:
        self.assertIsInstance(self.default_scheme, EducationalMLDSASignature)
        self.assertEqual(self.default_scheme.implementation_name, "handwritten-edu")
        keypair = self.default_scheme.keygen()
        message = b"pq-bitedu signature roundtrip"
        signature = self.default_scheme.sign(keypair.private_key, message)
        self.assertTrue(self.default_scheme.verify(keypair.public_key, message, signature))
        self.assertFalse(self.default_scheme.verify(keypair.public_key, message + b"!", signature))

    def test_mining_and_transfer(self) -> None:
        payment = self.miner.create_transaction(
            self.blockchain,
            self.alice.primary_pubkey_hash,
            amount=60,
            fee=2,
        )
        self.node.submit_transaction(payment)
        self.node.mine_pending(self.miner.primary_pubkey_hash, coinbase_data="tx-block")
        self.assertEqual(self.alice.balance(self.blockchain), 60)
        self.assertGreaterEqual(self.miner.balance(self.blockchain), 38)

    def test_reward_halves_on_schedule(self) -> None:
        chain = Blockchain(halving_interval=2)
        miner = Wallet("halving-miner", signature_schemes=chain.signature_schemes)
        chain.create_genesis_block(miner.primary_pubkey_hash, data="genesis")
        first = chain.mine_block(miner.primary_pubkey_hash, [], coinbase_data="first")
        chain.add_block(first)
        second = chain.mine_block(miner.primary_pubkey_hash, [], coinbase_data="second")
        self.assertEqual(first.transactions[0].outputs[0].value, 50)
        self.assertEqual(second.transactions[0].outputs[0].value, 25)

    def test_difficulty_retargets_after_adjustment_window(self) -> None:
        chain = Blockchain(difficulty_adjustment_interval=2, target_block_time_seconds=10)
        miner = Wallet("difficulty-miner", signature_schemes=chain.signature_schemes)
        chain.create_genesis_block(miner.primary_pubkey_hash, data="genesis")
        first = chain.mine_block(miner.primary_pubkey_hash, [], coinbase_data="first")
        chain.add_block(first)
        second = chain.mine_block(miner.primary_pubkey_hash, [], coinbase_data="second")
        self.assertLess(second.header.target, first.header.target)
        self.assertGreater(chain.difficulty_ratio_for_target(second.header.target), 1.0)

    def test_soibs_collapses_same_owner_inputs(self) -> None:
        payment = self.miner.create_transaction(
            self.blockchain,
            self.alice.primary_pubkey_hash,
            amount=60,
            fee=2,
        )
        self.assertEqual(len(payment.inputs), 2)
        self.assertEqual(len(payment.auth_bundles), 1)
        self.assertEqual(payment.auth_bundles[0].input_indices, (0, 1))

    def test_per_input_mode_keeps_baseline_witness_shape(self) -> None:
        payment = self.miner.create_transaction(
            self.blockchain,
            self.alice.primary_pubkey_hash,
            amount=60,
            fee=2,
            bundle_mode="per_input",
        )
        self.assertEqual(len(payment.inputs), 2)
        self.assertEqual(len(payment.auth_bundles), 2)
        self.assertEqual(payment.auth_bundles[0].input_indices, (0,))
        self.assertEqual(payment.auth_bundles[1].input_indices, (1,))

    def test_bundle_mode_comparison_shows_soibs_saves_verifications(self) -> None:
        comparison = compare_bundle_modes(
            self.miner,
            self.blockchain,
            self.alice.primary_pubkey_hash,
            amount=60,
            fee=2,
        )
        self.assertEqual(comparison["soibs"].verification_count, 1)
        self.assertEqual(comparison["per_input"].verification_count, 2)
        self.assertLess(comparison["soibs"].tx_size, comparison["per_input"].tx_size)

    def test_tampered_transaction_is_rejected(self) -> None:
        payment = self.miner.create_transaction(
            self.blockchain,
            self.alice.primary_pubkey_hash,
            amount=60,
            fee=2,
        )
        tampered = payment.__class__(
            version=payment.version,
            inputs=payment.inputs,
            outputs=(payment.outputs[0].__class__(value=61, pubkey_hash=payment.outputs[0].pubkey_hash),)
            + payment.outputs[1:],
            locktime=payment.locktime,
            auth_bundles=payment.auth_bundles,
        )
        with self.assertRaises(ValidationError):
            self.node.submit_transaction(tampered)

    def test_public_key_hash_mismatch_is_rejected(self) -> None:
        payment = self.miner.create_transaction(
            self.blockchain,
            self.alice.primary_pubkey_hash,
            amount=60,
            fee=2,
        )
        forged_bundle = AuthBundle(
            scheme_name=payment.auth_bundles[0].scheme_name,
            public_key=self.alice.keys[self.alice.primary_pubkey_hash].public_key,
            input_indices=payment.auth_bundles[0].input_indices,
            signature=payment.auth_bundles[0].signature,
        )
        forged = Transaction(
            version=payment.version,
            inputs=payment.inputs,
            outputs=payment.outputs,
            locktime=payment.locktime,
            auth_bundles=(forged_bundle,),
        )
        with self.assertRaises(ValidationError):
            self.node.submit_transaction(forged)

    def test_forged_signature_is_rejected(self) -> None:
        payment = self.miner.create_transaction(
            self.blockchain,
            self.alice.primary_pubkey_hash,
            amount=60,
            fee=2,
        )
        forged_signature = payment.auth_bundles[0].signature[:-1] + b"x"
        forged_bundle = AuthBundle(
            scheme_name=payment.auth_bundles[0].scheme_name,
            public_key=payment.auth_bundles[0].public_key,
            input_indices=payment.auth_bundles[0].input_indices,
            signature=forged_signature,
        )
        forged = Transaction(
            version=payment.version,
            inputs=payment.inputs,
            outputs=payment.outputs,
            locktime=payment.locktime,
            auth_bundles=(forged_bundle,),
        )
        with self.assertRaises(ValidationError):
            self.node.submit_transaction(forged)

    def test_coinbase_overclaim_is_rejected(self) -> None:
        bad_coinbase = Transaction.coinbase(
            pubkey_hash=self.miner.primary_pubkey_hash,
            value=self.blockchain.base_reward + 1,
            data="overclaim",
        )
        parent_hash = self.blockchain.best_tip
        height = self.blockchain.blocks[parent_hash].height + 1
        merkle = merkle_root([bad_coinbase.txid])
        timestamp = int(time.time())
        nonce = 0
        while True:
            header = BlockHeader(
                version=1,
                prev_block_hash=parent_hash,
                merkle_root=merkle,
                timestamp=timestamp,
                target=self.blockchain.target,
                nonce=nonce,
                height=height,
            )
            if int(header.block_hash, 16) < self.blockchain.target:
                break
            nonce += 1
        forged = Block(header=header, transactions=(bad_coinbase,))
        with self.assertRaises(ValidationError):
            self.blockchain.add_block(forged)

    def test_longer_fork_becomes_best_chain(self) -> None:
        fork_base = self.blockchain.best_tip
        main_child = self.blockchain.mine_block(
            self.miner.primary_pubkey_hash,
            [],
            parent_hash=fork_base,
            coinbase_data="main-child",
        )
        self.blockchain.add_block(main_child)
        self.assertEqual(self.blockchain.best_tip, main_child.block_hash)

        fork_one = self.blockchain.mine_block(
            self.miner.primary_pubkey_hash,
            [],
            parent_hash=fork_base,
            coinbase_data="fork-1",
        )
        self.blockchain.add_block(fork_one)
        self.assertEqual(self.blockchain.best_tip, main_child.block_hash)

        fork_two = self.blockchain.mine_block(
            self.miner.primary_pubkey_hash,
            [],
            parent_hash=fork_one.block_hash,
            coinbase_data="fork-2",
        )
        self.blockchain.add_block(fork_two)
        self.assertEqual(self.blockchain.best_tip, fork_two.block_hash)


if __name__ == "__main__":
    unittest.main()
