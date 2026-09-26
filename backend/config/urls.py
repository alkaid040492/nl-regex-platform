from django.urls import include, path

urlpatterns = [
    path("api/", include("apps.core.urls")),
    path("api/connections/", include("apps.connections.urls")),
    path("api/jobs/", include("apps.jobs.urls")),
]
