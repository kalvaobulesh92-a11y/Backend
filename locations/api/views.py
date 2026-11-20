from math import asin, cos, radians, sin, sqrt

from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import permissions
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from categories.models import ServiceCategory
from locations.api.serializers import NearbyWorkerQuerySerializer, NearbyWorkerResponseSerializer
from profiles.api.serializers import WorkerProfileSerializer
from profiles.models import WorkerProfile, WorkerServiceArea
from services.models import Service


EARTH_RADIUS_KM = 6371.0088


def haversine_km(latitude1, longitude1, latitude2, longitude2):
    latitude_delta = radians(latitude2 - latitude1)
    longitude_delta = radians(longitude2 - longitude1)
    latitude1 = radians(latitude1)
    latitude2 = radians(latitude2)
    haversine = (
        sin(latitude_delta / 2) ** 2
        + cos(latitude1) * cos(latitude2) * sin(longitude_delta / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * asin(sqrt(haversine))


class NearbyWorkerView(APIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = NearbyWorkerResponseSerializer

    @extend_schema(
        parameters=[NearbyWorkerQuerySerializer],
        responses=NearbyWorkerResponseSerializer,
    )
    def get(self, request):
        query_serializer = NearbyWorkerQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        params = query_serializer.validated_data

        category = None
        if params.get('category'):
            try:
                category = ServiceCategory.objects.get(slug=params['category'], is_active=True)
            except ServiceCategory.DoesNotExist as exc:
                raise NotFound('The requested service category was not found.') from exc

        service = None
        if params.get('service'):
            try:
                service = Service.objects.get(
                    slug=params['service'],
                    category=category,
                    is_active=True,
                )
            except Service.DoesNotExist as exc:
                raise NotFound('The requested service was not found in this category.') from exc

        latitude = params['latitude']
        longitude = params['longitude']
        radius_km = int(params['radius_km'])
        latitude_delta = radius_km / 110.574
        cosine = max(abs(cos(radians(latitude))), 0.000001)
        longitude_delta = min(radius_km / (111.320 * cosine), 180)

        areas = WorkerServiceArea.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False,
            latitude__gte=max(latitude - latitude_delta, -90),
            latitude__lte=min(latitude + latitude_delta, 90),
            longitude__gte=max(longitude - longitude_delta, -180),
            longitude__lte=min(longitude + longitude_delta, 180),
            worker__user__is_active=True,
            worker__user__is_worker=True,
            worker__is_available=params.get('available', True),
        ).select_related('worker__user').prefetch_related(
            'worker__skills',
            'worker__worker_services__category',
            'worker__worker_services__service',
            'worker__service_areas',
            'worker__portfolio_items',
            'worker__availability_slots',
        ).order_by('worker_id')

        if category:
            areas = areas.filter(worker__worker_services__category=category)
        if service:
            areas = areas.filter(worker__worker_services__service=service)
        if params.get('min_rating') is not None:
            areas = areas.filter(worker__average_rating__gte=params['min_rating'])
        if params.get('verified'):
            areas = areas.filter(worker__verification_status='verified')
        if params.get('search'):
            term = params['search'].strip()
            areas = areas.filter(
                Q(worker__user__full_name__icontains=term)
                | Q(worker__bio__icontains=term)
                | Q(worker__skills__name__icontains=term)
                | Q(worker__worker_services__category__name__icontains=term)
                | Q(worker__worker_services__service__name__icontains=term)
            )

        matches = {}
        for area in areas.distinct():
            area_latitude = float(area.latitude)
            area_longitude = float(area.longitude)
            distance = haversine_km(latitude, longitude, area_latitude, area_longitude)
            if distance > radius_km or distance > area.radius_km:
                continue

            existing = matches.get(area.worker_id)
            if existing is None or distance < existing['distance_km']:
                matches[area.worker_id] = {
                    'distance_km': distance,
                    'matched_service_area': {
                        'locality': area.locality,
                        'city': area.city,
                        'latitude': area_latitude,
                        'longitude': area_longitude,
                    },
                    'profile': area.worker,
                }

        ordered_matches = sorted(matches.values(), key=lambda item: (item['distance_km'], item['profile'].pk))
        page = self.paginate_queryset(ordered_matches)
        serialized = [
            {
                'distance_km': round(item['distance_km'], 2),
                'matched_service_area': item['matched_service_area'],
                'worker': WorkerProfileSerializer(item['profile'], context={'request': request}).data,
            }
            for item in page
        ]
        return self.get_paginated_response(serialized)

    def paginate_queryset(self, queryset):
        from rest_framework.pagination import PageNumberPagination

        self.paginator = PageNumberPagination()
        self.paginator.page_size = 20
        return self.paginator.paginate_queryset(queryset, self.request, view=self)

    def get_paginated_response(self, data):
        return self.paginator.get_paginated_response(data)
