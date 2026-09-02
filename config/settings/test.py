"""
Test settings: identical to dev except uses SQLite so the test suite runs
locally without a running Postgres container.
"""

from .dev import *  # noqa: F401, F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
