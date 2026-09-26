from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("metrics/summary/", views.metrics_summary, name="metrics-summary"),
]
