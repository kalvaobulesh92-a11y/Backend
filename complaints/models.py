from django.conf import settings
from django.db import models


class Complaint(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        INVESTIGATING = 'investigating', 'Investigating'
        RESOLVED = 'resolved', 'Resolved'
        DISMISSED = 'dismissed', 'Dismissed'

    class Category(models.TextChoices):
        SERVICE_QUALITY = 'service_quality', 'Service quality'
        PAYMENT = 'payment', 'Payment'
        SAFETY = 'safety', 'Safety'
        MISCONDUCT = 'misconduct', 'Misconduct'
        OTHER = 'other', 'Other'

    booking = models.ForeignKey(
        'bookings.Booking',
        on_delete=models.SET_NULL,
        related_name='complaints',
        blank=True,
        null=True,
    )
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='raised_complaints',
    )
    against_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='complaints_against',
    )
    category = models.CharField(max_length=20, choices=Category.choices)
    subject = models.CharField(max_length=180)
    description = models.TextField()
    status = models.CharField(
        max_length=14,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    resolution = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='assigned_complaints',
        blank=True,
        null=True,
    )
    resolved_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['raised_by', 'status']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(raised_by=models.F('against_user')),
                name='complaint_parties_must_differ',
            ),
        ]

    def __str__(self):
        return f'Complaint #{self.pk}: {self.subject}'
