from django.conf import settings
from django.db import models


class Notification(models.Model):
    class NotificationType(models.TextChoices):
        ENQUIRY = 'enquiry', 'Enquiry'
        BOOKING = 'booking', 'Booking'
        QUOTATION = 'quotation', 'Quotation'
        MESSAGE = 'message', 'Message'
        REVIEW = 'review', 'Review'
        VERIFICATION = 'verification', 'Verification'
        PAYMENT = 'payment', 'Payment'
        COMPLAINT = 'complaint', 'Complaint'
        SYSTEM = 'system', 'System'

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    notification_type = models.CharField(max_length=15, choices=NotificationType.choices)
    title = models.CharField(max_length=160)
    body = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'read_at', 'created_at']),
            models.Index(fields=['recipient', 'notification_type']),
        ]

    def __str__(self):
        return f'{self.get_notification_type_display()} notification for {self.recipient}'
