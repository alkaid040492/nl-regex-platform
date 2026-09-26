from django.urls import path

from . import views

urlpatterns = [
    path("", views.job_collection, name="job-collection"),
    path("<uuid:job_id>/", views.job_detail, name="job-detail"),
    path("<uuid:job_id>/cancel/", views.job_cancel, name="job-cancel"),
    path("<uuid:job_id>/result/", views.job_result, name="job-result"),
]
