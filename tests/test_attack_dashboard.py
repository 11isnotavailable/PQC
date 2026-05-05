from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pq_bitedu.attack_dashboard import (
    render_attack_dashboard_html,
    run_attack_reports,
    write_attack_dashboard,
)


class AttackDashboardTests(unittest.TestCase):
    def test_render_attack_dashboard_contains_scenarios(self) -> None:
        payload = run_attack_reports()
        html = render_attack_dashboard_html(payload)
        self.assertIn("双花攻击演示", html)
        self.assertIn("51% 私链重组演示", html)
        self.assertIn("攻击演示面板", html)

    def test_write_attack_dashboard_creates_html(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "attack_dashboard.html"
            written = write_attack_dashboard(str(output))
            self.assertTrue(written.exists())
            content = written.read_text(encoding="utf-8")
            self.assertIn("商家表面收款", content)


if __name__ == "__main__":
    unittest.main()
