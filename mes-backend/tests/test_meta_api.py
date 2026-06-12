"""测试 /api/meta 端点 — 元数据 API。

RED 阶段：端点还不存在，测试预期失败（404）。
之后 GREEN 阶段实现后端后测试应通过。
"""
import pytest
import requests

BASE = "http://localhost:8000"
LOGIN = f"{BASE}/api/auth/login"
META = f"{BASE}/api/meta"


def _login_token():
    resp = requests.post(LOGIN, json={
        "username": "admin",
        "password": "12345678",
    })
    data = resp.json().get("data", {})
    return data.get("access_token", "")


def test_meta_endpoint_exists():
    """/api/meta 必须存在，返回 200"""
    token = _login_token()
    resp = requests.get(META, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_meta_has_required_fields():
    """必须包含 stations, shifts, lines, mod_unit, thresholds"""
    token = _login_token()
    resp = requests.get(META, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json().get("data", {})

    assert "stations" in data, "缺少 stations"
    assert isinstance(data["stations"], list), "stations 应为 list"

    assert "shifts" in data, "缺少 shifts"
    assert isinstance(data["shifts"], list), "shifts 应为 list"

    assert "lines" in data, "缺少 lines"
    assert isinstance(data["lines"], list), "lines 应为 list"

    assert "mod_unit" in data, "缺少 mod_unit"
    assert 0 < data["mod_unit"] < 1, "mod_unit 应在 (0,1) 范围内"

    assert "thresholds" in data, "缺少 thresholds"
    th = data["thresholds"]
    assert "efficiency" in th
    assert "balance_rate" in th
    assert "waste_ratio" in th


def test_meta_requires_auth():
    """未登录请求应返回 401"""
    resp = requests.get(META)
    assert resp.status_code == 401


def test_meta_stations_format():
    """stations 每项必须包含 id, name"""
    token = _login_token()
    resp = requests.get(META, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    stations = resp.json().get("data", {}).get("stations", [])
    for s in stations:
        assert "id" in s, f"station 缺少 id: {s}"
        assert "name" in s, f"station 缺少 name: {s}"


def test_meta_shifts_format():
    """shifts 每项必须包含 value, label"""
    token = _login_token()
    resp = requests.get(META, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    shifts = resp.json().get("data", {}).get("shifts", [])
    for s in shifts:
        assert "value" in s, f"shift 缺少 value: {s}"
        assert "label" in s, f"shift 缺少 label: {s}"


def test_meta_lines_format():
    """lines 每项必须包含 id, name"""
    token = _login_token()
    resp = requests.get(META, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    lines = resp.json().get("data", {}).get("lines", [])
    for s in lines:
        assert "id" in s, f"line 缺少 id: {s}"
        assert "name" in s, f"line 缺少 name: {s}"
