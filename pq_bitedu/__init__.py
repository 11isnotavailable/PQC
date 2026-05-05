"""PQ-BitEdu package."""

from .agentic import (
    HostedAgentController,
    MinerController,
    MultiAgentEnvironment,
    NoopController,
    RoundRobinTraderController,
    build_hosted_adapter,
    deepseek_market_agent_presets,
    default_provider_config,
    format_presets_for_console,
)
from .core.blockchain import Blockchain
from .core.wallet import Wallet
from .crypto.signature import (
    MLDSASignature,
    MerkleLamportSignature,
    SignatureScheme,
    build_signature_schemes,
    default_scheme_name,
)
from .simulation import (
    AttackScenarioReport,
    PrivateForkAttacker,
    SimpleNetwork,
    bootstrap_demo_network,
    run_double_spend_scenario,
    run_majority_reorg_scenario,
)

__all__ = [
    "MultiAgentEnvironment",
    "HostedAgentController",
    "MinerController",
    "NoopController",
    "RoundRobinTraderController",
    "build_hosted_adapter",
    "deepseek_market_agent_presets",
    "default_provider_config",
    "format_presets_for_console",
    "Blockchain",
    "Wallet",
    "SignatureScheme",
    "MLDSASignature",
    "MerkleLamportSignature",
    "build_signature_schemes",
    "default_scheme_name",
    "AttackScenarioReport",
    "SimpleNetwork",
    "PrivateForkAttacker",
    "bootstrap_demo_network",
    "run_double_spend_scenario",
    "run_majority_reorg_scenario",
]
