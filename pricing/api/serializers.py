from rest_framework import serializers

from categories.models import ServiceCategory
from services.models import Service


class PriceEstimateQuerySerializer(serializers.Serializer):
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=ServiceCategory.objects.filter(is_active=True),
        source='category',
    )
    service_id = serializers.PrimaryKeyRelatedField(
        queryset=Service.objects.filter(is_active=True),
        source='service',
        required=False,
    )

    def validate(self, attrs):
        service = attrs.get('service')
        category = attrs['category']
        if service and service.category_id != category.id:
            raise serializers.ValidationError({
                'service_id': 'Choose a service from the selected category.'
            })
        return attrs
