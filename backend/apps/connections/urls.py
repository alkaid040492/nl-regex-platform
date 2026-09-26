from django.urls import path

from . import views

urlpatterns = [
    path("", views.create_connection, name="connection-create"),
    path("<uuid:connection_id>/", views.connection_detail, name="connection-detail"),
    path("<uuid:connection_id>/files/", views.list_files, name="connection-files"),
    path("<uuid:connection_id>/files/schema/", views.file_schema, name="connection-file-schema"),
]
