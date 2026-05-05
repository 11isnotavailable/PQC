"""Minimal runnable demo for the PQ-BitEdu base chain."""

from __future__ import annotations

from .core.blockchain import Blockchain
from .core.wallet import Wallet
from .experiments import compare_bundle_modes
from .node import Node


def main() -> None:
    blockchain = Blockchain()
    node = Node(blockchain)
    default_scheme = blockchain.signature_schemes[blockchain.default_scheme_name]

    miner = Wallet("miner", signature_schemes=blockchain.signature_schemes)
    alice = Wallet("alice", signature_schemes=blockchain.signature_schemes)
    bob = Wallet("bob", signature_schemes=blockchain.signature_schemes)

    mining_address = miner.primary_pubkey_hash
    genesis = blockchain.create_genesis_block(mining_address, data="genesis")
    print("genesis:", genesis.block_hash[:16], "height=", blockchain.best_height())
    print("default signature scheme:", blockchain.default_scheme_name)
    print("signature backend:", getattr(default_scheme, "implementation_name", type(default_scheme).__name__))

    second_block = blockchain.mine_block(mining_address, [], coinbase_data="second-reward")
    blockchain.add_block(second_block)
    print("second:", second_block.block_hash[:16], "height=", blockchain.best_height())
    print("miner balance after rewards:", miner.balance(blockchain))

    comparison = compare_bundle_modes(
        miner,
        blockchain,
        alice.primary_pubkey_hash,
        amount=60,
        fee=2,
    )
    print(
        "auth comparison:",
        {
            name: {
                "bundles": stats.auth_bundle_count,
                "verify_calls": stats.verification_count,
                "tx_size": stats.tx_size,
            }
            for name, stats in comparison.items()
        },
    )

    pay_alice = miner.create_transaction(blockchain, alice.primary_pubkey_hash, amount=60, fee=2)
    node.submit_transaction(pay_alice)
    mined = node.mine_pending(miner.primary_pubkey_hash, coinbase_data="include-payment")
    print("payment block:", mined.block_hash[:16], "bundles=", len(pay_alice.auth_bundles))
    print("first bundle covers inputs:", list(pay_alice.auth_bundles[0].input_indices))
    print("balances:", {"miner": miner.balance(blockchain), "alice": alice.balance(blockchain)})

    pay_bob = alice.create_transaction(blockchain, bob.primary_pubkey_hash, amount=20, fee=1)
    node.submit_transaction(pay_bob)
    node.mine_pending(miner.primary_pubkey_hash, coinbase_data="include-second-payment")
    print("final balances:", {"miner": miner.balance(blockchain), "alice": alice.balance(blockchain), "bob": bob.balance(blockchain)})


if __name__ == "__main__":
    main()
