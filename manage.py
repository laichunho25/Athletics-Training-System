#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

# ATM 專屬埠號。其他 Django 專案佔用 8000/8001，這裡固定用 8200 避免撞埠。
ATM_DEFAULT_PORT = "8200"


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

    # `python manage.py runserver`（未指定埠號）→ 自動用 ATM 專屬埠號
    if len(sys.argv) >= 2 and sys.argv[1] == 'runserver':
        rest = [a for a in sys.argv[2:] if not a.startswith('-')]
        if not rest:
            sys.argv.append(f'127.0.0.1:{ATM_DEFAULT_PORT}')

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
