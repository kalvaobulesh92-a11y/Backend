from rest_framework import serializers

from categories.models import ServiceCategory
from services.models import Service


class CategoryServiceSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_slug = serializers.CharField(source='category.slug', read_only=True)

    class Meta:
        model = Service
        fields = (
            'id', 'name', 'slug', 'description', 'category', 'category_name', 'category_slug',
            'is_active', 'created_at', 'updated_at'
        )
        read_only_fields = fields


class ServiceCategorySerializer(serializers.ModelSerializer):
    service_count = serializers.SerializerMethodField()
    services = CategoryServiceSerializer(many=True, read_only=True)

    class Meta:
        model = ServiceCategory
        fields = (
            'id', 'name', 'slug', 'description', 'icon', 'image', 'is_active', 'sort_order',
            'service_count', 'services', 'created_at', 'updated_at'
        )
        read_only_fields = fields

    def get_service_count(self, obj) -> int:
        return obj.services.filter(is_active=True).count()
