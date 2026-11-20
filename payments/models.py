import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


def generate_payout_reference_id():
    return f'kc-{uuid.uuid4().hex[:30]}'


class Payment(models.Model):
    class Status(models.TextChoices):
        CREATED = 'created', 'Created'
        PENDING = 'pending', 'Pending'
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'
        REFUNDED = 'refunded', 'Refunded'
        PARTIALLY_REFUNDED = 'partially_refunded', 'Partially refunded'

    class Method(models.TextChoices):
        RAZORPAY = 'razorpay', 'Razorpay'
        CASH = 'cash', 'Cash'
        UPI = 'upi', 'UPI'
        OTHER = 'other', 'Other'

    booking = models.ForeignKey(
        'bookings.Booking',
        on_delete=models.PROTECT,
        related_name='payments',
        blank=True,
        null=True,
    )
    agreement = models.ForeignKey(
        'quotations.WorkAgreement',
        on_delete=models.PROTECT,
        related_name='payments',
        blank=True,
        null=True,
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='payments',
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='INR')
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.RAZORPAY)
    status = models.CharField(
        max_length=18,
        choices=Status.choices,
        default=Status.CREATED,
        db_index=True,
    )
    provider_order_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    provider_payment_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    idempotency_key = models.CharField(max_length=128, blank=True, null=True, unique=True)
    receipt = models.CharField(max_length=100, blank=True)
    refunded_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    failure_reason = models.TextField(blank=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    refunded_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['booking', 'status']),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gte=0), name='payment_amount_nonnegative'),
            models.CheckConstraint(
                condition=(
                    Q(booking__isnull=False, agreement__isnull=True)
                    | Q(booking__isnull=True, agreement__isnull=False)
                ),
                name='payment_has_one_payable',
            ),
            models.CheckConstraint(
                condition=Q(refunded_amount__gte=0) & Q(refunded_amount__lte=models.F('amount')),
                name='payment_refund_within_amount',
            ),
        ]

    def __str__(self):
        return f'Payment #{self.pk}: {self.amount} {self.currency} ({self.get_status_display()})'


class PaymentProviderEvent(models.Model):
    event_id = models.CharField(max_length=100, unique=True)
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name='provider_events')
    event_type = models.CharField(max_length=80)
    provider_payment_id = models.CharField(max_length=100, blank=True)
    payload_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Payment provider events are immutable.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Payment provider events cannot be deleted.')

    def __str__(self):
        return f'{self.event_type} ({self.event_id})'


class PaymentLedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        CAPTURE = 'capture', 'Capture'
        REFUND = 'refund', 'Refund'
        PAYOUT = 'payout', 'Payout'
        PAYOUT_REVERSAL = 'payout_reversal', 'Payout reversal'

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name='ledger_entries')
    entry_type = models.CharField(max_length=16, choices=EntryType.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    provider_reference = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name='payment_ledger_amount_positive'),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Payment ledger entries are immutable.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Payment ledger entries cannot be deleted.')

    def __str__(self):
        return f'{self.entry_type} {self.amount} for payment #{self.payment_id}'


class Payout(models.Model):
    class Status(models.TextChoices):
        REQUESTED = 'requested', 'Requested'
        PROCESSING = 'processing', 'Processing'
        PAID = 'paid', 'Paid'
        FAILED = 'failed', 'Failed'
        REJECTED = 'rejected', 'Rejected'

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name='payouts')
    worker = models.ForeignKey(
        'profiles.WorkerProfile',
        on_delete=models.PROTECT,
        related_name='payouts',
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='INR')
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.REQUESTED,
        db_index=True,
    )
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    reference_id = models.CharField(
        max_length=40,
        unique=True,
        default=generate_payout_reference_id,
        editable=False,
    )
    provider_fund_account_id = models.CharField(max_length=100)
    provider_payout_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    provider_status = models.CharField(max_length=40, blank=True)
    utr = models.CharField(max_length=100, blank=True)
    failure_reason = models.CharField(max_length=500, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='reviewed_payouts',
        blank=True,
        null=True,
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-requested_at']
        indexes = [models.Index(fields=['worker', 'status'])]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name='payout_amount_positive'),
        ]

    def __str__(self):
        return f'Payout #{self.pk}: {self.amount} {self.currency} ({self.get_status_display()})'


class PayoutProviderEvent(models.Model):
    event_id = models.CharField(max_length=64, unique=True)
    payout = models.ForeignKey(Payout, on_delete=models.PROTECT, related_name='provider_events')
    event_type = models.CharField(max_length=80)
    payload_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Payout provider events are immutable.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Payout provider events cannot be deleted.')

    def __str__(self):
        return f'{self.event_type} ({self.event_id})'
