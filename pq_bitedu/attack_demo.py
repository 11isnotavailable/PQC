"""CLI entrypoint for the lightweight attack demos."""

from __future__ import annotations

import json

from .simulation import run_double_spend_scenario, run_majority_reorg_scenario


def main() -> None:
    reports = [
        run_double_spend_scenario().to_dict(),
        run_majority_reorg_scenario().to_dict(),
    ]
    print(json.dumps({"reports": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
