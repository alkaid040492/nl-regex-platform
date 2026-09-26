import os

from celery import Celery
from celery.signals import worker_ready

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("nlregex")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(["apps.jobs"])


@worker_ready.connect
def _warm_up_spark(**_kwargs):
    """
    Start the JVM/SparkSession as soon as the worker is up, so the first job does not pay
    the ~10s cold start inside its LOAD stage. Best effort: failures are logged, not fatal.
    """
    import logging

    from django.conf import settings

    if settings.SERVICE_ROLE != "worker":
        return
    try:
        from apps.engine.session import SparkConfig, get_spark

        get_spark(SparkConfig(master=settings.SPARK_MASTER, driver_memory=settings.SPARK_DRIVER_MEMORY,
                              shuffle_partitions=settings.SPARK_SHUFFLE_PARTITIONS))
        logging.getLogger(__name__).info("SparkSession warmed up")
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("Spark warm-up failed; it will start lazily with the first job")
