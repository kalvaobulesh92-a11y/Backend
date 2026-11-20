from django.conf import settings
from django.db import models


class Conversation(models.Model):
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='customer_conversations',
    )
    worker = models.ForeignKey(
        'profiles.WorkerProfile',
        on_delete=models.CASCADE,
        related_name='conversations',
    )
    enquiry = models.OneToOneField(
        'enquiries.Enquiry',
        on_delete=models.SET_NULL,
        related_name='conversation',
        blank=True,
        null=True,
    )
    booking = models.OneToOneField(
        'bookings.Booking',
        on_delete=models.SET_NULL,
        related_name='conversation',
        blank=True,
        null=True,
    )
    job_request = models.OneToOneField(
        'quotations.JobRequest',
        on_delete=models.SET_NULL,
        related_name='conversation',
        blank=True,
        null=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [models.Index(fields=['customer', 'is_active'])]

    def __str__(self):
        return f'Conversation #{self.pk}'


class Message(models.Model):
    class MessageType(models.TextChoices):
        TEXT = 'text', 'Text'
        IMAGE = 'image', 'Image'
        FILE = 'file', 'File'
        SYSTEM = 'system', 'System'

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    message_type = models.CharField(
        max_length=8,
        choices=MessageType.choices,
        default=MessageType.TEXT,
    )
    body = models.TextField(blank=True)
    attachment = models.FileField(upload_to='messages/%Y/%m/', blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(blank=True, null=True)
    edited_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['sent_at']
        indexes = [
            models.Index(fields=['conversation', 'sent_at']),
            models.Index(fields=['sender', 'read_at']),
        ]

    def __str__(self):
        return f'Message #{self.pk} in conversation #{self.conversation_id}'
