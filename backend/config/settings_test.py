"""Settings for pytest: sqlite, eager celery, fake keys."""
from .settings import *  # noqa: F401,F403
import os

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
FERNET_KEY = "hTGgS2LzB7l6xPHZ0M8q8Q1Xw7bXk1Q0f2s1Yq6rZbA="
OPENROUTER_API_KEY = "test-key"
RESULTS_DIR = "/tmp/nlregex-test-results"
SPARK_MASTER = "local[2]"
SPARK_DRIVER_MEMORY = "1g"
SPARK_SHUFFLE_PARTITIONS = 2
APP_REDIS_URL = os.environ.get("TEST_REDIS_URL", f"{REDIS_URL}/15")
S3_ENDPOINT_URL = None  # tests use moto, never the dev S3 mock
LLM_PROVIDER = "openrouter"
