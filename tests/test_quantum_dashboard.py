from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pq_bitedu.quantum_dashboard import (
    render_quantum_dashboard_html,
    run_quantum_report,
    write_quantum_dashboard,
)


class QuantumDashboardTests(unittest.TestCase):
    def test_run_quantum_report_contains_three_way_comparison(self) -> None:
        payload = run_quantum_report()
        self.assertEqual(len(payload["schemes"]), 3)
        names = [item["name"] for item in payload["schemes"]]
        self.assertIn("比特币方案", names)
        self.assertIn("原始抗量子方案", names)
        self.assertIn("创新方案", names)

    def test_render_quantum_dashboard_contains_key_sections(self) -> None:
        payload = run_quantum_report()
        html = render_quantum_dashboard_html(payload)
        self.assertIn("三方案对照", html)
        self.assertIn("比特币方案", html)
        self.assertIn("创新方案", html)
        self.assertIn("柱状图展示", html)

    def test_write_quantum_dashboard_creates_html(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "quantum_dashboard.html"
            written = write_quantum_dashboard(str(output))
            self.assertTrue(written.exists())
            self.assertIn("体积与验签开销", written.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
