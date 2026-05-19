@echo off
cd /d "d:\analyze ai\mes-backend"
python -m pytest tests/test_cache_store.py tests/test_rule_engine.py tests/test_celery_app.py -v --tb=short
