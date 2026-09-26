from rest_framework import serializers


class ConnectionCreateSerializer(serializers.Serializer):
    access_key = serializers.CharField(min_length=3, max_length=128, trim_whitespace=True)
    secret_key = serializers.CharField(min_length=3, max_length=256, trim_whitespace=True, write_only=True)
    bucket = serializers.RegexField(
        regex=r"^[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]$",
        error_messages={"invalid": "Bucket names are 3-63 lowercase letters, digits, dots or hyphens."},
    )
    region = serializers.CharField(required=False, allow_blank=True, max_length=32, default="")


class FileListQuerySerializer(serializers.Serializer):
    prefix = serializers.CharField(required=False, allow_blank=True, default="", max_length=1024)


class SchemaQuerySerializer(serializers.Serializer):
    key = serializers.CharField(max_length=1024)
