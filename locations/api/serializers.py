from math import isfinite

from rest_framework import serializers

from profiles.api.serializers import WorkerProfileSerializer


class NearbyWorkerQuerySerializer(serializers.Serializer):
    latitude = serializers.FloatField(min_value=-90, max_value=90)
    longitude = serializers.FloatField(min_value=-180, max_value=180)
    radius_km = serializers.ChoiceField(choices=(1, 3, 5, 10, 20), default=5)
    category = serializers.SlugField(required=False)
    service = serializers.SlugField(required=False)
    min_rating = serializers.FloatField(required=False, min_value=0, max_value=5)
    verified = serializers.BooleanField(required=False)
    available = serializers.BooleanField(required=False, default=True)
    search = serializers.CharField(required=False, allow_blank=False, max_length=100)

    def validate(self, attrs):
        for field in ('latitude', 'longitude', 'min_rating'):
            if field in attrs and not isfinite(attrs[field]):
                raise serializers.ValidationError({field: 'A finite number is required.'})
        if attrs.get('service') and not attrs.get('category'):
            raise serializers.ValidationError({'category': 'This field is required when filtering by service.'})
        return attrs


class MatchedServiceAreaSerializer(serializers.Serializer):
    locality = serializers.CharField()
    city = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()


class NearbyWorkerResultSerializer(serializers.Serializer):
    distance_km = serializers.FloatField()
    matched_service_area = MatchedServiceAreaSerializer()
    worker = WorkerProfileSerializer()


class NearbyWorkerResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = NearbyWorkerResultSerializer(many=True)
