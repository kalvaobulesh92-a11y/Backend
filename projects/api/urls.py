from rest_framework.routers import DefaultRouter

from .views import ProjectTaskViewSet, ProjectViewSet

router = DefaultRouter()
router.register('tasks', ProjectTaskViewSet, basename='project-task')
router.register('', ProjectViewSet, basename='project')

urlpatterns = router.urls
