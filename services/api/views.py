from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, permissions, viewsets

from services.models import Service
from services.api.serializers import ServiceSerializer


class ServiceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Service.objects.filter(is_active=True).select_related('category')
    serializer_class = ServiceSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'category__slug']
    search_fields = ['name', 'description', 'category__name']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']
