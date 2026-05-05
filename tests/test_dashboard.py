from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pq_bitedu.dashboard import render_dashboard_html, run_simulation, write_dashboard


class DashboardTests(unittest.TestCase):
    def test_render_dashboard_contains_expected_sections(self) -> None:
        report = run_simulation(mode="scripted", rounds=2, model="deepseek-v4-flash")
        html = render_dashboard_html(report)
        self.assertIn("PQC 多智能体市场面板", html)
        self.assertIn("maker_mia", html)
        self.assertIn("实时币价曲线", html)
        self.assertIn("链上与市场日志", html)

    def test_write_dashboard_creates_html_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "dashboard.html"
            written = write_dashboard(str(output), mode="scripted", rounds=1, model="deepseek-v4-flash")
            self.assertTrue(written.exists())
            self.assertIn("交易员", written.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
