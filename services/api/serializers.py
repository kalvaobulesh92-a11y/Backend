from rest_framework import serializers

from services.models import Service


class ServiceSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_slug = serializers.CharField(source='category.slug', read_only=True)

    class Meta:
        model = Service
        fields = (
            'id', 'category', 'category_name', 'category_slug', 'name', 'slug', 'description',
            'is_active', 'created_at', 'updated_at'
        )
        read_only_fields = fields
