from rest_framework import serializers

from profiles.api.serializers import UserSummarySerializer
from bookings.models import Booking
from profiles.models import WorkerProfile
from reviews.models import Review


class ReviewSerializer(serializers.ModelSerializer):
    customer = UserSummarySerializer(read_only=True)
    worker_name = serializers.CharField(source='worker.user.full_name', read_only=True)

    class Meta:
        model = Review
        fields = (
            'id', 'booking', 'customer', 'worker', 'worker_name',
            'rating', 'title', 'comment', 'is_public',
            'worker_reply', 'worker_replied_at',
            'created_at', 'updated_at',
        )
        read_only_fields = (
            'id', 'customer', 'worker', 'worker_name', 'is_public',
            'worker_reply', 'worker_replied_at', 'created_at', 'updated_at',
        )


class ReviewCreateSerializer(serializers.ModelSerializer):
    booking_id = serializers.PrimaryKeyRelatedField(
        queryset=Booking.objects.all(),
        source='booking',
        write_only=True,
    )

    class Meta:
        model = Review
        fields = ('id', 'booking_id', 'rating', 'title', 'comment')
        read_only_fields = ('id',)

    def validate(self, attrs):
        booking = attrs.get('booking')
        request = self.context.get('request')
        user = request.user if request else None

        if not user or booking.customer_id != user.id:
            raise serializers.ValidationError({'booking_id': 'You can only review your own bookings.'})

        if booking.status != Booking.Status.COMPLETED:
            raise serializers.ValidationError({'booking_id': 'You can only review a completed booking.'})

        if hasattr(booking, 'review') and booking.review is not None:
            raise serializers.ValidationError({'booking_id': 'A review has already been submitted for this booking.'})

        rating = attrs.get('rating')
        if not (1 <= rating <= 5):
            raise serializers.ValidationError({'rating': 'Rating must be between 1 and 5.'})

        return attrs


class ReviewReplySerializer(serializers.Serializer):
    worker_reply = serializers.CharField(required=True, allow_blank=False, max_length=1000)
