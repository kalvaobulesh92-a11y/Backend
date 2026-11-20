from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from categories.models import ServiceCategory
from categories.api.serializers import CategoryServiceSerializer, ServiceCategorySerializer


class ServiceCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ServiceCategory.objects.filter(is_active=True).prefetch_related('services')
    serializer_class = ServiceCategorySerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = 'slug'

    @action(detail=True, methods=['get'], url_path='services')
    def services(self, request, slug=None):
        category = self.get_object()
        services = category.services.filter(is_active=True)
        serializer = CategoryServiceSerializer(services, many=True)
        return Response(serializer.data)
