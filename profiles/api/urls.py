from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AddressViewSet,
    CustomerProfileView,
    WorkerProfileViewSet,
    WorkerAvailabilityDetailView,
    WorkerAvailabilityListCreateView,
    WorkerPortfolioDetailView,
    WorkerPortfolioListCreateView,
    WorkerServiceAreaDetailView,
    WorkerServiceAreaListCreateView,
    WorkerServiceDetailView,
    WorkerServiceListCreateView,
)

router = DefaultRouter()
router.register(r'addresses', AddressViewSet, basename='addresses')
router.register(r'workers', WorkerProfileViewSet, basename='workers')

urlpatterns = [
    path('me/', CustomerProfileView.as_view(), name='customer-profile-me'),
    path('workers/me/services/', WorkerServiceListCreateView.as_view(), name='worker-services'),
    path(
        'workers/me/availability/',
        WorkerAvailabilityListCreateView.as_view(),
        name='worker-availability',
    ),
    path(
        'workers/me/availability/<int:pk>/',
        WorkerAvailabilityDetailView.as_view(),
        name='worker-availability-detail',
    ),
    path(
        'workers/me/portfolio/',
        WorkerPortfolioListCreateView.as_view(),
        name='worker-portfolio',
    ),
    path(
        'workers/me/portfolio/<int:pk>/',
        WorkerPortfolioDetailView.as_view(),
        name='worker-portfolio-detail',
    ),
    path(
        'workers/me/services/<int:pk>/',
        WorkerServiceDetailView.as_view(),
        name='worker-service-detail',
    ),
    path(
        'workers/me/service-areas/',
        WorkerServiceAreaListCreateView.as_view(),
        name='worker-service-areas',
    ),
    path(
        'workers/me/service-areas/<int:pk>/',
        WorkerServiceAreaDetailView.as_view(),
        name='worker-service-area-detail',
    ),
    path('', include(router.urls)),
]
