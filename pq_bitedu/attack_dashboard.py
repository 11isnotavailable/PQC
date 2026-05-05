"""Generate a standalone HTML dashboard for attack demonstrations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

from .simulation import run_double_spend_scenario, run_majority_reorg_scenario


def run_attack_reports() -> Dict[str, object]:
    reports = [
        run_double_spend_scenario().to_dict(),
        run_majority_reorg_scenario().to_dict(),
    ]
    for report in reports:
        report["height_points"] = _scenario_points(report)
    return {
        "title": "PQ-BitEdu 攻击演示面板",
        "reports": reports,
    }


def _scenario_points(report: Dict[str, object]) -> List[Dict[str, object]]:
    points: List[Dict[str, object]] = [{"label": "起点", "height": 0}]
    for event in report.get("events", []):
        payload = event.get("payload", {})
        height = payload.get("height")
        if isinstance(height, int):
            points.append(
                {
                    "label": str(event.get("round_label", "")),
                    "height": height,
                    "actor": str(event.get("actor", "")),
                    "event_type": str(event.get("event_type", "")),
                }
            )
    return points


def render_attack_dashboard_html(payload: Dict[str, object]) -> str:
    report_json = json.dumps(payload, ensure_ascii=False)
    html = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PQ-BitEdu 攻击演示面板</title>
  <style>
    :root {
      --bg: #0d1220;
      --panel: #171f31;
      --panel-soft: rgba(255,255,255,0.04);
      --border: rgba(255,255,255,0.07);
      --text: #eef3ff;
      --muted: #aab5cf;
      --accent: #49d17d;
      --accent-2: #6fd3ff;
      --warn: #ffb454;
      --danger: #ff7c7c;
      --good-bg: rgba(73, 209, 125, 0.14);
      --bad-bg: rgba(255, 124, 124, 0.14);
      --font-mono: "Consolas", "SFMono-Regular", monospace;
      color-scheme: dark;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(80, 120, 255, 0.16), transparent 28%),
        radial-gradient(circle at top right, rgba(73, 209, 125, 0.09), transparent 26%),
        linear-gradient(180deg, #0a0f1b 0%, #111828 100%);
      color: var(--text);
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
    }
    .shell {
      width: min(1280px, calc(100% - 32px));
      margin: 0 auto;
      padding: 26px 0 40px;
    }
    .hero {
      display: grid;
      gap: 12px;
      padding: 28px;
      border-radius: 26px;
      background: linear-gradient(135deg, rgba(23,31,49,0.96), rgba(18,27,43,0.92));
      border: 1px solid rgba(255,255,255,0.06);
      box-shadow: 0 24px 80px rgba(0,0,0,0.28);
      margin-bottom: 18px;
    }
    .hero h1 {
      margin: 0;
      font-size: 36px;
      letter-spacing: 0.02em;
    }
    .hero p {
      margin: 0;
      color: var(--muted);
      line-height: 1.7;
      max-width: 980px;
    }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }
    .chip {
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.06);
      color: var(--muted);
      font-size: 13px;
    }
    .grid-row {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 18px;
      margin-bottom: 18px;
    }
    .panel {
      background: rgba(20, 28, 44, 0.96);
      border: 1px solid var(--border);
      border-radius: 24px;
      box-shadow: 0 18px 48px rgba(0,0,0,0.22);
      padding: 22px;
    }
    .scenario-card {
      border-left: 5px solid var(--accent-2);
    }
    .scenario-card.success {
      border-left-color: var(--accent);
    }
    .scenario-card.fail {
      border-left-color: var(--danger);
    }
    .eyebrow {
      display: inline-flex;
      align-items: center;
      padding: 6px 12px;
      border-radius: 999px;
      background: rgba(255,255,255,0.05);
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 12px;
    }
    .scenario-card h2 {
      margin: 0 0 8px;
      font-size: 26px;
    }
    .scenario-card p {
      margin: 0 0 16px;
      color: var(--muted);
      line-height: 1.65;
      min-height: 52px;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 14px;
    }
    .stat {
      padding: 12px 14px;
      border-radius: 16px;
      background: var(--panel-soft);
      border: 1px solid rgba(255,255,255,0.05);
    }
    .stat small {
      display: block;
      color: var(--muted);
      margin-bottom: 6px;
    }
    .stat strong {
      font-size: 24px;
      font-family: var(--font-mono);
    }
    .pill-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .pill {
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 13px;
      background: rgba(255,255,255,0.05);
      color: var(--text);
    }
    .pill.good {
      background: var(--good-bg);
      color: #82f2a8;
    }
    .pill.bad {
      background: var(--bad-bg);
      color: #ffaaaa;
    }
    .center-stage {
      display: grid;
      grid-template-columns: minmax(0, 1.45fr) minmax(320px, 0.95fr);
      gap: 18px;
      margin-bottom: 18px;
    }
    .panel h3 {
      margin: 0 0 4px;
      font-size: 24px;
    }
    .panel p.lead {
      margin: 0 0 16px;
      color: var(--muted);
      line-height: 1.6;
    }
    .chart-frame {
      width: 100%;
      aspect-ratio: 16 / 8;
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.015));
      border: 1px solid rgba(255,255,255,0.06);
      padding: 14px;
    }
    .chart-meta {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 14px;
    }
    .meta-box {
      padding: 12px 14px;
      border-radius: 16px;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.05);
    }
    .meta-box small {
      display: block;
      color: var(--muted);
      margin-bottom: 6px;
    }
    .meta-box strong {
      font-family: var(--font-mono);
      font-size: 18px;
    }
    .timeline {
      display: grid;
      gap: 10px;
      max-height: 860px;
      overflow: auto;
      padding-right: 4px;
    }
    .event {
      padding: 12px 14px;
      border-radius: 16px;
      background: rgba(255,255,255,0.035);
      border: 1px solid rgba(255,255,255,0.05);
      border-left: 4px solid var(--accent-2);
      font-size: 13px;
      line-height: 1.6;
    }
    .event .topline {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 12px;
    }
    .event .detail {
      color: var(--text);
      margin-bottom: 6px;
    }
    .event .hint {
      color: var(--muted);
    }
    .kind-transaction_broadcast { border-left-color: #ff8cc6; }
    .kind-block_mined { border-left-color: var(--warn); }
    .kind-block_broadcast { border-left-color: var(--accent); }
    @media (max-width: 1040px) {
      .center-stage { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>PQ-BitEdu 攻击演示面板</h1>
      <p>这个页面独立于主市场模拟页面，风格保持一致，专门展示教学版多节点网络中的双花攻击和 51% 私链重组。重点不是工业级 P2P，而是让攻击前后状态、分叉替换和商家结果足够直观。</p>
      <div class="chips" id="chips"></div>
    </section>

    <section class="grid-row" id="scenario-cards"></section>

    <section class="center-stage">
      <section class="panel">
        <h3>攻击高度曲线</h3>
        <p class="lead">下面两条折线分别代表两个攻击场景中被观察到的链高度推进。你上台时可以直接解释为：诚实链先长起来，攻击者私链后公布，最终替换公共视图。</p>
        <div class="chart-frame">
          <svg id="height-chart" viewBox="0 0 960 420" width="100%" height="100%" preserveAspectRatio="none"></svg>
        </div>
        <div class="chart-meta" id="height-chart-meta"></div>
      </section>
      <aside class="panel">
        <h3>结果摘要</h3>
        <p class="lead">这里把最适合讲述的结论抽出来，方便你现场解释“零确认为什么不安全”和“为什么累计工作量规则会接受更长私链”。</p>
        <div class="timeline" id="summary-list"></div>
      </aside>
    </section>

    <section class="grid-row">
      <section class="panel">
        <h3>双花攻击时间线</h3>
        <p class="lead">商家先收到付款，再被私链回滚，最适合在课堂上解释“为什么零确认收款不安全”。</p>
        <div class="timeline" id="double-spend-events"></div>
      </section>
      <section class="panel">
        <h3>51% 重组时间线</h3>
        <p class="lead">诚实节点先出块，攻击者憋私链，最后用更长链统一全网视图。</p>
        <div class="timeline" id="majority-events"></div>
      </section>
    </section>
  </div>

  <script>
    const REPORT = __REPORT_JSON__;

    function shortHash(value) {
      return String(value || "").slice(0, 12) + "...";
    }

    function addMetaBox(root, label, value) {
      const box = document.createElement("div");
      box.className = "meta-box";
      box.innerHTML = `<small>${label}</small><strong>${value}</strong>`;
      root.appendChild(box);
    }

    function renderChips() {
      const chips = document.getElementById("chips");
      const totalEvents = REPORT.reports.reduce((count, report) => count + (report.events || []).length, 0);
      const successes = REPORT.reports.filter(report => report.success).length;
      [
        `场景数: ${REPORT.reports.length}`,
        `成功场景: ${successes}/${REPORT.reports.length}`,
        `总事件数: ${totalEvents}`,
        `演示类型: 双花 + 51% 私链重组`,
      ].forEach((text) => {
        const chip = document.createElement("div");
        chip.className = "chip";
        chip.textContent = text;
        chips.appendChild(chip);
      });
    }

    function renderScenarioCards() {
      const root = document.getElementById("scenario-cards");
      root.innerHTML = "";
      REPORT.reports.forEach((report) => {
        const card = document.createElement("article");
        card.className = `panel scenario-card ${report.success ? "success" : "fail"}`;
        const merchantDelta = Number(report.merchant_received_on_public_chain || 0) - Number(report.merchant_received_after_reorg || 0);
        card.innerHTML = `
          <div class="eyebrow">${report.success ? "演示成功" : "演示未成功"}</div>
          <h2>${report.title}</h2>
          <p>${report.summary}</p>
          <div class="stats">
            <div class="stat">
              <small>公共链最终高度</small>
              <strong>${report.public_height}</strong>
            </div>
            <div class="stat">
              <small>攻击者私链高度</small>
              <strong>${report.attacker_private_height}</strong>
            </div>
            <div class="stat">
              <small>商家表面收款</small>
              <strong>${report.merchant_received_on_public_chain} 枚</strong>
            </div>
            <div class="stat">
              <small>回滚后商家收款</small>
              <strong>${report.merchant_received_after_reorg} 枚</strong>
            </div>
          </div>
          <div class="pill-row">
            <span class="pill ${merchantDelta > 0 ? "bad" : "good"}">商家净变化 ${merchantDelta > 0 ? "-" : ""}${Math.abs(merchantDelta)} 枚</span>
            <span class="pill">攻击者余额 ${report.final_balances.attacker} 枚</span>
            <span class="pill">事件数 ${(report.events || []).length}</span>
          </div>
        `;
        root.appendChild(card);
      });
    }

    function renderSummary() {
      const list = document.getElementById("summary-list");
      list.innerHTML = "";
      REPORT.reports.forEach((report) => {
        const item = document.createElement("article");
        item.className = "event";
        const sharedTip = report.extra && report.extra.shared_tip_count !== undefined
          ? `最终共享链头数: ${report.extra.shared_tip_count}`
          : "无共享链头字段";
        item.innerHTML = `
          <div class="topline">
            <span>${report.title}</span>
            <span>${report.success ? "成功" : "失败"}</span>
          </div>
          <div class="detail">${report.summary}</div>
          <div class="hint">商家表面收款 ${report.merchant_received_on_public_chain} 枚，回滚后 ${report.merchant_received_after_reorg} 枚。${sharedTip}</div>
        `;
        list.appendChild(item);
      });
    }

    function renderEvents(containerId, reportIndex) {
      const container = document.getElementById(containerId);
      container.innerHTML = "";
      (REPORT.reports[reportIndex].events || []).forEach((event) => {
        const payload = event.payload || {};
        const hints = [];
        if (payload.height !== undefined) hints.push(`高度 ${payload.height}`);
        if (payload.block_hash) hints.push(`区块 ${shortHash(payload.block_hash)}`);
        if (payload.txid) hints.push(`交易 ${shortHash(payload.txid)}`);
        if (Array.isArray(payload.recipients) && payload.recipients.length) {
          hints.push(`广播到 ${payload.recipients.join(" / ")}`);
        }
        const item = document.createElement("article");
        item.className = `event kind-${event.event_type}`;
        item.innerHTML = `
          <div class="topline">
            <span>${event.round_label}</span>
            <span>${event.actor}</span>
          </div>
          <div class="detail">${event.detail}</div>
          <div class="hint">${hints.join(" · ") || "无附加字段"}</div>
        `;
        container.appendChild(item);
      });
    }

    function renderHeightChart() {
      const svg = document.getElementById("height-chart");
      const meta = document.getElementById("height-chart-meta");
      const reports = REPORT.reports || [];
      const width = 960;
      const height = 420;
      const padding = { top: 30, right: 28, bottom: 48, left: 52 };
      const colors = ["#49d17d", "#6fd3ff"];
      const labels = reports[0] ? (reports[0].height_points || []).map(point => point.label) : [];
      const allHeights = reports.flatMap(report => (report.height_points || []).map(point => Number(point.height || 0)));
      const min = 0;
      const max = Math.max(1, ...allHeights);
      const span = Math.max(1, max - min);
      const maxCount = Math.max(2, ...reports.map(report => (report.height_points || []).length));
      const stepX = (width - padding.left - padding.right) / Math.max(1, maxCount - 1);

      let grid = "";
      for (let i = 0; i < 5; i += 1) {
        const y = padding.top + i * ((height - padding.top - padding.bottom) / 4);
        const value = Math.round(max - i * (span / 4));
        grid += `<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="rgba(255,255,255,0.08)" stroke-dasharray="6 8" />`;
        grid += `<text x="${padding.left - 10}" y="${y + 4}" fill="rgba(238,243,255,0.62)" text-anchor="end" font-size="13">${value}</text>`;
      }

      let axisLabels = "";
      labels.forEach((label, index) => {
        const x = padding.left + index * stepX;
        axisLabels += `<text x="${x}" y="${height - 18}" fill="rgba(238,243,255,0.58)" text-anchor="middle" font-size="12">${label}</text>`;
      });

      let paths = "";
      reports.forEach((report, reportIndex) => {
        const coords = (report.height_points || []).map((point, index) => {
          const x = padding.left + index * stepX;
          const y = padding.top + (1 - ((Number(point.height || 0) - min) / span)) * (height - padding.top - padding.bottom);
          return [x, y, point];
        });
        const polyline = coords.map(([x, y]) => `${x},${y}`).join(" ");
        const dots = coords.map(([x, y, point]) =>
          `<circle cx="${x}" cy="${y}" r="5.5" fill="${colors[reportIndex % colors.length]}" stroke="#101520" stroke-width="2"><title>${point.label}: 高度 ${point.height}</title></circle>`
        ).join("");
        paths += `<polyline fill="none" stroke="${colors[reportIndex % colors.length]}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" points="${polyline}" />`;
        paths += dots;
      });

      svg.innerHTML = grid + axisLabels + paths;
      meta.innerHTML = "";
      reports.forEach((report, index) => {
        addMetaBox(meta, report.title, `${report.success ? "成功" : "失败"} · 最终高度 ${report.public_height}`);
      });
      if (reports[0]) {
        addMetaBox(meta, "最高高度", `${Math.max(...allHeights)}`);
      }
    }

    renderChips();
    renderScenarioCards();
    renderSummary();
    renderHeightChart();
    renderEvents("double-spend-events", 0);
    renderEvents("majority-events", 1);
  </script>
</body>
</html>"""
    return html.replace("__REPORT_JSON__", report_json)


def write_attack_dashboard(output_path: str) -> Path:
    payload = run_attack_reports()
    html = render_attack_dashboard_html(payload)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a standalone attack demo dashboard.")
    parser.add_argument("--output", default="reports/attack_dashboard.html")
    args = parser.parse_args()
    output = write_attack_dashboard(args.output)
    print("attack_dashboard_written:", str(output.resolve()))


if __name__ == "__main__":
    main()
