import pytest, requests


def test_reports_kpi_no_null():
    """API 响应中不应有 null 值，会被 ECharts 视为非法数据"""
    resp = requests.post('http://localhost:8000/api/auth/login',
        json={'username':'admin','password':'12345678'})
    token = resp.json().get('data', {}).get('access_token', '')

    resp = requests.get('http://localhost:8000/api/reports/kpi?period=month',
        headers={'Authorization': f'Bearer {token}'})
    data = resp.json().get('data', {})

    # 检查每个字段都不是 None
    for key, val in data.items():
        assert val is not None, f'{key} is None (null), ECharts will crash on this'
