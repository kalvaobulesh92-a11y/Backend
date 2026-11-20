from rest_framework import serializers

from bookings.models import Booking
from quotations.models import WorkAgreement
from payments.models import Payment, Payout


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = (
            'id', 'booking', 'agreement', 'amount', 'currency', 'method', 'status',
            'provider_order_id', 'provider_payment_id', 'receipt', 'refunded_amount',
            'failure_reason', 'paid_at', 'refunded_at', 'created_at', 'updated_at',
        )
        read_only_fields = fields


class PaymentCheckoutSerializer(serializers.Serializer):
    booking_id = serializers.PrimaryKeyRelatedField(
        queryset=Booking.objects.all(),
        source='booking',
        required=False,
    )
    agreement_id = serializers.PrimaryKeyRelatedField(
        queryset=WorkAgreement.objects.all(),
        source='agreement',
        required=False,
    )

    def validate(self, attrs):
        if ('booking' in attrs) == ('agreement' in attrs):
            raise serializers.ValidationError(
                'Provide exactly one of booking_id or agreement_id.'
            )
        return attrs


class PaymentVerifySerializer(serializers.Serializer):
    razorpay_order_id = serializers.CharField(max_length=100)
    razorpay_payment_id = serializers.CharField(max_length=100)
    razorpay_signature = serializers.CharField(max_length=256)


class PayoutSerializer(serializers.ModelSerializer):
    worker_name = serializers.CharField(source='worker.user.full_name', read_only=True)

    class Meta:
        model = Payout
        fields = (
            'id', 'payment', 'worker_name', 'amount', 'currency', 'status',
            'provider_payout_id', 'provider_status', 'utr', 'failure_reason',
            'requested_at', 'reviewed_at', 'completed_at', 'updated_at',
        )
        read_only_fields = fields


class PayoutRequestSerializer(serializers.Serializer):
    payment_id = serializers.PrimaryKeyRelatedField(
        queryset=Payment.objects.all(),
    )


class PayoutReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=('approve', 'reject'))
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)
