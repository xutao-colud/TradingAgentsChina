from __future__ import annotations

import unittest

from app.web.server import STATIC_DIR


class WebAnalysisProgressTest(unittest.TestCase):
    def test_analysis_progress_has_accessible_runtime_states(self) -> None:
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        styles = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="analysisProgress"', html)
        self.assertIn('role="progressbar"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn("startAnalysisProgress(payload)", script)
        self.assertIn('finishAnalysisProgress("success"', script)
        self.assertIn('finishAnalysisProgress("error"', script)
        self.assertIn('.analysis-progress[data-state="success"]', styles)
        self.assertIn('.analysis-progress[data-state="error"]', styles)
        self.assertIn("prefers-reduced-motion", styles)


if __name__ == "__main__":
    unittest.main()
