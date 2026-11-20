from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class TaskTemplate(models.Model):
    category = models.ForeignKey(
        'categories.ServiceCategory',
        on_delete=models.PROTECT,
        related_name='work_task_templates',
    )
    service = models.ForeignKey(
        'services.Service',
        on_delete=models.SET_NULL,
        related_name='work_task_templates',
        blank=True,
        null=True,
    )
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    estimated_days = models.PositiveSmallIntegerField(blank=True, null=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'id']
        indexes = [models.Index(fields=['category', 'service', 'is_active'])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(estimated_days__isnull=True) | models.Q(estimated_days__gt=0),
                name='template_days_positive',
            ),
        ]

    def clean(self):
        super().clean()
        if self.service_id and self.category_id and self.service.category_id != self.category_id:
            raise ValidationError({'service': 'The service must belong to the selected category.'})

    def __str__(self):
        return self.title


class WorkBreakdown(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        APPROVED = 'approved', 'Approved'

    job_request = models.OneToOneField(
        'quotations.JobRequest',
        on_delete=models.PROTECT,
        related_name='work_breakdown',
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='work_breakdowns',
    )
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DRAFT)
    revision_number = models.PositiveIntegerField(default=0)
    approved_revision = models.PositiveIntegerField(blank=True, null=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def record_revision(self, user, approved=False):
        revision_number = self.revision_number + 1
        snapshot = [
            {
                'title': task.title,
                'description': task.description,
                'sort_order': task.sort_order,
                'estimated_days': task.estimated_days,
            }
            for task in self.tasks.order_by('sort_order', 'id')
        ]
        self.revision_number = revision_number
        update_fields = ['revision_number', 'updated_at']
        if approved:
            self.status = self.Status.APPROVED
            self.approved_revision = revision_number
            update_fields.extend(['status', 'approved_revision', 'approved_at'])
        self.save(update_fields=update_fields)
        return WorkBreakdownRevision.objects.create(
            breakdown=self,
            revision_number=revision_number,
            snapshot=snapshot,
            created_by=user,
            is_approved=approved,
        )

    def __str__(self):
        return f'Work breakdown for job #{self.job_request_id}'


class WorkBreakdownTask(models.Model):
    breakdown = models.ForeignKey(WorkBreakdown, on_delete=models.CASCADE, related_name='tasks')
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    estimated_days = models.PositiveSmallIntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['breakdown', 'sort_order'], name='unique_breakdown_task_order'),
            models.CheckConstraint(
                condition=models.Q(estimated_days__isnull=True) | models.Q(estimated_days__gt=0),
                name='breakdown_task_days_positive',
            ),
        ]

    def __str__(self):
        return self.title


class WorkBreakdownRevision(models.Model):
    breakdown = models.ForeignKey(WorkBreakdown, on_delete=models.PROTECT, related_name='revisions')
    revision_number = models.PositiveIntegerField()
    snapshot = models.JSONField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='work_breakdown_revisions',
    )
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-revision_number']
        constraints = [
            models.UniqueConstraint(
                fields=['breakdown', 'revision_number'],
                name='unique_breakdown_revision_number',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Work breakdown revisions are immutable.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Work breakdown revisions cannot be deleted.')

    def __str__(self):
        return f'Revision {self.revision_number} for breakdown #{self.breakdown_id}'
