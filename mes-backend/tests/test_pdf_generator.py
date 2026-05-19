"""Tests for PDF report generator (T5-03).

Verifies that PDF generation works correctly for worktime and
line balance reports.
"""

from __future__ import annotations

import pytest


class TestPdfGeneratorAvailable:
    """Verify reportlab is available."""

    def test_reportlab_importable(self):
        from reportlab.lib import colors
        assert colors is not None

    def test_pdf_generator_module_importable(self):
        from app.services.pdf_generator import generate_worktime_pdf, generate_line_balance_pdf
        assert callable(generate_worktime_pdf)
        assert callable(generate_line_balance_pdf)


class TestGenerateWorktimePdf:
    """Worktime PDF generation."""

    def test_returns_bytes(self):
        from app.services.pdf_generator import generate_worktime_pdf

        data = {
            "station_id": "ws_01",
            "period": "today",
            "kpi": {"Utilization": "85.0%", "Segments": "100"},
            "therblig_stats": [
                {"symbol": "R", "name": "reach", "count": 20, "total_mod": 60.0, "total_seconds": 7.74, "is_waste": False},
            ],
            "operations": [
                {"action": "reach", "count": 20, "avg_duration_ms": 500, "total_duration_ms": 10000},
            ],
            "efficiency_ranking": [],
        }

        result = generate_worktime_pdf(data)
        assert isinstance(result, bytes)
        assert len(result) > 0
        # PDF files start with %PDF
        assert result[:4] == b"%PDF"

    def test_empty_data(self):
        from app.services.pdf_generator import generate_worktime_pdf

        data = {
            "station_id": "all",
            "period": "today",
            "kpi": {},
            "therblig_stats": [],
            "operations": [],
            "efficiency_ranking": [],
        }

        result = generate_worktime_pdf(data)
        assert isinstance(result, bytes)
        assert result[:4] == b"%PDF"

    def test_many_therblig_types(self):
        from app.services.pdf_generator import generate_worktime_pdf

        data = {
            "station_id": "ws_02",
            "period": "week",
            "kpi": {"Utilization": "72.0%", "Segments": "50"},
            "therblig_stats": [
                {"symbol": "R", "name": "reach", "count": 10, "total_mod": 30.0, "total_seconds": 3.87, "is_waste": False},
                {"symbol": "G", "name": "grasp", "count": 8, "total_mod": 8.0, "total_seconds": 1.03, "is_waste": False},
                {"symbol": "M", "name": "move", "count": 7, "total_mod": 28.0, "total_seconds": 3.61, "is_waste": False},
                {"symbol": "RL", "name": "release", "count": 6, "total_mod": 6.0, "total_seconds": 0.77, "is_waste": False},
                {"symbol": "UD", "name": "unavoidable_delay", "count": 5, "total_mod": 0.0, "total_seconds": 2.50, "is_waste": True},
                {"symbol": "AD", "name": "avoidable_delay", "count": 3, "total_mod": 0.0, "total_seconds": 1.80, "is_waste": True},
            ],
            "operations": [],
            "efficiency_ranking": [
                {"station": "ws_01", "efficiency": 0.85},
                {"station": "ws_02", "efficiency": 0.72},
            ],
        }

        result = generate_worktime_pdf(data)
        assert isinstance(result, bytes)
        assert len(result) > 1000  # substantial PDF


class TestGenerateLineBalancePdf:
    """Line balance PDF generation."""

    def test_returns_bytes(self):
        from app.services.pdf_generator import generate_line_balance_pdf

        data = {
            "line_id": "line1",
            "balance_rate": 0.78,
            "smoothness_index": 0.85,
            "stations": [
                {"name": "WS-01", "cycle_time": 12.5, "load": 1.0, "status": "bottleneck"},
                {"name": "WS-02", "cycle_time": 10.0, "load": 0.8, "status": "normal"},
                {"name": "WS-03", "cycle_time": 8.0, "load": 0.64, "status": "normal"},
            ],
            "bottleneck": {
                "station": "WS-01",
                "cycle_time": 12.5,
                "deviation": 0.25,
            },
            "ecrs_suggestions": [
                {"priority": "1", "type": "Redistribute", "description": "Move work from WS-01 to WS-03"},
            ],
        }

        result = generate_line_balance_pdf(data)
        assert isinstance(result, bytes)
        assert result[:4] == b"%PDF"

    def test_no_suggestions(self):
        from app.services.pdf_generator import generate_line_balance_pdf

        data = {
            "line_id": "line2",
            "balance_rate": 0.95,
            "smoothness_index": 0.98,
            "stations": [
                {"name": "WS-01", "cycle_time": 10.0, "load": 1.0, "status": "normal"},
                {"name": "WS-02", "cycle_time": 9.5, "load": 0.95, "status": "normal"},
            ],
            "bottleneck": {
                "station": "N/A",
                "cycle_time": 0,
                "deviation": 0,
            },
            "ecrs_suggestions": [],
        }

        result = generate_line_balance_pdf(data)
        assert isinstance(result, bytes)
        assert result[:4] == b"%PDF"

    def test_empty_stations(self):
        from app.services.pdf_generator import generate_line_balance_pdf

        data = {
            "line_id": "empty_line",
            "balance_rate": 0.0,
            "smoothness_index": 0.0,
            "stations": [],
            "bottleneck": {},
            "ecrs_suggestions": [],
        }

        result = generate_line_balance_pdf(data)
        assert isinstance(result, bytes)
