import os
from pathlib import Path

from dotenv import load_dotenv

# Load .envs/.env.local automatically in dev so manage.py works without
# manually exporting variables. Docker sets env vars directly; this is a
# no-op when the file doesn't exist (e.g. inside the container).
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".envs" / ".env.local"
load_dotenv(_ENV_FILE, override=False)

from .base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "spotter_db"),
        "USER": os.environ.get("POSTGRES_USER", "postgres"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "postgres"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structured": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "DEBUG",
    },
}
