@echo off
cd /d "d:\analyze ai\mes-backend"
python -m pytest tests\test_cache_store.py -v --tb=long
