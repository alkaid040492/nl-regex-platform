"""
Delete Parquet results (and clear result_path) for jobs older than N days.

    python manage.py clean_results --older-than 7 [--dry-run]

Meant for a daily cron on the host; results are a cache of the last run, not a system of record.
"""
from __future__ import annotations

import os
import shutil
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.jobs.models import Job


class Command(BaseCommand):
    help = "Remove result files of jobs finished more than --older-than days ago."

    def add_arguments(self, parser):
        parser.add_argument("--older-than", type=int, default=7, help="days")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(days=opts["older_than"])
        jobs = Job.objects.filter(finished_at__lt=cutoff).exclude(result_path="")
        removed = 0
        for job in jobs:
            path = job.result_path
            if path and os.path.isdir(path) and os.path.realpath(path).startswith(os.path.realpath(settings.RESULTS_DIR)):
                self.stdout.write(f"{'would remove' if opts['dry_run'] else 'removing'} {path}")
                if not opts["dry_run"]:
                    shutil.rmtree(path, ignore_errors=True)
            if not opts["dry_run"]:
                Job.objects.filter(pk=job.pk).update(result_path="")
            removed += 1

        # orphan directories (job row deleted, files left behind)
        known = set(Job.objects.exclude(result_path="").values_list("result_path", flat=True))
        if os.path.isdir(settings.RESULTS_DIR):
            for name in os.listdir(settings.RESULTS_DIR):
                path = os.path.join(settings.RESULTS_DIR, name)
                if path not in known and os.path.isdir(path):
                    mtime = os.path.getmtime(path)
                    if mtime < cutoff.timestamp():
                        self.stdout.write(f"{'would remove' if opts['dry_run'] else 'removing'} orphan {path}")
                        if not opts["dry_run"]:
                            shutil.rmtree(path, ignore_errors=True)
                        removed += 1
        self.stdout.write(self.style.SUCCESS(f"{removed} result set(s) processed"))
