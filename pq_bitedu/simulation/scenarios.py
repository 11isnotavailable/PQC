"""Lightweight attack scenarios suitable for classroom demos."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from ..core.blockchain import Blockchain
from ..core.validation import ValidationError
from ..core.wallet import Wallet
from .attacker import PrivateForkAttacker
from .network import SimpleNetwork, clone_blockchain


@dataclass
class AttackScenarioReport:
    title: str
    success: bool
    summary: str
    starting_balances: Dict[str, int]
    final_balances: Dict[str, int]
    public_height: int
    attacker_private_height: int
    merchant_received_on_public_chain: int
    merchant_received_after_reorg: int
    extra: Dict[str, object]
    events: List[Dict[str, object]]

    def to_dict(self) -> Dict[str, object]:
        return {
            "title": self.title,
            "success": self.success,
            "summary": self.summary,
            "starting_balances": dict(self.starting_balances),
            "final_balances": dict(self.final_balances),
            "public_height": self.public_height,
            "attacker_private_height": self.attacker_private_height,
            "merchant_received_on_public_chain": self.merchant_received_on_public_chain,
            "merchant_received_after_reorg": self.merchant_received_after_reorg,
            "extra": dict(self.extra),
            "events": list(self.events),
        }


def _build_seed_chain() -> Tuple[Blockchain, Dict[str, Wallet]]:
    chain = Blockchain()
    wallets = {
        "bootstrap": Wallet("bootstrap", signature_schemes=chain.signature_schemes),
        "attacker": Wallet("attacker", signature_schemes=chain.signature_schemes),
        "merchant": Wallet("merchant", signature_schemes=chain.signature_schemes),
        "honest_1": Wallet("honest_1", signature_schemes=chain.signature_schemes),
        "honest_2": Wallet("honest_2", signature_schemes=chain.signature_schemes),
    }
    chain.create_genesis_block(wallets["bootstrap"].primary_pubkey_hash, data="genesis")
    chain.add_block(chain.mine_block(wallets["bootstrap"].primary_pubkey_hash, [], coinbase_data="bootstrap-1"))
    chain.add_block(chain.mine_block(wallets["bootstrap"].primary_pubkey_hash, [], coinbase_data="bootstrap-2"))

    fund_attacker = wallets["bootstrap"].create_transaction(
        chain,
        wallets["attacker"].primary_pubkey_hash,
        amount=35,
        fee=1,
    )
    chain.add_block(chain.mine_block(wallets["bootstrap"].primary_pubkey_hash, [fund_attacker], coinbase_data="fund-attacker"))

    fund_honest = wallets["bootstrap"].create_transaction(
        chain,
        wallets["honest_1"].primary_pubkey_hash,
        amount=20,
        fee=1,
    )
    chain.add_block(chain.mine_block(wallets["bootstrap"].primary_pubkey_hash, [fund_honest], coinbase_data="fund-honest"))
    return chain, wallets


def bootstrap_demo_network() -> Tuple[SimpleNetwork, Dict[str, Wallet]]:
    seed_chain, wallets = _build_seed_chain()
    network = SimpleNetwork()
    for name in ("attacker", "merchant", "honest_1", "honest_2"):
        cloned_chain = clone_blockchain(seed_chain)
        network.register_node(name, wallets[name], cloned_chain)
    return network, wallets


def run_double_spend_scenario() -> AttackScenarioReport:
    network, wallets = bootstrap_demo_network()
    starting_balances = network.balances()
    attacker_private = PrivateForkAttacker.from_public_chain(
        name="attacker",
        wallet=wallets["attacker"],
        blockchain=network.nodes["attacker"].blockchain,
    )
    safe_address = wallets["attacker"].new_address(label="safe-receive")

    public_payment = wallets["attacker"].create_transaction(
        network.nodes["attacker"].blockchain,
        wallets["merchant"].primary_pubkey_hash,
        amount=8,
        fee=1,
    )
    network.submit_transaction(
        origin="attacker",
        transaction=public_payment,
        recipients=("merchant", "honest_1", "honest_2"),
        round_label="第1轮",
    )
    public_block = network.mine_pending("honest_1", "第1轮", "merchant-payment")
    network.broadcast_block("honest_1", public_block, ("merchant", "honest_2"), "第1轮")

    merchant_balance_after_public = wallets["merchant"].balance(network.nodes["merchant"].blockchain)

    private_refund = attacker_private.create_transaction(
        recipient_pubkey_hash=safe_address,
        amount=8,
        fee=1,
    )
    attacker_private.mine_hidden_block([private_refund], "private-refund")
    attacker_private.mine_hidden_block([], "private-lead")
    attacker_private.release_hidden_blocks(
        network=network,
        round_label="第2轮",
        recipients=("merchant", "honest_1", "honest_2", "attacker"),
    )

    merchant_balance_after_reorg = wallets["merchant"].balance(network.nodes["merchant"].blockchain)
    final_balances = network.balances()
    success = merchant_balance_after_public >= 8 and merchant_balance_after_reorg == 0
    summary = "双花攻击成功，商家先看到付款，随后被更长私链回滚。"
    if not success:
        summary = "双花攻击未成功，商家收款没有被回滚。"

    return AttackScenarioReport(
        title="双花攻击演示",
        success=success,
        summary=summary,
        starting_balances=starting_balances,
        final_balances=final_balances,
        public_height=network.nodes["merchant"].blockchain.best_height(),
        attacker_private_height=attacker_private.private_chain.best_height(),
        merchant_received_on_public_chain=merchant_balance_after_public,
        merchant_received_after_reorg=merchant_balance_after_reorg,
        extra={
            "public_payment_txid": public_payment.txid,
            "private_refund_txid": private_refund.txid,
            "safe_address": safe_address,
        },
        events=[event.to_dict() for event in network.events],
    )


def run_majority_reorg_scenario() -> AttackScenarioReport:
    network, wallets = bootstrap_demo_network()
    starting_balances = network.balances()
    attacker_private = PrivateForkAttacker.from_public_chain(
        name="attacker",
        wallet=wallets["attacker"],
        blockchain=network.nodes["attacker"].blockchain,
    )

    honest_block_1 = network.mine_pending("honest_1", "第1轮", "honest-growth-1")
    network.broadcast_block("honest_1", honest_block_1, ("merchant", "honest_2", "attacker"), "第1轮")
    honest_block_2 = network.mine_pending("honest_2", "第2轮", "honest-growth-2")
    network.broadcast_block("honest_2", honest_block_2, ("merchant", "honest_1", "attacker"), "第2轮")

    attacker_private.mine_hidden_block([], "private-1")
    attacker_private.mine_hidden_block([], "private-2")
    attacker_private.mine_hidden_block([], "private-3")
    attacker_private.release_hidden_blocks(
        network=network,
        round_label="第3轮",
        recipients=("merchant", "honest_1", "honest_2", "attacker"),
    )

    final_heights = network.best_heights()
    final_balances = network.balances()
    success = min(final_heights.values()) >= honest_block_2.header.height
    shared_tips = set(network.best_tips().values())
    success = success and len(shared_tips) == 1

    return AttackScenarioReport(
        title="51% 私链重组演示",
        success=success,
        summary="攻击者私下连续出块，随后发布更长分叉链，其他节点切换到累计工作量更高的链。",
        starting_balances=starting_balances,
        final_balances=final_balances,
        public_height=max(final_heights.values()),
        attacker_private_height=attacker_private.private_chain.best_height(),
        merchant_received_on_public_chain=0,
        merchant_received_after_reorg=0,
        extra={
            "shared_tip_count": len(shared_tips),
            "final_heights": final_heights,
            "final_tips": network.best_tips(),
        },
        events=[event.to_dict() for event in network.events],
    )
