"""Basic tests for AppError error model."""

import json

from app.core.errors import AppError


def test_app_error_basic_properties_and_dict():
    err = AppError("sample error", code=1234, http_status_code=400)
    assert err.message == "sample error"
    assert err.code == 1234
    assert err.http_status_code == 400
    d = err.to_dict()
    assert isinstance(d, dict)
    assert d["code"] == 1234
    assert d["message"] == "sample error"
    assert d["data"] is None

    # __str__ should include key information
    s = str(err)
    assert "AppError" in s and "1234" in s
