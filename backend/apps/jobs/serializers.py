from __future__ import annotations

import re

from django.conf import settings
from rest_framework import serializers

from .models import Job

_COLUMN_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


class JobCreateSerializer(serializers.Serializer):
    connection_id = serializers.UUIDField()
    file_key = serializers.CharField(max_length=1024)
    transform_type = serializers.ChoiceField(choices=Job.TransformType.choices)
    prompt = serializers.CharField(min_length=3, max_length=2000, trim_whitespace=True)
    replacement = serializers.CharField(required=False, allow_blank=True, default="", max_length=500, trim_whitespace=False)
    columns = serializers.ListField(child=serializers.CharField(max_length=255), min_length=1, max_length=50)
    new_column_name = serializers.CharField(required=False, allow_blank=True, default="", max_length=128)

    def validate_columns(self, value: list[str]) -> list[str]:
        seen: list[str] = []
        for c in value:
            if c not in seen:
                seen.append(c)
        return seen

    def validate(self, attrs):
        t = attrs["transform_type"]
        if t == Job.TransformType.EXTRACT:
            name = attrs.get("new_column_name", "")
            if not name:
                raise serializers.ValidationError({"new_column_name": "Required for EXTRACT."})
            if not _COLUMN_NAME.match(name):
                raise serializers.ValidationError({"new_column_name": "Use letters, digits and underscores only."})
            if name in attrs["columns"]:
                raise serializers.ValidationError({"new_column_name": "Must differ from the source column."})
        return attrs


class JobSerializer(serializers.ModelSerializer):
    duration_seconds = serializers.FloatField(read_only=True)

    class Meta:
        model = Job
        fields = [
            "id",
            "status",
            "stage",
            "progress",
            "transform_type",
            "prompt",
            "replacement",
            "columns",
            "new_column_name",
            "bucket",
            "file_key",
            "regex_pattern",
            "replacement_template",
            "llm_explanation",
            "llm_cache_hit",
            "row_count",
            "matched_rows",
            "result_columns",
            "error_code",
            "error_message",
            "created_at",
            "started_at",
            "finished_at",
            "duration_seconds",
        ]
        read_only_fields = fields


class ResultQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(
        required=False, min_value=1, max_value=settings.RESULT_PAGE_SIZE_MAX, default=settings.RESULT_PAGE_SIZE_DEFAULT
    )
    only_matched = serializers.BooleanField(required=False, default=False)
