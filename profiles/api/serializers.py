from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from profiles.models import (
    Address,
    Availability,
    CustomerProfile,
    Portfolio,
    WorkerProfile,
    WorkerService,
    WorkerServiceArea,
    WorkerSkill,
)

User = get_user_model()


class UserSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'full_name', 'phone', 'profile_picture')
        read_only_fields = fields


class CustomerProfileSerializer(serializers.ModelSerializer):
    user = UserSummarySerializer(read_only=True)

    class Meta:
        model = CustomerProfile
        fields = ('id', 'user', 'gender', 'date_of_birth', 'created_at', 'updated_at')
        read_only_fields = fields


class AddressSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Address
        fields = (
            'id', 'user', 'label', 'address_line1', 'address_line2', 'locality', 'city', 'state',
            'pincode', 'latitude', 'longitude', 'is_default', 'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'user', 'created_at', 'updated_at')


class WorkerSkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkerSkill
        fields = ('id', 'name', 'created_at')
        read_only_fields = fields


class WorkerServiceSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    service_name = serializers.CharField(source='service.name', read_only=True)

    class Meta:
        model = WorkerService
        fields = (
            'id', 'category', 'category_name', 'service', 'service_name', 'description', 'price',
            'is_primary', 'created_at'
        )
        read_only_fields = fields


class WorkerServiceManagementSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    service_name = serializers.CharField(source='service.name', read_only=True)
    price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.00'),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = WorkerService
        fields = (
            'id', 'category', 'category_name', 'service', 'service_name', 'description',
            'price', 'is_primary', 'created_at',
        )
        read_only_fields = ('id', 'category_name', 'service_name', 'created_at')

    def validate(self, attrs):
        category = attrs.get('category', getattr(self.instance, 'category', None))
        service = attrs.get('service', getattr(self.instance, 'service', None))
        if service and category and service.category_id != category.id:
            raise ValidationError({'service': 'Choose a service from the selected category.'})

        worker = self.context.get('worker_profile')
        if worker and service and category:
            existing = WorkerService.objects.filter(worker=worker, category=category, service=service)
            if self.instance:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise ValidationError({'service': 'This service is already on your profile.'})
        return attrs


class WorkerServiceAreaSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkerServiceArea
        fields = (
            'id', 'locality', 'city', 'state', 'pincode', 'latitude', 'longitude',
            'radius_km', 'created_at'
        )
        read_only_fields = fields


class WorkerServiceAreaManagementSerializer(serializers.ModelSerializer):
    latitude = serializers.DecimalField(
        max_digits=9, decimal_places=6, min_value=Decimal('-90'), max_value=Decimal('90'),
        allow_null=True, required=False,
    )
    longitude = serializers.DecimalField(
        max_digits=9, decimal_places=6, min_value=Decimal('-180'), max_value=Decimal('180'),
        allow_null=True, required=False,
    )
    radius_km = serializers.IntegerField(min_value=1, max_value=20)

    class Meta:
        model = WorkerServiceArea
        fields = (
            'id', 'locality', 'city', 'state', 'pincode', 'latitude', 'longitude',
            'radius_km', 'created_at',
        )
        read_only_fields = ('id', 'created_at')

    def validate(self, attrs):
        latitude = attrs.get('latitude', getattr(self.instance, 'latitude', None))
        longitude = attrs.get('longitude', getattr(self.instance, 'longitude', None))
        if (latitude is None) != (longitude is None):
            raise ValidationError('Provide both latitude and longitude, or leave both blank.')

        worker = self.context.get('worker_profile')
        locality = attrs.get('locality', getattr(self.instance, 'locality', None))
        city = attrs.get('city', getattr(self.instance, 'city', 'Hyderabad'))
        if worker and locality and city:
            existing = WorkerServiceArea.objects.filter(worker=worker, locality=locality, city=city)
            if self.instance:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise ValidationError({'locality': 'This service area is already on your profile.'})
        return attrs


class PortfolioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Portfolio
        fields = ('id', 'title', 'description', 'image', 'is_before_after', 'created_at')
        read_only_fields = fields


class AvailabilitySerializer(serializers.ModelSerializer):
    day_name = serializers.SerializerMethodField()

    class Meta:
        model = Availability
        fields = ('id', 'day_of_week', 'day_name', 'start_time', 'end_time', 'is_available')
        read_only_fields = fields

    def get_day_name(self, obj) -> str:
        return obj.get_day_of_week_display()


class AvailabilityManagementSerializer(AvailabilitySerializer):
    class Meta(AvailabilitySerializer.Meta):
        read_only_fields = ('id', 'day_name')

    def validate(self, attrs):
        day_of_week = attrs.get('day_of_week', getattr(self.instance, 'day_of_week', None))
        start_time = attrs.get('start_time', getattr(self.instance, 'start_time', None))
        end_time = attrs.get('end_time', getattr(self.instance, 'end_time', None))
        if start_time and end_time and start_time >= end_time:
            raise ValidationError({'end_time': 'End time must be later than start time.'})

        worker = self.context.get('worker_profile')
        if worker and day_of_week is not None and start_time and end_time:
            overlapping = Availability.objects.filter(
                worker=worker,
                day_of_week=day_of_week,
                start_time__lt=end_time,
                end_time__gt=start_time,
            )
            if self.instance:
                overlapping = overlapping.exclude(pk=self.instance.pk)
            if overlapping.exists():
                raise ValidationError('This time overlaps another availability slot.')
        return attrs


class PortfolioManagementSerializer(PortfolioSerializer):
    def validate_image(self, image):
        if image.size > 10 * 1024 * 1024:
            raise ValidationError('Portfolio images must be 10 MB or smaller.')
        return image

    class Meta(PortfolioSerializer.Meta):
        read_only_fields = ('id', 'created_at')


class WorkerProfileSerializer(serializers.ModelSerializer):
    user = UserSummarySerializer(read_only=True)
    skills = WorkerSkillSerializer(many=True, read_only=True)
    worker_services = WorkerServiceSerializer(many=True, read_only=True)
    service_areas = WorkerServiceAreaSerializer(many=True, read_only=True)
    portfolio_items = PortfolioSerializer(many=True, read_only=True)
    availability_slots = AvailabilitySerializer(many=True, read_only=True)

    class Meta:
        model = WorkerProfile
        fields = (
            'id', 'user', 'bio', 'experience_years', 'starting_price', 'pricing_type', 'gender',
            'is_available', 'verification_status', 'average_rating', 'total_reviews', 'total_bookings',
            'skills', 'worker_services', 'service_areas', 'portfolio_items', 'availability_slots',
            'created_at', 'updated_at'
        )
        read_only_fields = (
            'id', 'user', 'verification_status', 'average_rating', 'total_reviews', 'total_bookings',
            'skills', 'worker_services', 'service_areas', 'portfolio_items', 'availability_slots',
            'created_at', 'updated_at'
        )
