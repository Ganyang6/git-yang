#!/usr/bin/env python3
"""List configured auth users (sanitized).

Usage: python scripts/list_auth.py
"""
import sys

def main():
    try:
        from app.core.config import load_app_config
        cfg = load_app_config()
        users = getattr(cfg.auth, 'users', []) or []
        if not users:
            print("admin (admin)")
            return
        for u in users:
            username = u.get('username', '')
            role = u.get('role', '')
            name = u.get('display_name', username)
            print(f"{username} ({role}) - {name}")
    except Exception as e:
        print(f"Error listing auth users: {e}", file=sys.stderr)
        raise

if __name__ == '__main__':
    main()
