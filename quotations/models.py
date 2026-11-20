from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class JobRequest(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        IN_REVIEW = 'in_review', 'In review'
        AWARDED = 'awarded', 'Awarded'
        CANCELLED = 'cancelled', 'Cancelled'
        CLOSED = 'closed', 'Closed'

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='job_requests',
    )
    category = models.ForeignKey(
        'categories.ServiceCategory',
        on_delete=models.PROTECT,
        related_name='job_requests',
    )
    service = models.ForeignKey(
        'services.Service',
        on_delete=models.SET_NULL,
        related_name='job_requests',
        blank=True,
        null=True,
    )
    address = models.ForeignKey(
        'profiles.Address',
        on_delete=models.SET_NULL,
        related_name='job_requests',
        blank=True,
        null=True,
        help_text='Private service address; do not expose in public job listings.',
    )
    title = models.CharField(max_length=180)
    description = models.TextField()
    budget_min = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    budget_max = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    preferred_date = models.DateField(blank=True, null=True)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    expires_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['category', 'status']),
            models.Index(fields=['customer', 'status']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(budget_min__isnull=True) | models.Q(budget_min__gte=0),
                name='job_budget_min_nonnegative',
            ),
            models.CheckConstraint(
                condition=models.Q(budget_max__isnull=True) | models.Q(budget_max__gte=0),
                name='job_budget_max_nonnegative',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(budget_min__isnull=True)
                    | models.Q(budget_max__isnull=True)
                    | models.Q(budget_min__lte=models.F('budget_max'))
                ),
                name='job_budget_min_lte_max',
            ),
        ]

    def clean(self):
        super().clean()
        if self.service_id and self.category_id:
            if self.service.category_id != self.category_id:
                raise ValidationError({'service': 'The selected service must belong to the selected category.'})

    def __str__(self):
        return self.title


class Quotation(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ACCEPTED = 'accepted', 'Accepted'
        DECLINED = 'declined', 'Declined'
        WITHDRAWN = 'withdrawn', 'Withdrawn'
        EXPIRED = 'expired', 'Expired'

    job_request = models.ForeignKey(
        JobRequest,
        on_delete=models.CASCADE,
        related_name='quotations',
    )
    worker = models.ForeignKey(
        'profiles.WorkerProfile',
        on_delete=models.CASCADE,
        related_name='quotations',
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    message = models.TextField(blank=True)
    estimated_days = models.PositiveSmallIntegerField(blank=True, null=True)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    valid_until = models.DateTimeField(blank=True, null=True)
    accepted_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['job_request', 'worker'], name='unique_worker_quotation_per_job'),
            models.CheckConstraint(condition=models.Q(amount__gte=0), name='quotation_amount_nonnegative'),
        ]

    def __str__(self):
        return f'Quotation #{self.pk} for {self.job_request}'


class QuotationRevision(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ACCEPTED = 'accepted', 'Accepted'
        REJECTED = 'rejected', 'Rejected'
        REVISED = 'revised', 'Applied by worker'

    quotation = models.ForeignKey(
        Quotation,
        on_delete=models.CASCADE,
        related_name='revisions',
    )
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='quotation_revisions_proposed',
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    message = models.TextField(blank=True)
    estimated_days = models.PositiveSmallIntegerField(blank=True, null=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    response_message = models.TextField(blank=True)
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='quotation_revisions_responded',
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['quotation', 'status', 'created_at'])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='quotation_revision_amount_positive',
            ),
        ]

    def __str__(self):
        return f'Revision #{self.pk} for quotation #{self.quotation_id}'


class WorkAgreement(models.Model):
    job_request = models.OneToOneField(
        JobRequest,
        on_delete=models.PROTECT,
        related_name='work_agreement',
    )
    quotation = models.OneToOneField(
        Quotation,
        on_delete=models.PROTECT,
        related_name='work_agreement',
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='work_agreements_as_customer',
    )
    worker = models.ForeignKey(
        'profiles.WorkerProfile',
        on_delete=models.PROTECT,
        related_name='work_agreements',
    )
    scope_snapshot = models.JSONField()
    terms_snapshot = models.JSONField()
    accepted_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-accepted_at']

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Accepted work agreements are immutable.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Accepted work agreements cannot be deleted.')

    def __str__(self):
        return f'Agreement for job #{self.job_request_id}'
