from django.conf import settings
from django.db import models


class VerificationDocument(models.Model):
    class DocumentType(models.TextChoices):
        IDENTITY = 'identity', 'Identity document'
        ADDRESS = 'address', 'Address proof'
        SKILL = 'skill', 'Skill certificate'
        BUSINESS = 'business', 'Business registration'
        OTHER = 'other', 'Other'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending review'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    worker = models.ForeignKey(
        'profiles.WorkerProfile',
        on_delete=models.CASCADE,
        related_name='verification_documents',
    )
    document_type = models.CharField(max_length=10, choices=DocumentType.choices)
    document = models.FileField(upload_to='verification/%Y/%m/')
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='reviewed_verification_documents',
        blank=True,
        null=True,
    )
    reviewer_note = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-uploaded_at']
        indexes = [models.Index(fields=['worker', 'status'])]

    def __str__(self):
        return f'{self.get_document_type_display()} for {self.worker}'
