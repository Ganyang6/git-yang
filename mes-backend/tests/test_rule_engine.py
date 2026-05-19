"""
Tests for RuleEngine.

Tests keyword matching for common manufacturing queries:
  - Known keywords (bottleneck, efficiency, therblig, etc.)
  - Unknown queries fall through to generic response
  - Case-insensitive matching
  - Context parameter (currently not used but accepted)
"""

from app.services.rule_engine import RuleEngine


class TestRuleEngine:
    def setup_method(self):
        self.engine = RuleEngine()

    def test_keyword_bottleneck(self):
        result = self.engine.generate_response("What is the bottleneck?")
        assert "bottleneck" in result.lower() or "workstation load" in result.lower()

    def test_keyword_efficiency(self):
        result = self.engine.generate_response("Efficiency analysis needed")
        assert "efficiency" in result.lower()

    def test_keyword_therblig(self):
        result = self.engine.generate_response("Therblig motion elements")
        assert "therblig" in result.lower()

    def test_keyword_balance(self):
        result = self.engine.generate_response("Line balance optimization")
        assert "balance" in result.lower()

    def test_keyword_anomaly(self):
        result = self.engine.generate_response("Anomaly detection report")
        assert "anomaly" in result.lower()

    def test_keyword_worktime(self):
        result = self.engine.generate_response("Worktime breakdown")
        assert "worktime" in result.lower()

    def test_unknown_query_fallback(self):
        result = self.engine.generate_response("xyzrandom123")
        assert "unavailable" in result.lower()

    def test_case_insensitive(self):
        result_upper = self.engine.generate_response("BOTTLENECK")
        result_lower = self.engine.generate_response("bottleneck")
        assert result_upper == result_lower

    def test_with_context_dict(self):
        """Context parameter should be accepted without error."""
        result = self.engine.generate_response(
            "efficiency",
            context={"station_id": "STA-01", "line_id": "L01"},
        )
        assert "efficiency" in result.lower()

    def test_empty_prompt(self):
        result = self.engine.generate_response("")
        assert "unavailable" in result.lower()

    def test_chinese_keyword_not_matched(self):
        """Chinese characters should fall to fallback."""
        result = self.engine.generate_response("unknown chinese chars")
        assert "unavailable" in result.lower()
