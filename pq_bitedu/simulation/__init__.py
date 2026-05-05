"""Lightweight multi-node and attack simulation helpers."""

from .attacker import PrivateForkAttacker
from .network import NetworkEvent, NetworkNodeState, SimpleNetwork, clone_blockchain
from .scenarios import (
    AttackScenarioReport,
    bootstrap_demo_network,
    run_double_spend_scenario,
    run_majority_reorg_scenario,
)

__all__ = [
    "AttackScenarioReport",
    "NetworkEvent",
    "NetworkNodeState",
    "PrivateForkAttacker",
    "SimpleNetwork",
    "bootstrap_demo_network",
    "clone_blockchain",
    "run_double_spend_scenario",
    "run_majority_reorg_scenario",
]
