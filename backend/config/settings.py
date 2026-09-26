"""
Django settings. Everything is environment-driven; see .env.example for the full list.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(int(default))).lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# --- core -------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-secret-key")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,web") or ["*"]
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if "." in h and h not in {"127.0.0.1"}]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "corsheaders",
    "apps.core",
    "apps.connections",
    "apps.jobs",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": False,
        "OPTIONS": {"context_processors": []},
    }
]

# --- database ---------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "nlregex"),
        "USER": env("POSTGRES_USER", "nlregex"),
        "PASSWORD": env("POSTGRES_PASSWORD", "nlregex"),
        "HOST": env("POSTGRES_HOST", "postgres"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

# --- redis / celery ---------------------------------------------------------
REDIS_URL = env("REDIS_URL", "redis://redis:6379")
CELERY_BROKER_URL = f"{REDIS_URL}/0"
CELERY_RESULT_BACKEND = f"{REDIS_URL}/1"
APP_REDIS_URL = f"{REDIS_URL}/2"

CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_SOFT_TIME_LIMIT = int(env("CELERY_TASK_SOFT_TIME_LIMIT", "1800"))
CELERY_TASK_TIME_LIMIT = int(env("CELERY_TASK_TIME_LIMIT", "1900"))
CELERY_WORKER_SEND_TASK_EVENTS = True
CELERY_TASK_SEND_SENT_EVENT = True
CELERY_RESULT_EXPIRES = 60 * 60 * 24
CELERY_TASK_ALWAYS_EAGER = False
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# --- api --------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    "UNAUTHENTICATED_USER": None,
}
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
CORS_ALLOW_ALL_ORIGINS = DEBUG

# --- domain settings --------------------------------------------------------
FERNET_KEY = env("FERNET_KEY", "")
CONNECTION_TTL_SECONDS = int(env("CONNECTION_TTL_SECONDS", "7200"))
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL") or None
AWS_DEFAULT_REGION = env("AWS_DEFAULT_REGION", "us-east-1")

# "openrouter" (default) or "fake" (deterministic email regex, for local dev without a key)
LLM_PROVIDER = env("LLM_PROVIDER", "openrouter").lower()
OPENROUTER_API_KEY = env("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = env("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5")
OPENROUTER_BASE_URL = env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
LLM_CACHE_TTL_SECONDS = int(env("LLM_CACHE_TTL_SECONDS", str(7 * 24 * 3600)))

SERVICE_ROLE = env("SERVICE_ROLE", "web")
SPARK_MASTER = env("SPARK_MASTER", "local[*]")
SPARK_DRIVER_MEMORY = env("SPARK_DRIVER_MEMORY", "3g")
SPARK_SHUFFLE_PARTITIONS = int(env("SPARK_SHUFFLE_PARTITIONS", "16"))
RESULTS_DIR = env("RESULTS_DIR", "/data/results")

RESULT_PAGE_SIZE_DEFAULT = 50
RESULT_PAGE_SIZE_MAX = 500

# --- logging ----------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "mask_secrets": {"()": "apps.core.logging.SecretMaskingFilter"},
    },
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.json.JsonFormatter",
            "fmt": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "plain" if DEBUG else "json",
            "filters": ["mask_secrets"],
        }
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {"level": "WARNING"},
        "py4j": {"level": "WARNING"},
        "botocore": {"level": "WARNING"},
        "urllib3": {"level": "WARNING"},
    },
}
