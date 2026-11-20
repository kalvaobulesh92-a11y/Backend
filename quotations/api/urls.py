from rest_framework.routers import DefaultRouter

from .views import JobRequestViewSet, QuotationViewSet

router = DefaultRouter()
router.register('jobs', JobRequestViewSet, basename='job-request')
router.register('', QuotationViewSet, basename='quotation')

urlpatterns = router.urls
