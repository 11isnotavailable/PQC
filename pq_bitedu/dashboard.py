"""Generate a standalone HTML dashboard for the agent market simulation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Mapping, Sequence

from .agentic import CompositeController, MinerController, MultiAgentEnvironment, RoundRobinTraderController
from .agentic.presets import deepseek_market_agent_presets
from .market_simulation import build_environment as build_hosted_environment


MODE_LABELS = {
    "scripted": "脚本驱动",
    "hosted": "模型驱动",
}
ROLE_LABELS = {
    "miner": "矿工",
    "trader": "交易员",
    "market-maker": "交易员",
    "conservative-holder": "交易员",
    "holder": "交易员",
    "community-promoter": "交易员",
    "promoter": "交易员",
}


def localized_mode(mode: str) -> str:
    return MODE_LABELS.get(mode, mode)


def localized_role(role: str) -> str:
    return ROLE_LABELS.get(role, role)


def localized_provider(provider: str) -> str:
    labels = {
        "deepseek": "DeepSeek",
        "gemini": "Gemini",
        "scripted": "Scripted",
    }
    return labels.get(str(provider).lower(), provider)


def estimate_power_cost_yuan(difficulty_ratio: float) -> float:
    return round(80.0 * max(1.0, difficulty_ratio), 2)


def build_scripted_environment(
    external_capital_strategy: str = "strategy_mix",
) -> MultiAgentEnvironment:
    environment = MultiAgentEnvironment(
        recent_event_window=80,
        external_capital_strategy=external_capital_strategy,
    )
    presets = deepseek_market_agent_presets()
    scripted_controllers = {
        "maker_mia": CompositeController(
            [RoundRobinTraderController(amount=3, fee=1), MinerController(coinbase_prefix="maker-mine")]
        ),
        "holder_han": CompositeController(
            [RoundRobinTraderController(amount=3, fee=1), MinerController(coinbase_prefix="holder-mine")]
        ),
        "promoter_pia": CompositeController(
            [RoundRobinTraderController(amount=3, fee=1), MinerController(coinbase_prefix="promoter-mine")]
        ),
    }
    for preset in presets:
        environment.register_agent(
            name=preset.name,
            controller=scripted_controllers[preset.name],
            role=preset.role,
            objective=preset.objective,
            system_prompt=preset.system_prompt,
            max_tool_calls_per_turn=preset.max_tool_calls_per_turn,
        )
    environment.initialize_bootstrap_chain(extra_reward_blocks=3)
    for preset in presets:
        environment.bootstrap_transfer(preset.name, amount=preset.bootstrap_balance, fee=1)
        environment._mine_to_pubkey_hash(
            miner_label="bootstrap_system",
            recipient_pubkey_hash=environment.bootstrap_wallet.primary_pubkey_hash,
            coinbase_data="scripted-bootstrap-{0}".format(preset.name),
        )
    return environment
    environment.register_agent(
        name="miner_1",
        controller=MinerController(coinbase_prefix="scripted-round"),
        role="miner",
        objective="每一轮都挖矿并确认待处理交易。",
    )
    environment.initialize_chain("miner_1", extra_reward_blocks=3)
    for preset in presets:
        environment.transfer("miner_1", preset.name, amount=preset.bootstrap_balance, fee=1)
        environment.mine("miner_1", coinbase_data="scripted-bootstrap-{0}".format(preset.name))
    return environment


def run_simulation(
    mode: str,
    rounds: int,
    model: str,
    external_capital_strategy: str = "strategy_mix",
) -> Dict[str, object]:
    if mode == "hosted":
        environment = build_hosted_environment(
            model=model,
            external_capital_strategy=external_capital_strategy,
        )
    elif mode == "scripted":
        environment = build_scripted_environment(
            external_capital_strategy=external_capital_strategy,
        )
    else:
        raise ValueError("mode must be 'scripted' or 'hosted'")

    initial_balances = environment.balances()
    initial_cash = dict(environment.cash_balances_yuan)
    for _ in range(rounds):
        environment.step()

    return _build_report_payload(
        environment=environment,
        mode=mode,
        model=model,
        rounds=rounds,
        initial_balances=initial_balances,
        initial_cash_balances=initial_cash,
        price_history=environment.price_history,
        round_history=environment.round_history,
    )


def _build_report_payload(
    environment: MultiAgentEnvironment,
    mode: str,
    model: str,
    rounds: int,
    initial_balances: Mapping[str, int],
    initial_cash_balances: Mapping[str, float],
    price_history: Sequence[Mapping[str, object]],
    round_history: Sequence[Mapping[str, object]],
) -> Dict[str, object]:
    final_price = float(price_history[-1]["price"])
    stats_by_agent: Dict[str, Dict[str, object]] = {}
    last_action_by_agent: Dict[str, str] = {}

    for profile in environment.agent_profiles():
        provider_name = (
            profile.provider.provider if profile.provider is not None else "scripted"
        )
        final_balance = environment.wallets[profile.name].balance(environment.blockchain)
        final_cash = round(environment.cash_balances_yuan[profile.name], 2)
        stats_by_agent[profile.name] = {
            "name": profile.name,
            "role": profile.role,
            "role_label": localized_role(profile.role),
            "provider": provider_name,
            "provider_label": localized_provider(provider_name),
            "objective": profile.objective,
            "prompt": profile.system_prompt,
            "initial_balance": int(initial_balances.get(profile.name, 0)),
            "initial_cash_yuan": round(float(initial_cash_balances.get(profile.name, 0.0)), 2),
            "balance": final_balance,
            "cash_balance_yuan": final_cash,
            "net_worth_yuan": round(final_cash + final_balance * final_price, 2),
            "sent_transactions": 0,
            "received_transactions": 0,
            "tokens_sent": 0,
            "tokens_received": 0,
            "tokens_bought": 0,
            "tokens_sold": 0,
            "fees_paid": 0,
            "blocks_mined": 0,
            "mining_rewards": 0,
            "power_cost_yuan": 0.0,
            "living_cost_yuan": 0.0,
            "estimated_value_yuan": round(final_balance * final_price, 2),
            "estimated_pnl_yuan": 0.0,
            "net_token_change": final_balance - int(initial_balances.get(profile.name, 0)),
            "bankrupt": environment.is_bankrupt(profile.name),
            "last_action": "",
        }

    log_entries: List[Dict[str, object]] = []
    for event in environment.events:
        payload = event.payload
        agent_name = event.agent_name or "system"
        if event.event_type == "transaction_submitted":
            sender_stats = stats_by_agent[agent_name]
            sender_stats["sent_transactions"] = int(sender_stats["sent_transactions"]) + 1
            sender_stats["tokens_sent"] = int(sender_stats["tokens_sent"]) + int(payload["amount"])
            sender_stats["fees_paid"] = int(sender_stats["fees_paid"]) + int(payload["fee"])
            recipient_name = str(payload["recipient"])
            if recipient_name in stats_by_agent:
                recipient_stats = stats_by_agent[recipient_name]
                recipient_stats["received_transactions"] = int(recipient_stats["received_transactions"]) + 1
                recipient_stats["tokens_received"] = int(recipient_stats["tokens_received"]) + int(
                    payload["amount"]
                )
            description = "{0} -> {1} {2} PQC（手续费 {3}）".format(
                agent_name,
                recipient_name,
                payload["amount"],
                payload["fee"],
            )
            log_entries.append({"tick": event.tick, "kind": "trade", "agent": agent_name, "description": description})
            last_action_by_agent[agent_name] = description
        elif event.event_type == "agent_decision" and agent_name in stats_by_agent:
            tool_calls = payload.get("tool_calls", [])
            tool_names = ", ".join(str(item.get("tool_name", "")) for item in tool_calls if item.get("tool_name"))
            description = "{0} 决策: {1}".format(agent_name, str(payload.get("summary", "")))
            if tool_names:
                description += " | 计划工具: {0}".format(tool_names)
            log_entries.append({"tick": event.tick, "kind": "decision", "agent": agent_name, "description": description})
            last_action_by_agent[agent_name] = description
        elif event.event_type == "tool_executed" and agent_name in stats_by_agent:
            tool_name = str(payload.get("tool_name", "tool"))
            if bool(payload.get("ok")):
                description = "{0} 执行 {1} 成功".format(agent_name, tool_name)
            else:
                description = "{0} 执行 {1} 失败: {2}".format(
                    agent_name,
                    tool_name,
                    str(payload.get("error", "unknown error")),
                )
                last_action_by_agent[agent_name] = description
            log_entries.append({"tick": event.tick, "kind": "tool", "agent": agent_name, "description": description})
        elif event.event_type == "market_buy":
            buyer_stats = stats_by_agent[agent_name]
            buyer_stats["tokens_bought"] = int(buyer_stats["tokens_bought"]) + int(payload["amount"])
            description = "{0} 用现金买入 {1} PQC，成交价 ¥{2:.2f}".format(
                agent_name,
                payload["amount"],
                float(payload["price_yuan"]),
            )
            log_entries.append({"tick": event.tick, "kind": "market", "agent": agent_name, "description": description})
            last_action_by_agent[agent_name] = description
        elif event.event_type == "market_sell":
            seller_stats = stats_by_agent[agent_name]
            seller_stats["tokens_sold"] = int(seller_stats["tokens_sold"]) + int(payload["amount"])
            description = "{0} 卖给市场池 {1} PQC，回收现金 ¥{2:.2f}".format(
                agent_name,
                payload["amount"],
                float(payload["value_yuan"]),
            )
            log_entries.append({"tick": event.tick, "kind": "market", "agent": agent_name, "description": description})
            last_action_by_agent[agent_name] = description
        elif event.event_type == "external_capital_fill":
            seller_stats = stats_by_agent[agent_name]
            seller_stats["tokens_sold"] = int(seller_stats["tokens_sold"]) + int(payload["amount"])
            description = "{0} 向外部资本卖出 {1} PQC，报价 ¥{2:.2f}，成交额 ¥{3:.2f}，剩余预算 ¥{4:.2f}".format(
                agent_name,
                int(payload["amount"]),
                float(payload["price_yuan"]),
                float(payload["value_yuan"]),
                float(payload.get("remaining_budget_yuan", 0.0) or 0.0),
            )
            log_entries.append({"tick": event.tick, "kind": "capital", "agent": agent_name, "description": description})
            last_action_by_agent[agent_name] = description
        elif event.event_type == "external_capital_buy":
            strategy_label = str(payload.get("strategy", "external"))
            description = "外部资本[{0}]买入 {1} PQC，注入现金 ¥{2:.2f}".format(
                strategy_label,
                payload["amount"],
                float(payload["value_yuan"]),
            )
            log_entries.append({"tick": event.tick, "kind": "capital", "agent": "外部资本", "description": description})
        elif event.event_type == "external_capital_signal":
            description = "外部资本预算信号 {0}: ¥{1:.2f} | {2}".format(
                str(payload.get("strategy", "external")),
                float(payload.get("budget_yuan", 0.0) or 0.0),
                str(payload.get("reason", "")),
            )
            log_entries.append({"tick": event.tick, "kind": "capital", "agent": "外部资本", "description": description})
        elif event.event_type == "external_capital_skipped":
            description = "外部资本未继续买入: {0}".format(str(payload.get("reason", "")))
            log_entries.append({"tick": event.tick, "kind": "capital", "agent": "外部资本", "description": description})
        elif event.event_type == "block_mined" and agent_name in stats_by_agent:
            miner_stats = stats_by_agent[agent_name]
            miner_stats["blocks_mined"] = int(miner_stats["blocks_mined"]) + 1
            miner_stats["mining_rewards"] = int(miner_stats["mining_rewards"]) + int(payload.get("coinbase_value", 0))
            block_cost = estimate_power_cost_yuan(float(payload.get("difficulty_ratio", 1.0)))
            miner_stats["power_cost_yuan"] = round(float(miner_stats["power_cost_yuan"]) + block_cost, 2)
            description = "挖出区块 H{0}，区块奖励 {1} PQC，难度 x{2}，耗电成本 ¥{3:.2f}".format(
                payload["height"],
                payload.get("coinbase_value", 0),
                float(payload.get("difficulty_ratio", 1.0)),
                block_cost,
            )
            log_entries.append({"tick": event.tick, "kind": "mine", "agent": agent_name, "description": description})
            last_action_by_agent[agent_name] = description
        elif event.event_type == "living_cost" and agent_name in stats_by_agent:
            stats_by_agent[agent_name]["living_cost_yuan"] = round(
                float(stats_by_agent[agent_name]["living_cost_yuan"]) + float(payload["cost_yuan"]),
                2,
            )
            log_entries.append(
                {
                    "tick": event.tick,
                    "kind": "cost",
                    "agent": agent_name,
                    "description": "{0} 日常开销 ¥{1:.2f}".format(agent_name, float(payload["cost_yuan"])),
                }
            )
        elif event.event_type == "price_updated":
            log_entries.append(
                {
                    "tick": event.tick,
                    "kind": "valuation",
                    "agent": "市场",
                    "description": "币价更新到 ¥{0:.2f}，净资金流信号 {1:.2f}".format(
                        float(payload["price_yuan"]),
                        float(payload["market_buy_yuan"]) - float(payload["market_sell_yuan"]),
                    ),
                }
            )
        elif event.event_type == "bankruptcy_declared" and agent_name in stats_by_agent:
            log_entries.append(
                {
                    "tick": event.tick,
                    "kind": "bankrupt",
                    "agent": agent_name,
                    "description": "{0} 现金跌破破产线，宣布破产".format(agent_name),
                }
            )
            last_action_by_agent[agent_name] = "已破产"

    for name, stats in stats_by_agent.items():
        current_total = float(stats["cash_balance_yuan"]) + float(stats["estimated_value_yuan"])
        stats["estimated_pnl_yuan"] = round(current_total - float(environment.initial_cash_yuan), 2)
        stats["last_action"] = last_action_by_agent.get(name, "暂时还没有值得记录的动作。")

    ordered_logs = sorted(log_entries, key=lambda item: (int(item["tick"]), str(item["agent"]), str(item["kind"])))
    provider_names = sorted({str(agent["provider"]) for agent in stats_by_agent.values()})
    provider_equity_history: List[Dict[str, object]] = []

    def build_provider_totals(
        balances: Mapping[str, int],
        cash_balances: Mapping[str, float],
        price: float,
    ) -> Dict[str, float]:
        totals = {provider_name: 0.0 for provider_name in provider_names}
        for agent_name, stats in stats_by_agent.items():
            provider_name = str(stats["provider"])
            totals[provider_name] += float(cash_balances.get(agent_name, 0.0)) + int(
                balances.get(agent_name, 0)
            ) * price
        return {provider_name: round(value, 2) for provider_name, value in totals.items()}

    provider_equity_history.append(
        {
            "round": -1,
            "label": str(price_history[0]["label"]),
            "groups": build_provider_totals(
                initial_balances,
                initial_cash_balances,
                float(price_history[0]["price"]),
            ),
        }
    )
    for round_entry in round_history:
        provider_equity_history.append(
            {
                "round": int(round_entry["round"]),
                "label": "第 {0} 轮".format(int(round_entry["round"]) + 1),
                "groups": build_provider_totals(
                    round_entry["balances"],
                    round_entry["cash_balances_yuan"],
                    float(round_entry["price"]),
                ),
            }
        )
    best_height = environment.blockchain.best_height()
    return {
        "title": "PQC 多智能体市场面板",
        "mode": mode,
        "mode_label": localized_mode(mode),
        "model": model,
        "rounds": rounds,
        "base_price_yuan": float(price_history[0]["price"]),
        "final_price_yuan": final_price,
        "price_history": list(price_history),
        "round_history": list(round_history),
        "summary": {
            "height": best_height,
            "blocks": sum(1 for event in environment.events if event.event_type == "block_mined"),
            "transactions": sum(
                1
                for event in environment.events
                if event.event_type in {"transaction_submitted", "market_buy", "market_sell"}
            ),
            "mempool_size": len(environment.node.mempool),
            "bankrupt_agents": len(environment.bankrupt_agents),
        },
        "economics": {
            "current_subsidy": environment.blockchain.reward_for_height(best_height),
            "next_subsidy": environment.blockchain.reward_for_height(best_height + 1),
            "current_difficulty": environment.blockchain.current_difficulty_ratio(),
            "halving_interval": environment.blockchain.halving_interval,
            "difficulty_adjustment_interval": environment.blockchain.difficulty_adjustment_interval,
            "target_block_time_seconds": environment.blockchain.target_block_time_seconds,
            "living_cost_per_round_yuan": environment.living_cost_per_round_yuan,
            "bankruptcy_floor_yuan": environment.bankruptcy_floor_yuan,
            "external_buy_budget_yuan": environment.external_buy_budget_yuan,
            "external_buy_budget_unlimited": environment.external_budget_is_unlimited(),
            "external_max_buy_tokens_per_round": environment.external_max_buy_tokens_per_round,
            "external_capital_strategy": environment.external_capital_strategy,
            "external_current_round_budget_yuan": environment.external_current_round_budget_yuan,
            "external_remaining_budget_yuan": environment.external_remaining_budget_yuan,
            "external_remaining_token_capacity": environment.external_remaining_token_capacity,
            "external_bid_ceiling_yuan": environment.external_bid_ceiling_yuan(),
        },
        "provider_equity_history": provider_equity_history,
        "agents": list(stats_by_agent.values()),
        "logs": ordered_logs,
    }


def render_dashboard_html(report: Mapping[str, object]) -> str:
    report_json = json.dumps(report, ensure_ascii=False).replace("<", "\\u003c")
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PQC 多智能体市场面板</title>
  <style>
    :root {{
      --panel: rgba(20, 24, 34, 0.9);
      --panel-2: rgba(16, 19, 28, 0.92);
      --line: rgba(111, 125, 156, 0.22);
      --text: #eef3ff;
      --muted: #9ba9c9;
      --accent: #49d17d;
      --accent-2: #6fd3ff;
      --warn: #ffb454;
      --danger: #ff7c7c;
      --card-shadow: 0 16px 40px rgba(0, 0, 0, 0.28);
      --radius: 22px;
      --font-sans: "Segoe UI Variable", "Aptos", "Trebuchet MS", sans-serif;
      --font-mono: "Cascadia Code", "Consolas", monospace;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      background:
        radial-gradient(circle at top, rgba(75, 209, 125, 0.15), transparent 28%),
        radial-gradient(circle at 90% 20%, rgba(111, 211, 255, 0.12), transparent 24%),
        linear-gradient(180deg, #0b0d12 0%, #10131c 100%);
      font-family: var(--font-sans);
    }}
    .shell {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 26px;
    }}
    .hero, .panel, .agent-card {{
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: var(--radius);
      box-shadow: var(--card-shadow);
      background: linear-gradient(180deg, var(--panel), var(--panel-2));
    }}
    .hero {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 20px;
      padding: 24px 28px;
    }}
    .hero h1 {{ margin: 0 0 8px; font-size: clamp(28px, 4vw, 42px); }}
    .hero p {{ margin: 0; color: var(--muted); max-width: 720px; line-height: 1.55; }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 10px; align-content: flex-start; }}
    .chip {{
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.08);
      font-size: 13px;
      color: var(--muted);
    }}
    .grid-row {{
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin-bottom: 18px;
    }}
    .agent-card {{
      position: relative;
      overflow: hidden;
      padding: 20px;
      min-height: 292px;
    }}
    .agent-card::after {{
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 6px;
      background: var(--role-color, var(--accent));
    }}
    .agent-card.bankrupt::before {{
      content: "已破产";
      position: absolute;
      top: 14px;
      right: 14px;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(255, 124, 124, 0.18);
      color: #ffd6d6;
      font-size: 12px;
    }}
    .agent-head {{
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: flex-start;
      margin-bottom: 14px;
    }}
    .agent-name {{ margin: 0 0 6px; font-size: 22px; }}
    .agent-role {{
      display: inline-flex;
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 12px;
      background: rgba(255,255,255,0.08);
      color: var(--role-color, var(--accent));
    }}
    .agent-balance {{ text-align: right; }}
    .agent-balance strong {{
      display: block;
      font-size: 30px;
      line-height: 1;
    }}
    .agent-balance span {{ color: var(--muted); font-size: 12px; }}
    .objective {{ margin: 0 0 14px; color: var(--muted); line-height: 1.5; font-size: 14px; }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 14px;
    }}
    .stat {{
      padding: 12px;
      border-radius: 16px;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.05);
    }}
    .stat-label {{ color: var(--muted); font-size: 12px; margin-bottom: 6px; }}
    .stat-value {{ font-family: var(--font-mono); font-size: 18px; }}
    .last-action {{
      padding: 12px 14px;
      border-radius: 16px;
      background: rgba(73, 209, 125, 0.08);
      border: 1px solid rgba(73, 209, 125, 0.12);
      color: #d6ffe4;
      font-size: 13px;
      line-height: 1.5;
    }}
    .center-stage {{
      display: grid;
      grid-template-columns: minmax(0, 1.8fr) minmax(320px, 0.95fr);
      gap: 18px;
      margin-bottom: 18px;
    }}
    .panel {{ padding: 20px; }}
    .panel h2 {{ margin: 0 0 4px; font-size: 22px; }}
    .panel p {{ margin: 0 0 18px; color: var(--muted); line-height: 1.5; }}
    .chart-frame {{
      width: 100%;
      aspect-ratio: 16 / 8;
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.015));
      border: 1px solid rgba(255,255,255,0.06);
      padding: 14px;
    }}
    .chart-meta {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 14px;
    }}
    .meta-box {{
      padding: 12px 14px;
      border-radius: 16px;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.05);
    }}
    .meta-box small {{ display: block; color: var(--muted); margin-bottom: 6px; }}
    .meta-box strong {{ font-family: var(--font-mono); font-size: 18px; }}
    .log-list {{ display: grid; gap: 10px; max-height: 760px; overflow: auto; padding-right: 4px; }}
    .log-item {{
      padding: 12px 14px;
      border-radius: 16px;
      background: rgba(255,255,255,0.035);
      border: 1px solid rgba(255,255,255,0.05);
      font-size: 13px;
      line-height: 1.55;
    }}
    .log-item .topline {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 12px;
    }}
    .kind-trade {{ border-left: 4px solid var(--accent-2); }}
    .kind-mine {{ border-left: 4px solid var(--warn); }}
    .kind-cost {{ border-left: 4px solid var(--danger); }}
    .kind-valuation {{ border-left: 4px solid var(--accent); }}
    .kind-market {{ border-left: 4px solid #8fb2ff; }}
    .kind-capital {{ border-left: 4px solid #ff8cc6; }}
    .kind-bankrupt {{ border-left: 4px solid #ff7c7c; }}
    @media (max-width: 1060px) {{ .center-stage {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 860px) {{ .grid-row {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div>
        <h1>PQC 多智能体市场面板</h1>
        <p>每个智能体初始现金为 1 万元，每回合固定扣除 100 元日常开销，并且有外部资本持续买入，市场不再只是单纯转账，而是具备真实现金、投资和破产机制。</p>
      </div>
      <div class="chips" id="chips"></div>
    </section>

    <section class="grid-row" id="top-row"></section>

    <section class="center-stage">
      <section class="panel">
        <h2>实时币价曲线</h2>
        <p>价格会受到真实现金买卖、外部买盘、挖矿活跃度和破产情况影响。</p>
        <div class="chart-frame">
          <svg id="price-chart" viewBox="0 0 960 420" width="100%" height="100%" preserveAspectRatio="none"></svg>
        </div>
        <div class="chart-meta" id="chart-meta"></div>
        <h2>模型阵营总资产对比</h2>
        <p>两条折线分别表示 DeepSeek 阵营与 Gemini 阵营的总资产变化。</p>
        <div class="chart-frame">
          <svg id="provider-chart" viewBox="0 0 960 420" width="100%" height="100%" preserveAspectRatio="none"></svg>
        </div>
        <div class="chart-meta" id="provider-chart-meta"></div>
      </section>
      <aside class="panel">
        <h2>链上与市场日志</h2>
        <p>这里汇总了转账、买卖、外部资本注入、挖矿和破产等事件。</p>
        <div class="log-list" id="log-list"></div>
      </aside>
    </section>

    <section class="grid-row" id="bottom-row"></section>
  </div>

  <script>
    const REPORT = {report_json};

    function roleColor(role) {{
      const normalized = String(role || "").toLowerCase();
      if (normalized.includes("miner")) return "#ffb454";
      if (normalized.includes("maker")) return "#49d17d";
      if (normalized.includes("holder")) return "#8fb2ff";
      if (normalized.includes("promoter")) return "#ff8cc6";
      return "#6fd3ff";
    }}

    function tickLabel(tick) {{
      return Number(tick) < 0 ? "启动" : `第 ${{Number(tick) + 1}} 轮`;
    }}

    function formatYuan(value) {{
      const sign = Number(value) < 0 ? "-" : "";
      return sign + "¥" + Math.abs(Number(value)).toFixed(2);
    }}

    function formatToken(value) {{
      const prefix = Number(value) > 0 ? "+" : "";
      return prefix + value + " PQC";
    }}

    function buildCard(agent) {{
      const card = document.createElement("article");
      card.className = `agent-card${{agent.bankrupt ? " bankrupt" : ""}}`;
      card.style.setProperty("--role-color", roleColor(agent.role));
      card.innerHTML = `
        <div class="agent-head">
          <div>
            <h3 class="agent-name">${{agent.name}}</h3>
            <span class="agent-role">${{agent.role_label || agent.role}}</span>
          </div>
          <div class="agent-balance">
            <strong>${{agent.balance}} PQC</strong>
            <span>当前持币</span>
          </div>
        </div>
        <p class="objective">${{agent.objective}}</p>
        <div class="stats">
          <div class="stat"><div class="stat-label">现金余额</div><div class="stat-value">${{formatYuan(agent.cash_balance_yuan)}}</div></div>
          <div class="stat"><div class="stat-label">总资产</div><div class="stat-value">${{formatYuan(agent.net_worth_yuan)}}</div></div>
          <div class="stat"><div class="stat-label">持币估值</div><div class="stat-value">${{formatYuan(agent.estimated_value_yuan)}}</div></div>
          <div class="stat"><div class="stat-label">累计收益</div><div class="stat-value">${{formatYuan(agent.estimated_pnl_yuan)}}</div></div>
          <div class="stat"><div class="stat-label">耗电成本</div><div class="stat-value">${{formatYuan(agent.power_cost_yuan)}}</div></div>
          <div class="stat"><div class="stat-label">日常开销</div><div class="stat-value">${{formatYuan(agent.living_cost_yuan)}}</div></div>
        </div>
        <div class="last-action">${{agent.last_action}}</div>
      `;
      return card;
    }}

    function renderCards() {{
      const agents = [...REPORT.agents];
      const top = agents.filter(agent => String(agent.provider) === "deepseek");
      const bottom = agents.filter(agent => String(agent.provider) === "gemini");
      const topRow = document.getElementById("top-row");
      const bottomRow = document.getElementById("bottom-row");
      top.forEach(agent => topRow.appendChild(buildCard(agent)));
      bottom.forEach(agent => bottomRow.appendChild(buildCard(agent)));
    }}

    function renderChips() {{
      const chips = document.getElementById("chips");
      const entries = [
        `模式: ${{REPORT.mode_label || REPORT.mode}}`,
        `模型: ${{REPORT.model}}`,
        `轮数: ${{REPORT.rounds}}`,
        `区块高度: ${{REPORT.summary.height}}`,
        `总交易数: ${{REPORT.summary.transactions}}`,
        `当前难度: x${{Number(REPORT.economics.current_difficulty || 1).toFixed(2)}}`,
        `下一块奖励: ${{REPORT.economics.next_subsidy}} PQC`,
        `外部买盘: 每轮 ¥${{Number(REPORT.economics.external_buy_budget_yuan).toFixed(2)}}`,
        `外部风格: ${{REPORT.economics.external_capital_strategy}}`,
        `破产数: ${{REPORT.summary.bankrupt_agents}}`,
        `最新估值: ${{formatYuan(REPORT.final_price_yuan)}}`
      ];
      entries.forEach(text => {{
        const chip = document.createElement("div");
        chip.className = "chip";
        chip.textContent = text;
        chips.appendChild(chip);
      }});
    }}

    function renderChart() {{
      const svg = document.getElementById("price-chart");
      const points = REPORT.price_history.map(item => Number(item.price));
      const labels = REPORT.price_history.map(item => item.label);
      const width = 960;
      const height = 420;
      const padding = {{ top: 30, right: 28, bottom: 48, left: 52 }};
      const min = Math.min(...points);
      const max = Math.max(...points);
      const span = Math.max(0.5, max - min);
      const stepX = (width - padding.left - padding.right) / Math.max(1, points.length - 1);
      const coords = points.map((value, index) => {{
        const x = padding.left + index * stepX;
        const y = padding.top + (1 - (value - min) / span) * (height - padding.top - padding.bottom);
        return [x, y];
      }});
      const polyline = coords.map(([x, y]) => `${{x}},${{y}}`).join(" ");
      const area = `M ${{coords[0][0]}},${{height - padding.bottom}} ` + coords.map(([x, y]) => `L ${{x}},${{y}}`).join(" ") + ` L ${{coords[coords.length - 1][0]}},${{height - padding.bottom}} Z`;
      let grid = "";
      for (let i = 0; i < 5; i += 1) {{
        const y = padding.top + i * ((height - padding.top - padding.bottom) / 4);
        const label = (max - i * (span / 4)).toFixed(2);
        grid += `<line x1="${{padding.left}}" y1="${{y}}" x2="${{width - padding.right}}" y2="${{y}}" stroke="rgba(255,255,255,0.08)" stroke-dasharray="6 8" />`;
        grid += `<text x="${{padding.left - 10}}" y="${{y + 4}}" fill="rgba(238,243,255,0.62)" text-anchor="end" font-size="13">${{label}}</text>`;
      }}
      let axisLabels = "";
      coords.forEach(([x], index) => {{
        axisLabels += `<text x="${{x}}" y="${{height - 18}}" fill="rgba(238,243,255,0.58)" text-anchor="middle" font-size="12">${{labels[index]}}</text>`;
      }});
      let markers = "";
      coords.forEach(([x, y], index) => {{
        markers += `<circle cx="${{x}}" cy="${{y}}" r="5.5" fill="#49d17d" stroke="#0f1116" stroke-width="2" />`;
        markers += `<title>${{labels[index]}}: ¥${{points[index].toFixed(2)}}</title>`;
      }});
      svg.innerHTML = `
        <defs>
          <linearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="rgba(73,209,125,0.42)" />
            <stop offset="100%" stop-color="rgba(73,209,125,0.03)" />
          </linearGradient>
        </defs>
        ${{grid}}
        <path d="${{area}}" fill="url(#areaFill)" />
        <polyline fill="none" stroke="#49d17d" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" points="${{polyline}}" />
        ${{markers}}
        ${{axisLabels}}
      `;
      const meta = document.getElementById("chart-meta");
      const first = points[0];
      const last = points[points.length - 1];
      const change = last - first;
      const pct = first === 0 ? 0 : (change / first) * 100;
      const metaItems = [
        ["起始估值", formatYuan(first)],
        ["最新估值", formatYuan(last)],
        ["阶段涨跌", `${{change >= 0 ? "+" : ""}}${{change.toFixed(2)}} / ${{pct.toFixed(1)}}%`],
      ];
      metaItems.forEach(([label, value]) => {{
        const box = document.createElement("div");
        box.className = "meta-box";
        box.innerHTML = `<small>${{label}}</small><strong>${{value}}</strong>`;
        meta.appendChild(box);
      }});
    }}

    function renderProviderChart() {{
      const svg = document.getElementById("provider-chart");
      const meta = document.getElementById("provider-chart-meta");
      const history = REPORT.provider_equity_history || [];
      if (!svg || !history.length) return;
      const labels = history.map(item => item.label);
      const deepseek = history.map(item => Number((item.groups || {{}}).deepseek || 0));
      const gemini = history.map(item => Number((item.groups || {{}}).gemini || 0));
      const width = 960;
      const height = 420;
      const padding = {{ top: 30, right: 28, bottom: 48, left: 52 }};
      const all = [...deepseek, ...gemini];
      const min = Math.min(...all);
      const max = Math.max(...all);
      const span = Math.max(1, max - min);
      const stepX = (width - padding.left - padding.right) / Math.max(1, labels.length - 1);
      const toCoords = (series) => series.map((value, index) => {{
        const x = padding.left + index * stepX;
        const y = padding.top + (1 - (value - min) / span) * (height - padding.top - padding.bottom);
        return [x, y];
      }});
      const deepseekCoords = toCoords(deepseek);
      const geminiCoords = toCoords(gemini);
      const polyline = (coords) => coords.map(([x, y]) => `${{x}},${{y}}`).join(" ");
      let grid = "";
      for (let i = 0; i < 5; i += 1) {{
        const y = padding.top + i * ((height - padding.top - padding.bottom) / 4);
        const label = (max - i * (span / 4)).toFixed(0);
        grid += `<line x1="${{padding.left}}" y1="${{y}}" x2="${{width - padding.right}}" y2="${{y}}" stroke="rgba(255,255,255,0.08)" stroke-dasharray="6 8" />`;
        grid += `<text x="${{padding.left - 10}}" y="${{y + 4}}" fill="rgba(238,243,255,0.62)" text-anchor="end" font-size="13">${{label}}</text>`;
      }}
      let axisLabels = "";
      deepseekCoords.forEach(([x], index) => {{
        axisLabels += `<text x="${{x}}" y="${{height - 18}}" fill="rgba(238,243,255,0.58)" text-anchor="middle" font-size="12">${{labels[index]}}</text>`;
      }});
      svg.innerHTML = `
        ${{grid}}
        <polyline fill="none" stroke="#49d17d" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" points="${{polyline(deepseekCoords)}}" />
        <polyline fill="none" stroke="#6fd3ff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" points="${{polyline(geminiCoords)}}" />
        ${{axisLabels}}
      `;
      const latestDeepseek = deepseek[deepseek.length - 1];
      const latestGemini = gemini[gemini.length - 1];
      [
        ["DeepSeek 总资产", formatYuan(latestDeepseek)],
        ["Gemini 总资产", formatYuan(latestGemini)],
        ["当前领先方", latestDeepseek >= latestGemini ? "DeepSeek" : "Gemini"],
      ].forEach(([label, value]) => {{
        const box = document.createElement("div");
        box.className = "meta-box";
        box.innerHTML = `<small>${{label}}</small><strong>${{value}}</strong>`;
        meta.appendChild(box);
      }});
    }}

    function renderLogs() {{
      const list = document.getElementById("log-list");
      const recentLogs = [...REPORT.logs].slice(-36).reverse();
      recentLogs.forEach(entry => {{
        const item = document.createElement("article");
        item.className = `log-item kind-${{entry.kind}}`;
        item.innerHTML = `
          <div class="topline">
            <span>${{tickLabel(entry.tick)}}</span>
            <span>${{entry.agent}}</span>
          </div>
          <div>${{entry.description}}</div>
        `;
        list.appendChild(item);
      }});
    }}

    renderChips();
    renderCards();
    renderChart();
    renderProviderChart();
    renderLogs();
  </script>
</body>
</html>""".format(report_json=report_json)


def write_dashboard(
    output_path: str,
    mode: str = "scripted",
    rounds: int = 4,
    model: str = "deepseek-v4-flash",
    external_capital_strategy: str = "strategy_mix",
) -> Path:
    report = run_simulation(
        mode=mode,
        rounds=rounds,
        model=model,
        external_capital_strategy=external_capital_strategy,
    )
    html = render_dashboard_html(report)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a standalone market dashboard.")
    parser.add_argument("--mode", choices=["scripted", "hosted"], default="scripted")
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument(
        "--capital-strategy",
        default="strategy_mix",
        choices=["strategy_mix", "fixed_dca", "dip_buyer", "trend_follower"],
    )
    parser.add_argument("--output", default="reports/market_dashboard.html")
    args = parser.parse_args()

    output = write_dashboard(
        output_path=args.output,
        mode=args.mode,
        rounds=args.rounds,
        model=args.model,
        external_capital_strategy=args.capital_strategy,
    )
    print("dashboard_written:", str(output.resolve()))


if __name__ == "__main__":
    main()
