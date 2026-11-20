from decimal import Decimal
from django.contrib.auth import get_user_model
from rest_framework import serializers

from bookings.models import Booking, BookingStatusHistory
from categories.models import ServiceCategory
from profiles.api.serializers import AddressSerializer, UserSummarySerializer, WorkerProfileSerializer
from profiles.models import Address, WorkerProfile
from services.models import Service

User = get_user_model()


class BookingStatusHistorySerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(source='changed_by.full_name', read_only=True)

    class Meta:
        model = BookingStatusHistory
        fields = ('id', 'previous_status', 'new_status', 'note', 'changed_by_name', 'created_at')
        read_only_fields = fields


class BookingServiceSummarySerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = Service
        fields = ('id', 'name', 'category_name', 'slug')
        read_only_fields = fields


class BookingWorkerSummarySerializer(serializers.ModelSerializer):
    user = UserSummarySerializer(read_only=True)

    class Meta:
        model = WorkerProfile
        fields = ('id', 'user', 'experience_years', 'starting_price', 'average_rating', 'total_reviews', 'verification_status')
        read_only_fields = fields


class BookingSerializer(serializers.ModelSerializer):
    customer = UserSummarySerializer(read_only=True)
    worker = BookingWorkerSummarySerializer(read_only=True)
    service = BookingServiceSummarySerializer(read_only=True)
    address = AddressSerializer(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    status_history = BookingStatusHistorySerializer(many=True, read_only=True)
    has_review = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = (
            'id', 'customer', 'worker', 'service', 'address',
            'scheduled_date', 'scheduled_time', 'estimated_amount', 'final_amount',
            'status', 'status_display', 'customer_notes', 'worker_notes',
            'cancellation_reason', 'completed_at', 'customer_approved_completed_at', 'cancelled_at',
            'created_at', 'updated_at', 'status_history', 'has_review',
        )
        read_only_fields = fields

    def get_has_review(self, obj) -> bool:
        return hasattr(obj, 'review') and obj.review is not None


class BookingCreateSerializer(serializers.ModelSerializer):
    worker_id = serializers.PrimaryKeyRelatedField(
        queryset=WorkerProfile.objects.filter(user__is_active=True),
        source='worker',
        write_only=True,
    )
    service_id = serializers.PrimaryKeyRelatedField(
        queryset=Service.objects.all(),
        source='service',
        write_only=True,
        required=False,
        allow_null=True,
    )
    address_id = serializers.PrimaryKeyRelatedField(
        queryset=Address.objects.all(),
        source='address',
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Booking
        fields = (
            'id', 'worker_id', 'service_id', 'address_id',
            'scheduled_date', 'scheduled_time', 'estimated_amount',
            'customer_notes',
        )
        read_only_fields = ('id',)

    def validate(self, attrs):
        request = self.context.get('request')
        user = request.user if request else None

        address = attrs.get('address')
        if not address and user:
            # Pick default or first address of the customer
            address = Address.objects.filter(user=user).order_by('-is_default', '-created_at').first()
            if not address:
                raise serializers.ValidationError({
                    'address_id': 'Please add a service address to your account first.'
                })
            attrs['address'] = address
        elif address and user and address.user_id != user.id:
            raise serializers.ValidationError({
                'address_id': 'Invalid address selected.'
            })

        worker = attrs.get('worker')
        if worker and user and worker.user_id == user.id:
            raise serializers.ValidationError({
                'worker_id': 'You cannot book your own professional profile.'
            })

        return attrs


class BookingStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Booking.Status.choices)
    worker_notes = serializers.CharField(required=False, allow_blank=True)
    cancellation_reason = serializers.CharField(required=False, allow_blank=True)
    final_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal('0.00'), required=False, allow_null=True
    )
