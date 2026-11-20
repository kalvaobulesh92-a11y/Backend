from django.conf import settings
from django.db import models


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        CONFIRMED = 'confirmed', 'Confirmed'
        IN_PROGRESS = 'in_progress', 'In progress'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'
        DISPUTED = 'disputed', 'Disputed'

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='bookings',
    )
    worker = models.ForeignKey(
        'profiles.WorkerProfile',
        on_delete=models.PROTECT,
        related_name='bookings',
    )
    service = models.ForeignKey(
        'services.Service',
        on_delete=models.SET_NULL,
        related_name='bookings',
        blank=True,
        null=True,
    )
    enquiry = models.OneToOneField(
        'enquiries.Enquiry',
        on_delete=models.SET_NULL,
        related_name='booking',
        blank=True,
        null=True,
    )
    address = models.ForeignKey(
        'profiles.Address',
        on_delete=models.PROTECT,
        related_name='bookings',
        help_text='Private service address; restrict access to booking participants and staff.',
    )
    scheduled_date = models.DateField()
    scheduled_time = models.TimeField(blank=True, null=True)
    estimated_amount = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    final_amount = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    customer_notes = models.TextField(blank=True)
    worker_notes = models.TextField(blank=True)
    cancellation_reason = models.TextField(blank=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    customer_approved_completed_at = models.DateTimeField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['worker', 'status']),
            models.Index(fields=['scheduled_date', 'status']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(estimated_amount__isnull=True) | models.Q(estimated_amount__gte=0),
                name='booking_estimated_amount_nonnegative',
            ),
            models.CheckConstraint(
                condition=models.Q(final_amount__isnull=True) | models.Q(final_amount__gte=0),
                name='booking_final_amount_nonnegative',
            ),
        ]

    def __str__(self):
        return f'Booking #{self.pk} ({self.get_status_display()})'


class BookingStatusHistory(models.Model):
    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name='status_history',
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='booking_status_changes',
        blank=True,
        null=True,
    )
    previous_status = models.CharField(max_length=12, choices=Booking.Status.choices, blank=True)
    new_status = models.CharField(max_length=12, choices=Booking.Status.choices)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name_plural = 'booking status histories'

    def __str__(self):
        return f'Booking #{self.booking_id}: {self.previous_status or "created"} -> {self.new_status}'
