from decimal import Decimal
from math import ceil

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from profiles.models import WorkerProfile, WorkerService
from .serializers import PriceEstimateQuerySerializer

MIN_COMPARABLE_LISTINGS = 3
MIDDLE_RANGE_LIMIT = 5


def _nearest_rank(values, percentile):
    return values[max(0, ceil(percentile * len(values)) - 1)]


def _median(values):
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / Decimal('2')


def _money(value):
    return value.quantize(Decimal('0.01'))


class PriceEstimateView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        query = PriceEstimateQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        category = query.validated_data['category']
        service = query.validated_data.get('service')
        listings = WorkerService.objects.filter(
            category=category,
            worker__user__is_active=True,
            worker__user__is_worker=True,
            worker__is_available=True,
            price__gt=0,
        ).select_related('worker')
        if service:
            listings = listings.filter(service=service)
        else:
            listings = listings.filter(service__isnull=True)

        grouped = {}
        for price, pricing_type in listings.values_list('price', 'worker__pricing_type'):
            grouped.setdefault(pricing_type, []).append(price)

        estimates = []
        insufficient_groups = 0
        for pricing_type, prices in sorted(grouped.items()):
            ordered_prices = sorted(prices)
            sample_size = len(ordered_prices)
            if sample_size < MIN_COMPARABLE_LISTINGS:
                insufficient_groups += 1
                continue
            lower = _nearest_rank(ordered_prices, Decimal('0.25'))
            upper = _nearest_rank(ordered_prices, Decimal('0.75'))
            estimates.append({
                'pricing_type': pricing_type,
                'pricing_type_label': dict(
                    WorkerProfile.PRICING_TYPE
                ).get(pricing_type, pricing_type),
                'sample_size': sample_size,
                'confidence': 'low' if sample_size < MIDDLE_RANGE_LIMIT else 'moderate',
                'median': str(_money(_median(ordered_prices))),
                'middle_range': {
                    'low': str(_money(lower)),
                    'high': str(_money(upper)),
                },
                'range_method': 'Nearest-rank 25th to 75th percentiles.',
                'evidence': 'Current worker-listed service prices; these are not completed transaction prices.',
            })

        return Response({
            'category': {'id': category.id, 'name': category.name},
            'service': {'id': service.id, 'name': service.name} if service else None,
            'currency': 'INR',
            'basis': 'Current active worker service listings with an explicitly entered price.',
            'confidence_method': (
                'Low with 3-4 comparable listings; moderate with 5 or more. '
                'Confidence is never high because listing prices are self-reported.'
            ),
            'inputs': {
                'source_field': 'WorkerService.price',
                'category_id': category.id,
                'service_id': service.id if service else None,
                'eligibility': [
                    'active worker account',
                    'worker marked available',
                    'positive service listing price',
                    'matching pricing type',
                ],
            },
            'comparison_scope': 'Exact service listings' if service else 'Category-wide listings without a specific service',
            'estimates': estimates,
            'status': 'available' if estimates else 'insufficient_data',
            'suppressed_groups': insufficient_groups,
            'limitations': [
                'Prices are self-reported listings, not verified or completed transaction amounts.',
                'Listings have no structured unit; compare only within the same pricing type and confirm scope, unit, materials, and travel with the worker.',
                'Location, job complexity, materials, urgency, and taxes are not included.',
                'Confidence is capped at moderate because listing prices are not transaction evidence.',
            ],
        })
