"""Live-updating local dashboard server for the agent market simulation."""

from __future__ import annotations

import argparse
import json
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Mapping, Optional
from urllib.parse import urlparse

from .agentic import MultiAgentEnvironment
from .dashboard import _build_report_payload, build_scripted_environment, localized_mode, localized_role
from .market_simulation import build_environment as build_hosted_environment


def build_market_quotes(
    environment: MultiAgentEnvironment,
    current_price: float,
    round_index: int,
) -> List[Dict[str, object]]:
    quotes: List[Dict[str, object]] = []
    balances = environment.balances()
    for profile in environment.agent_profiles():
        if profile.role == "miner":
            continue
        balance = balances[profile.name]
        cash_balance = environment.cash_balances_yuan[profile.name]
        role = profile.role.lower()
        if "maker" in role:
            bid_discount, ask_premium = 0.01, 0.015
        elif "holder" in role:
            bid_discount, ask_premium = 0.03, 0.08
        elif "promoter" in role:
            bid_discount, ask_premium = 0.015, 0.03
        else:
            bid_discount, ask_premium = 0.02, 0.05

        buy_size = max(0, min(6, int(max(0.0, cash_balance) // max(0.5, current_price))))
        sell_size = max(0, min(6, balance))
        stance = "中性"
        if buy_size > sell_size:
            stance = "偏多"
        elif sell_size > buy_size:
            stance = "偏空"

        quotes.append(
            {
                "round": round_index,
                "agent": profile.name,
                "role": profile.role,
                "role_label": localized_role(profile.role),
                "bid": round(current_price * (1.0 - bid_discount), 2),
                "ask": round(current_price * (1.0 + ask_premium), 2),
                "buy_size": buy_size,
                "sell_size": sell_size,
                "stance": stance,
            }
        )
    quotes.sort(key=lambda item: (float(item["bid"]) + float(item["ask"])) / 2.0, reverse=True)
    return quotes


def build_market_quotes_from_outcomes(
    environment: MultiAgentEnvironment,
    current_price: float,
    round_index: int,
    outcomes: Mapping[str, object],
) -> List[Dict[str, object]]:
    quotes: List[Dict[str, object]] = []
    for profile in environment.agent_profiles():
        raw_outcome = outcomes.get(profile.name)
        decision = raw_outcome[0] if isinstance(raw_outcome, tuple) and raw_outcome else None
        tool_calls = tuple() if decision is None else getattr(decision, "tool_calls", tuple())
        summary = "" if decision is None else str(getattr(decision, "summary", ""))
        buy_size = 0
        sell_size = 0
        bid = current_price
        ask = current_price
        will_mine = False
        for tool_call in tool_calls:
            tool_name = getattr(tool_call, "tool_name", "")
            arguments = dict(getattr(tool_call, "arguments", {}))
            if tool_name == "buy_tokens":
                buy_size += max(0, int(arguments.get("amount", 0)))
                bid = float(arguments.get("quote_price_yuan", current_price))
            elif tool_name == "sell_tokens":
                sell_size += max(0, int(arguments.get("amount", 0)))
                ask = float(arguments.get("quote_price_yuan", current_price))
            elif tool_name == "mine_block":
                will_mine = True

        stance = "观望"
        if will_mine and buy_size == 0 and sell_size == 0:
            stance = "挖矿"
        elif buy_size > sell_size:
            stance = "偏多"
        elif sell_size > buy_size:
            stance = "偏空"
        elif buy_size > 0 or sell_size > 0:
            stance = "双向"

        quotes.append(
            {
                "round": round_index,
                "agent": profile.name,
                "role": profile.role,
                "role_label": localized_role(profile.role),
                "bid": round(bid, 2),
                "ask": round(ask, 2),
                "buy_size": buy_size,
                "sell_size": sell_size,
                "stance": stance,
                "will_mine": will_mine,
                "summary": summary,
            }
        )
    quotes.sort(key=lambda item: (int(item["buy_size"]) + int(item["sell_size"]), str(item["agent"])), reverse=True)
    return quotes


class LiveSimulationRunner:
    """Owns a simulation environment and advances it in the background."""

    def __init__(
        self,
        mode: str,
        model: str,
        interval_sec: float,
        external_capital_strategy: str = "strategy_mix",
        max_rounds: Optional[int] = None,
    ) -> None:
        if mode == "hosted":
            self.environment = build_hosted_environment(
                model=model,
                external_capital_strategy=external_capital_strategy,
            )
        elif mode == "scripted":
            self.environment = build_scripted_environment(
                external_capital_strategy=external_capital_strategy,
            )
        else:
            raise ValueError("mode must be 'scripted' or 'hosted'")

        self.mode = mode
        self.model = model
        self.external_capital_strategy = external_capital_strategy
        self.interval_sec = interval_sec
        self.max_rounds = max_rounds
        self.lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.running = False
        self.current_round = -1
        self.last_outcomes: Dict[str, object] = {}
        self.initial_balances = self.environment.balances()
        self.initial_cash = dict(self.environment.cash_balances_yuan)
        self.current_quotes: List[Dict[str, object]] = build_market_quotes_from_outcomes(
            self.environment,
            current_price=self.environment.current_price_yuan,
            round_index=-1,
            outcomes=self.last_outcomes,
        )

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        self.running = False

    def resume(self) -> None:
        if self.running:
            return
        self.start()

    def stop(self) -> None:
        self.running = False
        self._stop_event.set()

    def step_once(self) -> bool:
        with self.lock:
            if self.max_rounds is not None and self.current_round + 1 >= self.max_rounds:
                self.running = False
                return False
            self.last_outcomes = self.environment.step()
            self.current_round += 1
            self.current_quotes = build_market_quotes_from_outcomes(
                self.environment,
                current_price=self.environment.current_price_yuan,
                round_index=self.current_round,
                outcomes=self.last_outcomes,
            )
            return True

    def snapshot(self) -> Dict[str, object]:
        with self.lock:
            report = _build_report_payload(
                environment=self.environment,
                mode=self.mode,
                model=self.model,
                rounds=max(0, self.current_round + 1),
                initial_balances=self.initial_balances,
                initial_cash_balances=self.initial_cash,
                price_history=self.environment.price_history,
                round_history=self.environment.round_history,
            )
            quote_logs = [
                {
                    "tick": quote["round"],
                    "kind": "market",
                    "agent": quote["agent"],
                    "description": "{0} 报出买价 ¥{1:.2f} x {2} / 卖价 ¥{3:.2f} x {4}".format(
                        quote["agent"],
                        float(quote["bid"]),
                        int(quote["buy_size"]),
                        float(quote["ask"]),
                        int(quote["sell_size"]),
                    ),
                }
                for quote in self.current_quotes
            ]
            quote_logs = [
                {
                    "tick": quote["round"],
                    "kind": "market",
                    "agent": quote["agent"],
                    "description": "{0} 本轮方案: 买 ¥{1:.2f} x {2} / 卖 ¥{3:.2f} x {4} / {5}{6}".format(
                        quote["agent"],
                        float(quote["bid"]),
                        int(quote["buy_size"]),
                        float(quote["ask"]),
                        int(quote["sell_size"]),
                        str(quote["stance"]),
                        " / 挖矿" if bool(quote.get("will_mine")) else "",
                    ),
                }
                for quote in self.current_quotes
            ]
            report["logs"].extend(quote_logs)
            report["logs"] = sorted(
                report["logs"],
                key=lambda item: (int(item["tick"]), str(item["agent"]), str(item["kind"])),
            )
            report["live"] = {
                "running": self.running,
                "interval_sec": self.interval_sec,
                "current_round": self.current_round,
                "max_rounds": self.max_rounds,
                "mode_label": localized_mode(self.mode),
            }
            report["current_quotes"] = self.current_quotes
            return report

    def _loop(self) -> None:
        while not self._stop_event.is_set() and self.running:
            advanced = self.step_once()
            if not advanced:
                break
            time.sleep(self.interval_sec)
        self.running = False


def _render_live_html() -> str:
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PQC 实时市场沙盘</title>
  <style>
    :root {
      --panel: rgba(18, 24, 36, 0.94);
      --text: #eef3ff;
      --muted: #9ba9c9;
      --accent: #49d17d;
      --warn: #ffb454;
      --info: #6fd3ff;
      --danger: #ff7c7c;
      --radius: 18px;
      --shadow: 0 14px 36px rgba(0,0,0,0.28);
      --font: "Segoe UI Variable","Aptos","Trebuchet MS",sans-serif;
      --mono: "Cascadia Code","Consolas",monospace;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--text);
      font-family: var(--font);
      background:
        radial-gradient(circle at top, rgba(73,209,125,0.14), transparent 25%),
        radial-gradient(circle at 85% 10%, rgba(111,211,255,0.12), transparent 20%),
        linear-gradient(180deg, #090b10 0%, #10141d 100%);
    }
    .shell { max-width: 1460px; margin: 0 auto; padding: 20px; }
    .hero, .panel, .agent-card {
      border: 1px solid rgba(255,255,255,0.07);
      background: var(--panel);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }
    .hero {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      padding: 20px 22px;
      margin-bottom: 16px;
    }
    .hero h1 { margin: 0 0 8px; font-size: clamp(26px, 4vw, 40px); }
    .hero p { margin: 0; color: var(--muted); line-height: 1.5; max-width: 760px; }
    .controls { display: flex; flex-wrap: wrap; gap: 10px; justify-content: flex-end; min-width: 260px; }
    button {
      border: 0;
      border-radius: 999px;
      padding: 10px 16px;
      color: #0c1118;
      background: var(--accent);
      font-weight: 700;
      cursor: pointer;
    }
    button.secondary { background: rgba(255,255,255,0.08); color: var(--text); border: 1px solid rgba(255,255,255,0.08); }
    .chipbar { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
    .chip { padding: 8px 12px; border-radius: 999px; background: rgba(255,255,255,0.06); color: var(--muted); font-size: 13px; }
    .grid-row { display: grid; gap: 14px; grid-template-columns: repeat(2, minmax(0, 1fr)); margin-bottom: 16px; }
    .agent-card { position: relative; padding: 18px; overflow: hidden; min-height: 260px; }
    .agent-card::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 6px; background: var(--agent-color, var(--accent)); }
    .agent-card.bankrupt::after {
      content: "已破产";
      position: absolute;
      top: 14px;
      right: 14px;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(255, 124, 124, 0.18);
      color: #ffd6d6;
      font-size: 12px;
    }
    .agent-head { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
    .role-badge { display: inline-block; margin-top: 6px; padding: 5px 10px; border-radius: 999px; background: rgba(255,255,255,0.08); color: var(--agent-color, var(--accent)); font-size: 12px; }
    .agent-balance strong { display: block; font-size: 28px; font-family: var(--mono); text-align: right; }
    .agent-balance span { color: var(--muted); font-size: 12px; }
    .objective { color: var(--muted); line-height: 1.5; margin-bottom: 12px; min-height: 44px; }
    .stats { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }
    .stat { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.05); border-radius: 14px; padding: 10px 12px; }
    .stat small { display: block; color: var(--muted); margin-bottom: 6px; font-size: 11px; }
    .stat strong { font-family: var(--mono); font-size: 17px; }
    .quote { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
    .quote-pill { padding: 7px 10px; border-radius: 999px; font-size: 12px; border: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.05); color: var(--text); }
    .mid { display: grid; grid-template-columns: 1.7fr 1fr; gap: 16px; margin-bottom: 16px; }
    .panel { padding: 18px; }
    .panel h2 { margin: 0 0 6px; font-size: 22px; }
    .panel p { margin: 0 0 14px; color: var(--muted); line-height: 1.45; }
    .chart { width: 100%; aspect-ratio: 16 / 8; border-radius: 16px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); padding: 10px; }
    .quote-table { display: grid; gap: 10px; }
    .quote-row { display: grid; grid-template-columns: 1.15fr 0.7fr 0.7fr 0.6fr; gap: 8px; padding: 11px 12px; border-radius: 14px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.05); font-size: 13px; align-items: center; }
    .quote-row.header { background: rgba(255,255,255,0.07); color: var(--muted); font-size: 11px; }
    .logs { max-height: 720px; overflow: auto; display: grid; gap: 10px; }
    .log-item { padding: 11px 12px; border-radius: 14px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.05); font-size: 13px; line-height: 1.5; }
    .log-top { display: flex; justify-content: space-between; margin-bottom: 5px; color: var(--muted); font-size: 11px; }
    .kind-market { border-left: 4px solid var(--info); }
    .kind-trade { border-left: 4px solid var(--accent); }
    .kind-mine { border-left: 4px solid var(--warn); }
    .kind-cost { border-left: 4px solid var(--danger); }
    .kind-valuation { border-left: 4px solid #a0ffbf; }
    .kind-capital { border-left: 4px solid #ff8cc6; }
    .kind-bankrupt { border-left: 4px solid #ff7c7c; }
    @media (max-width: 1040px) { .mid { grid-template-columns: 1fr; } }
    @media (max-width: 840px) { .grid-row { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div>
        <h1>PQC 实时市场沙盘</h1>
        <p>每个智能体都有现金账户、持币账户、每回合固定生活开销，以及持续的外部资金买盘。现在它们可以真买、真卖，也可能真破产。</p>
        <div class="chipbar" id="chips"></div>
      </div>
      <div class="controls">
        <button id="resume-btn">开始自动运行</button>
        <button class="secondary" id="pause-btn">暂停</button>
        <button class="secondary" id="step-btn">单步推进</button>
      </div>
    </section>

    <section class="grid-row" id="top-row"></section>

    <section class="mid">
      <section class="panel">
        <h2>实时币价曲线</h2>
        <p>价格会受到真实现金买卖、外部资本注入和市场活跃度影响。</p>
        <div class="chart">
          <svg id="chart" viewBox="0 0 960 420" width="100%" height="100%" preserveAspectRatio="none"></svg>
        </div>
        <h2>模型阵营总资产对比</h2>
        <div class="chart">
          <svg id="provider-chart" viewBox="0 0 960 420" width="100%" height="100%" preserveAspectRatio="none"></svg>
        </div>
      </section>
      <aside class="panel">
        <h2>即时竞价板</h2>
        <p>这里是当前买卖意向，不是严格订单簿，但会参考现金余额和持币余额生成。</p>
        <div class="quote-table" id="quote-table"></div>
      </aside>
    </section>

    <section class="mid">
      <section class="panel">
        <h2>链上与市场日志</h2>
        <div class="logs" id="logs"></div>
      </section>
      <section class="panel">
        <h2>运行状态</h2>
        <p id="status-text"></p>
      </section>
    </section>

    <section class="grid-row" id="bottom-row"></section>
  </div>

  <script>
    function roleColor(role) {
      const normalized = String(role || "").toLowerCase();
      if (normalized.includes("miner")) return "#ffb454";
      if (normalized.includes("maker")) return "#49d17d";
      if (normalized.includes("holder")) return "#8fb2ff";
      if (normalized.includes("promoter")) return "#ff8cc6";
      return "#6fd3ff";
    }
    function yuan(v) {
      const sign = Number(v) < 0 ? "-" : "";
      return sign + "¥" + Math.abs(Number(v)).toFixed(2);
    }
    function tickLabel(tick) {
      return Number(tick) < 0 ? "启动" : `第 ${Number(tick) + 1} 轮`;
    }
    function clear(id) {
      const node = document.getElementById(id);
      while (node.firstChild) node.removeChild(node.firstChild);
      return node;
    }
    function render(report) {
      renderChips(report);
      renderCards(report);
      renderChart(report);
      renderProviderChart(report);
      renderQuotes(report);
      renderLogs(report);
      renderStatus(report);
    }
    function renderChips(report) {
      const wrap = clear("chips");
      const chips = [
        `模式: ${report.mode_label || report.mode}`,
        `模型: ${report.model}`,
        `当前轮次: ${Math.max(0, report.live.current_round + 1)}`,
        `区块高度: ${report.summary.height}`,
        `总交易数: ${report.summary.transactions}`,
        `当前难度: x${Number(report.economics.current_difficulty || 1).toFixed(2)}`,
        `外部买盘: 每轮 ¥${Number(report.economics.external_buy_budget_yuan).toFixed(2)}`,
        `外部风格: ${report.economics.external_capital_strategy}`,
        `破产数: ${report.summary.bankrupt_agents}`,
        report.live.running ? "状态: 运行中" : "状态: 已暂停"
      ];
      chips.forEach(text => {
        const chip = document.createElement("div");
        chip.className = "chip";
        chip.textContent = text;
        wrap.appendChild(chip);
      });
    }
    function agentCard(agent, quote) {
      const article = document.createElement("article");
      article.className = `agent-card${agent.bankrupt ? " bankrupt" : ""}`;
      article.style.setProperty("--agent-color", roleColor(agent.role));
      const quoteHtml = quote ? `
        <div class="quote">
          <span class="quote-pill">买价 ${yuan(quote.bid)} x ${quote.buy_size}</span>
          <span class="quote-pill">卖价 ${yuan(quote.ask)} x ${quote.sell_size}</span>
          <span class="quote-pill">${quote.stance}</span>
        </div>
      ` : "";
      article.innerHTML = `
        <div class="agent-head">
          <div>
            <h3>${agent.name}</h3>
            <span class="role-badge">${agent.role_label || agent.role}</span>
          </div>
          <div class="agent-balance">
            <strong>${agent.balance} PQC</strong>
            <span>当前持币</span>
          </div>
        </div>
        <div class="objective">${agent.objective}</div>
        <div class="stats">
          <div class="stat"><small>现金余额</small><strong>${yuan(agent.cash_balance_yuan)}</strong></div>
          <div class="stat"><small>总资产</small><strong>${yuan(agent.net_worth_yuan)}</strong></div>
          <div class="stat"><small>持币估值</small><strong>${yuan(agent.estimated_value_yuan)}</strong></div>
          <div class="stat"><small>累计收益</small><strong>${yuan(agent.estimated_pnl_yuan)}</strong></div>
        </div>
        <div class="objective">${agent.last_action}</div>
        ${quoteHtml}
      `;
      return article;
    }
    function renderCards(report) {
      const quotes = Object.fromEntries((report.current_quotes || []).map(item => [item.agent, item]));
      const agents = [...report.agents];
      const top = agents.filter(agent => String(agent.provider) === "deepseek");
      const bottom = agents.filter(agent => String(agent.provider) === "gemini");
      const topRow = clear("top-row");
      const bottomRow = clear("bottom-row");
      top.forEach(agent => topRow.appendChild(agentCard(agent, quotes[agent.name])));
      bottom.forEach(agent => bottomRow.appendChild(agentCard(agent, quotes[agent.name])));
    }
    function renderChart(report) {
      const svg = document.getElementById("chart");
      const series = report.price_history.map(item => Number(item.price));
      const labels = report.price_history.map(item => item.label);
      const width = 960;
      const height = 420;
      const pad = { top: 24, right: 24, bottom: 40, left: 52 };
      const min = Math.min(...series);
      const max = Math.max(...series);
      const span = Math.max(0.5, max - min);
      const stepX = (width - pad.left - pad.right) / Math.max(1, series.length - 1);
      const points = series.map((value, index) => {
        const x = pad.left + index * stepX;
        const y = pad.top + (1 - (value - min) / span) * (height - pad.top - pad.bottom);
        return [x, y];
      });
      const polyline = points.map(([x, y]) => `${x},${y}`).join(" ");
      const area = `M ${points[0][0]},${height - pad.bottom} ` + points.map(([x, y]) => `L ${x},${y}`).join(" ") + ` L ${points[points.length - 1][0]},${height - pad.bottom} Z`;
      let grid = "";
      for (let i = 0; i < 5; i += 1) {
        const y = pad.top + i * ((height - pad.top - pad.bottom) / 4);
        const label = (max - i * (span / 4)).toFixed(2);
        grid += `<line x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}" stroke="rgba(255,255,255,0.08)" stroke-dasharray="6 8" />`;
        grid += `<text x="${pad.left - 10}" y="${y + 4}" fill="rgba(255,255,255,0.55)" text-anchor="end" font-size="12">${label}</text>`;
      }
      let labelsSvg = "";
      points.forEach(([x], index) => {
        labelsSvg += `<text x="${x}" y="${height - 16}" fill="rgba(255,255,255,0.52)" text-anchor="middle" font-size="11">${labels[index]}</text>`;
      });
      let markers = "";
      points.forEach(([x, y], index) => {
        markers += `<circle cx="${x}" cy="${y}" r="5" fill="#49d17d" stroke="#0b0e14" stroke-width="2"></circle>`;
        markers += `<title>${labels[index]}: ¥${series[index].toFixed(2)}</title>`;
      });
      svg.innerHTML = `
        <defs>
          <linearGradient id="fillLine" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="rgba(73,209,125,0.35)" />
            <stop offset="100%" stop-color="rgba(73,209,125,0.03)" />
          </linearGradient>
        </defs>
        ${grid}
        <path d="${area}" fill="url(#fillLine)"></path>
        <polyline points="${polyline}" fill="none" stroke="#49d17d" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></polyline>
        ${markers}
        ${labelsSvg}
      `;
    }
    function renderProviderChart(report) {
      const svg = document.getElementById("provider-chart");
      const history = report.provider_equity_history || [];
      if (!svg || !history.length) return;
      const labels = history.map(item => item.label);
      const deepseek = history.map(item => Number((item.groups || {}).deepseek || 0));
      const gemini = history.map(item => Number((item.groups || {}).gemini || 0));
      const width = 960;
      const height = 420;
      const pad = { top: 24, right: 24, bottom: 40, left: 52 };
      const all = [...deepseek, ...gemini];
      const min = Math.min(...all);
      const max = Math.max(...all);
      const span = Math.max(1, max - min);
      const stepX = (width - pad.left - pad.right) / Math.max(1, deepseek.length - 1);
      const toPoints = (series) => series.map((value, index) => {
        const x = pad.left + index * stepX;
        const y = pad.top + (1 - (value - min) / span) * (height - pad.top - pad.bottom);
        return [x, y];
      });
      const deepseekPoints = toPoints(deepseek);
      const geminiPoints = toPoints(gemini);
      const polyline = (points) => points.map(([x, y]) => `${x},${y}`).join(" ");
      let grid = "";
      for (let i = 0; i < 5; i += 1) {
        const y = pad.top + i * ((height - pad.top - pad.bottom) / 4);
        const label = (max - i * (span / 4)).toFixed(0);
        grid += `<line x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}" stroke="rgba(255,255,255,0.08)" stroke-dasharray="6 8" />`;
        grid += `<text x="${pad.left - 10}" y="${y + 4}" fill="rgba(255,255,255,0.55)" text-anchor="end" font-size="12">${label}</text>`;
      }
      let labelsSvg = "";
      deepseekPoints.forEach(([x], index) => {
        labelsSvg += `<text x="${x}" y="${height - 16}" fill="rgba(255,255,255,0.52)" text-anchor="middle" font-size="11">${labels[index]}</text>`;
      });
      svg.innerHTML = `
        ${grid}
        <polyline points="${polyline(deepseekPoints)}" fill="none" stroke="#49d17d" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></polyline>
        <polyline points="${polyline(geminiPoints)}" fill="none" stroke="#6fd3ff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></polyline>
        ${labelsSvg}
      `;
    }
    function renderQuotes(report) {
      const wrap = clear("quote-table");
      const header = document.createElement("div");
      header.className = "quote-row header";
      header.innerHTML = "<div>智能体</div><div>买价</div><div>卖价</div><div>倾向</div>";
      wrap.appendChild(header);
      (report.current_quotes || []).forEach(quote => {
        const row = document.createElement("div");
        row.className = "quote-row";
        row.innerHTML = `
          <div>${quote.agent}</div>
          <div>${yuan(quote.bid)} x ${quote.buy_size}</div>
          <div>${yuan(quote.ask)} x ${quote.sell_size}</div>
          <div>${quote.stance}</div>
        `;
        wrap.appendChild(row);
      });
    }
    function renderLogs(report) {
      const wrap = clear("logs");
      const logs = [...report.logs].slice(-30).reverse();
      logs.forEach(log => {
        const item = document.createElement("article");
        item.className = `log-item kind-${log.kind}`;
        item.innerHTML = `
          <div class="log-top"><span>${tickLabel(log.tick)}</span><span>${log.agent}</span></div>
          <div>${log.description}</div>
        `;
        wrap.appendChild(item);
      });
    }
    function renderStatus(report) {
      const text = document.getElementById("status-text");
      text.textContent = `当前模式 ${report.mode_label || report.mode}，自动刷新间隔 ${report.live.interval_sec}s，当前回合 ${Math.max(0, report.live.current_round + 1)}，状态 ${report.live.running ? "运行中" : "暂停"}。`;
    }
    async function request(path, method = "GET") {
      const response = await fetch(path, { method });
      if (response.status !== 200) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.json();
    }
    async function refresh() {
      try {
        const report = await request("/api/state");
        render(report);
      } catch (error) {
        console.error(error);
      }
    }
    document.getElementById("resume-btn").addEventListener("click", async () => {
      await request("/api/resume", "POST");
      refresh();
    });
    document.getElementById("pause-btn").addEventListener("click", async () => {
      await request("/api/pause", "POST");
      refresh();
    });
    document.getElementById("step-btn").addEventListener("click", async () => {
      await request("/api/step", "POST");
      refresh();
    });
    setInterval(refresh, 1000);
    refresh();
  </script>
</body>
</html>"""


class LiveDashboardHandler(BaseHTTPRequestHandler):
    runner: LiveSimulationRunner

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(_render_live_html())
            return
        if parsed.path == "/api/state":
            self._send_json(self.runner.snapshot())
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/step":
            self.runner.step_once()
            self._send_json(self.runner.snapshot())
            return
        if parsed.path == "/api/pause":
            self.runner.pause()
            self._send_json(self.runner.snapshot())
            return
        if parsed.path == "/api/resume":
            self.runner.resume()
            self._send_json(self.runner.snapshot())
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, payload: Mapping[str, object]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def _send_html(self, html: str) -> None:
        raw = html.encode("utf-8")
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a live-updating dashboard server.")
    parser.add_argument("--mode", choices=["scripted", "hosted"], default="scripted")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--interval", type=float, default=4.0)
    parser.add_argument(
        "--capital-strategy",
        default="strategy_mix",
        choices=["strategy_mix", "fixed_dca", "dip_buyer", "trend_follower"],
    )
    parser.add_argument("--rounds", type=int, default=0, help="0 means unlimited rounds.")
    parser.add_argument("--autostart", action="store_true")
    args = parser.parse_args()

    runner = LiveSimulationRunner(
        mode=args.mode,
        model=args.model,
        interval_sec=args.interval,
        external_capital_strategy=args.capital_strategy,
        max_rounds=None if args.rounds <= 0 else args.rounds,
    )
    if args.autostart:
        runner.start()

    LiveDashboardHandler.runner = runner
    server = ThreadingHTTPServer((args.host, args.port), LiveDashboardHandler)
    print("live_dashboard_url: http://{0}:{1}/".format(args.host, args.port))
    try:
        server.serve_forever()
    finally:
        runner.stop()
        server.server_close()


if __name__ == "__main__":
    main()
