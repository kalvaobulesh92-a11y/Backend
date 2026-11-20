from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Enquiry(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ACCEPTED = 'accepted', 'Accepted'
        DECLINED = 'declined', 'Declined'
        CONVERTED = 'converted', 'Converted to booking'
        CANCELLED = 'cancelled', 'Cancelled'
        CLOSED = 'closed', 'Closed'

    class ContactPreference(models.TextChoices):
        CHAT = 'chat', 'In-app chat'
        CALL = 'call', 'Phone call'
        WHATSAPP = 'whatsapp', 'WhatsApp'

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='enquiries',
    )
    worker = models.ForeignKey(
        'profiles.WorkerProfile',
        on_delete=models.CASCADE,
        related_name='enquiries',
    )
    category = models.ForeignKey(
        'categories.ServiceCategory',
        on_delete=models.PROTECT,
        related_name='enquiries',
    )
    service = models.ForeignKey(
        'services.Service',
        on_delete=models.SET_NULL,
        related_name='enquiries',
        blank=True,
        null=True,
    )
    address = models.ForeignKey(
        'profiles.Address',
        on_delete=models.SET_NULL,
        related_name='enquiries',
        blank=True,
        null=True,
        help_text='Private service address; do not expose in public responses.',
    )
    subject = models.CharField(max_length=180)
    message = models.TextField()
    preferred_date = models.DateField(blank=True, null=True)
    contact_preference = models.CharField(
        max_length=10,
        choices=ContactPreference.choices,
        default=ContactPreference.CHAT,
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['worker', 'status']),
        ]

    def clean(self):
        super().clean()
        if self.service_id and self.category_id:
            if self.service.category_id != self.category_id:
                raise ValidationError({'service': 'The selected service must belong to the selected category.'})

    def __str__(self):
        return f'Enquiry #{self.pk}: {self.subject}'
