from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ApproveWorkBreakdownView,
    JobWorkBreakdownView,
    SuggestWorkBreakdownView,
    WorkBreakdownTaskViewSet,
)

router = DefaultRouter()
router.register('tasks', WorkBreakdownTaskViewSet, basename='work-breakdown-task')

urlpatterns = [
    path('jobs/<int:job_id>/', JobWorkBreakdownView.as_view(), name='job-work-breakdown'),
    path('jobs/<int:job_id>/suggest/', SuggestWorkBreakdownView.as_view(), name='suggest-job-work-breakdown'),
    path('jobs/<int:job_id>/approve/', ApproveWorkBreakdownView.as_view(), name='approve-job-work-breakdown'),
    path('', include(router.urls)),
]
