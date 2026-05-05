"""Generate a standalone HTML dashboard for three-way scheme comparison."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Dict, List

from .core.blockchain import Blockchain
from .core.wallet import Wallet
from .crypto.signature import EducationalMLDSASignature
from .experiments import compare_bundle_modes


def _benchmark_mldsa(iterations: int = 10) -> Dict[str, float]:
    scheme = EducationalMLDSASignature()
    keypair = scheme.keygen()
    sign_times_ms: List[float] = []
    verify_times_ms: List[float] = []

    for index in range(iterations):
        message = b"pq-bitedu-mldsa|" + str(index).encode("ascii")

        started = time.perf_counter()
        signature = scheme.sign(keypair.private_key, message)
        sign_times_ms.append((time.perf_counter() - started) * 1000.0)

        started = time.perf_counter()
        if not scheme.verify(keypair.public_key, message, signature):
            raise RuntimeError("ml-dsa benchmark verify failed")
        verify_times_ms.append((time.perf_counter() - started) * 1000.0)

    return {
        "public_key_size": scheme.estimate_public_key_size(keypair.public_key),
        "signature_size": scheme.estimate_signature_size(signature),
        "sign_time_ms_avg": round(sum(sign_times_ms) / len(sign_times_ms), 3),
        "verify_time_ms_avg": round(sum(verify_times_ms) / len(verify_times_ms), 3),
    }


def run_quantum_report() -> Dict[str, object]:
    chain = Blockchain()
    miner = Wallet("miner", signature_schemes=chain.signature_schemes)
    recipient = Wallet("recipient", signature_schemes=chain.signature_schemes)
    chain.create_genesis_block(miner.primary_pubkey_hash, data="genesis")
    chain.add_block(chain.mine_block(miner.primary_pubkey_hash, [], coinbase_data="reward"))

    comparison = compare_bundle_modes(
        miner,
        chain,
        recipient.primary_pubkey_hash,
        amount=60,
        fee=2,
    )
    timing = _benchmark_mldsa(iterations=10)

    schemes = [
        {
            "name": "比特币方案",
            "label": "Bitcoin / ECDSA-Schnorr",
            "post_quantum": False,
            "public_key_size": 32,
            "signature_size": 64,
            "tx_size": 320,
            "verification_count": 2,
            "sign_time_ms": 0.2,
            "verify_time_ms": 0.25,
            "summary": "小而快，量子风险高",
        },
        {
            "name": "原始抗量子方案",
            "label": "ML-DSA + 逐输入签名",
            "post_quantum": True,
            "public_key_size": comparison["per_input"].public_key_bytes,
            "signature_size": comparison["per_input"].signature_bytes,
            "tx_size": comparison["per_input"].tx_size,
            "verification_count": comparison["per_input"].verification_count,
            "sign_time_ms": timing["sign_time_ms_avg"],
            "verify_time_ms": round(timing["verify_time_ms_avg"] * comparison["per_input"].verification_count, 3),
            "summary": "抗量子，但体积和验签成本明显变大",
        },
        {
            "name": "创新方案",
            "label": "ML-DSA + SOIBS",
            "post_quantum": True,
            "public_key_size": comparison["soibs"].public_key_bytes,
            "signature_size": comparison["soibs"].signature_bytes,
            "tx_size": comparison["soibs"].tx_size,
            "verification_count": comparison["soibs"].verification_count,
            "sign_time_ms": timing["sign_time_ms_avg"],
            "verify_time_ms": round(timing["verify_time_ms_avg"] * comparison["soibs"].verification_count, 3),
            "summary": "保留抗量子，同时把交易体积和验签次数压下来",
        },
    ]
    return {
        "title": "PQ-BitEdu 三方案对照",
        "schemes": schemes,
        "bench_note": "同一笔两输入交易场景下的对照",
    }


def render_quantum_dashboard_html(payload: Dict[str, object]) -> str:
    report_json = json.dumps(payload, ensure_ascii=False)
    html = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PQ-BitEdu 三方案对照</title>
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
    .hero, .panel {
      background: rgba(20, 28, 44, 0.96);
      border: 1px solid var(--border);
      border-radius: 24px;
      box-shadow: 0 18px 48px rgba(0,0,0,0.22);
    }
    .hero {
      padding: 28px;
      margin-bottom: 18px;
      display: grid;
      gap: 12px;
      background: linear-gradient(135deg, rgba(23,31,49,0.96), rgba(18,27,43,0.92));
    }
    .hero h1 { margin: 0; font-size: 36px; }
    .chips { display: flex; flex-wrap: wrap; gap: 10px; }
    .chip, .pill {
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
    .panel { padding: 22px; }
    .scheme-card { border-left: 5px solid var(--accent-2); }
    .scheme-card.good { border-left-color: var(--accent); }
    .scheme-card.bad { border-left-color: var(--danger); }
    .eyebrow {
      display: inline-flex;
      padding: 6px 12px;
      border-radius: 999px;
      background: rgba(255,255,255,0.05);
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 12px;
    }
    .scheme-card h2 { margin: 0 0 8px; font-size: 25px; }
    .scheme-card p { margin: 0 0 14px; color: var(--muted); }
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
    .stat small { display: block; color: var(--muted); margin-bottom: 6px; }
    .stat strong { font-size: 22px; font-family: var(--font-mono); }
    .pill-row { display: flex; flex-wrap: wrap; gap: 8px; }
    .pill.good { background: var(--good-bg); color: #82f2a8; }
    .pill.bad { background: var(--bad-bg); color: #ffaaaa; }
    .center-stage {
      display: grid;
      grid-template-columns: minmax(0, 1.5fr) minmax(0, 1.1fr);
      gap: 18px;
      margin-bottom: 18px;
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
    .meta-box small { display: block; color: var(--muted); margin-bottom: 6px; }
    .meta-box strong { font-family: var(--font-mono); font-size: 18px; }
    @media (max-width: 1040px) {
      .center-stage { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>PQ-BitEdu 三方案对照</h1>
      <div class="chips" id="chips"></div>
    </section>

    <section class="grid-row" id="scheme-cards"></section>

    <section class="center-stage">
      <section class="panel">
        <h2>体积与验签开销</h2>
        <div class="chart-frame">
          <svg id="size-chart" viewBox="0 0 960 420" width="100%" height="100%" preserveAspectRatio="none"></svg>
        </div>
        <div class="chart-meta" id="size-chart-meta"></div>
      </section>
      <section class="panel">
        <h2>签名与验签耗时</h2>
        <div class="chart-frame">
          <svg id="time-chart" viewBox="0 0 960 420" width="100%" height="100%" preserveAspectRatio="none"></svg>
        </div>
        <div class="chart-meta" id="time-chart-meta"></div>
      </section>
    </section>
  </div>

  <script>
    const REPORT = __REPORT_JSON__;

    function addMetaBox(root, label, value) {
      const box = document.createElement("div");
      box.className = "meta-box";
      box.innerHTML = `<small>${label}</small><strong>${value}</strong>`;
      root.appendChild(box);
    }

    function renderChips() {
      const chips = document.getElementById("chips");
      [
        REPORT.bench_note,
        "三者对照: 比特币 / 原始抗量子 / 创新方案",
        "柱状图展示",
      ].forEach((text) => {
        const chip = document.createElement("div");
        chip.className = "chip";
        chip.textContent = text;
        chips.appendChild(chip);
      });
    }

    function renderSchemeCards() {
      const root = document.getElementById("scheme-cards");
      REPORT.schemes.forEach((item) => {
        const status = item.post_quantum ? "good" : "bad";
        const card = document.createElement("article");
        card.className = `panel scheme-card ${status}`;
        card.innerHTML = `
          <div class="eyebrow">${item.label}</div>
          <h2>${item.name}</h2>
          <p>${item.summary}</p>
          <div class="stats">
            <div class="stat">
              <small>公钥体积</small>
              <strong>${item.public_key_size} B</strong>
            </div>
            <div class="stat">
              <small>签名字节</small>
              <strong>${item.signature_size} B</strong>
            </div>
            <div class="stat">
              <small>交易体积</small>
              <strong>${item.tx_size} B</strong>
            </div>
            <div class="stat">
              <small>验签次数</small>
              <strong>${item.verification_count}</strong>
            </div>
          </div>
          <div class="pill-row">
            <span class="pill ${item.post_quantum ? "good" : "bad"}">${item.post_quantum ? "抗量子" : "非抗量子"}</span>
            <span class="pill">签名 ${item.sign_time_ms} ms</span>
            <span class="pill">验签 ${item.verify_time_ms} ms</span>
          </div>
        `;
        root.appendChild(card);
      });
    }

    function renderBarChart(svgId, metaId, seriesDefs) {
      const svg = document.getElementById(svgId);
      const meta = document.getElementById(metaId);
      const data = REPORT.schemes || [];
      const width = 960;
      const height = 420;
      const padding = { top: 30, right: 28, bottom: 52, left: 56 };
      const labels = data.map(item => item.name);
      const allValues = seriesDefs.flatMap(series => data.map(item => Number(item[series.key] || 0)));
      const max = Math.max(1, ...allValues);
      const span = max;
      const plotWidth = width - padding.left - padding.right;
      const groupWidth = plotWidth / Math.max(1, labels.length);
      const innerGap = 10;
      const barWidth = Math.max(18, (groupWidth - innerGap * (seriesDefs.length + 1)) / Math.max(1, seriesDefs.length));

      let grid = "";
      for (let i = 0; i < 5; i += 1) {
        const y = padding.top + i * ((height - padding.top - padding.bottom) / 4);
        const value = (max - i * (span / 4)).toFixed(0);
        grid += `<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="rgba(255,255,255,0.08)" stroke-dasharray="6 8" />`;
        grid += `<text x="${padding.left - 10}" y="${y + 4}" fill="rgba(238,243,255,0.62)" text-anchor="end" font-size="13">${value}</text>`;
      }

      let axisLabels = "";
      labels.forEach((label, index) => {
        const x = padding.left + groupWidth * index + groupWidth / 2;
        axisLabels += `<text x="${x}" y="${height - 18}" fill="rgba(238,243,255,0.58)" text-anchor="middle" font-size="12">${label}</text>`;
      });

      let bars = "";
      data.forEach((item, itemIndex) => {
        const groupStart = padding.left + groupWidth * itemIndex;
        seriesDefs.forEach((series, seriesIndex) => {
          const value = Number(item[series.key] || 0);
          const barHeight = (value / span) * (height - padding.top - padding.bottom);
          const x = groupStart + innerGap + seriesIndex * (barWidth + innerGap);
          const y = height - padding.bottom - barHeight;
          bars += `<rect x="${x}" y="${y}" width="${barWidth}" height="${barHeight}" rx="8" fill="${series.color}"></rect>`;
        });
      });

      svg.innerHTML = grid + axisLabels + bars;
      meta.innerHTML = "";
      seriesDefs.forEach(series => addMetaBox(meta, series.label, series.colorLabel));
    }

    renderChips();
    renderSchemeCards();
    renderBarChart("size-chart", "size-chart-meta", [
      { key: "public_key_size", color: "#6fd3ff", label: "蓝柱", colorLabel: "公钥体积" },
      { key: "signature_size", color: "#49d17d", label: "绿柱", colorLabel: "签名字节" },
      { key: "tx_size", color: "#ffb454", label: "橙柱", colorLabel: "交易体积" },
    ]);
    renderBarChart("time-chart", "time-chart-meta", [
      { key: "sign_time_ms", color: "#6fd3ff", label: "蓝柱", colorLabel: "签名耗时" },
      { key: "verify_time_ms", color: "#49d17d", label: "绿柱", colorLabel: "验签耗时" },
      { key: "verification_count", color: "#ff7c7c", label: "红柱", colorLabel: "验签次数" },
    ]);
  </script>
</body>
</html>"""
    return html.replace("__REPORT_JSON__", report_json)


def write_quantum_dashboard(output_path: str) -> Path:
    payload = run_quantum_report()
    html = render_quantum_dashboard_html(payload)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a standalone scheme comparison dashboard.")
    parser.add_argument("--output", default="reports/quantum_dashboard.html")
    args = parser.parse_args()
    output = write_quantum_dashboard(args.output)
    print("quantum_dashboard_written:", str(output.resolve()))


if __name__ == "__main__":
    main()
