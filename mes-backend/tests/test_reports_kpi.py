"""
Test reports KPI metrics with proper OrderStatus integer comparison.

Verifies that report_kpi() correctly counts completed orders
(Order.status is an Integer FK, not a string).
"""

import os


def test_report_kpi_returns_nonzero_completion_rate(seed_data, client, auth_headers):
    """Given a seeded DB with one completed order, KPI completion_rate > 0.

    Regression test for: Order.status is Integer FK but reports.py
    compares with string "completed" → completion_rate always 0.
    """
    resp = client.get("/api/reports/kpi", headers=auth_headers)
    assert resp.status_code == 200, f"KPI endpoint failed: {resp.text}"
    data = resp.json()["data"]
    # The seed_data fixture creates one completed order out of three
    assert data["completionRate"] > 0, (
        f"Expected completionRate > 0, got {data['completionRate']}. "
        "This indicates Order.status string comparison bug."
    )
    assert data["totalOutput"] > 0, (
        f"Expected totalOutput > 0 (completed_qty=200), got {data['totalOutput']}. "
        "Likely bug: comparing integer FK status to string 'completed'."
    )
