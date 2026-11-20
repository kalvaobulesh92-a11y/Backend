from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Project(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = 'scheduled', 'Scheduled'
        IN_PROGRESS = 'in_progress', 'In progress'
        COMPLETED = 'completed', 'Completed'

    agreement = models.OneToOneField(
        'quotations.WorkAgreement',
        on_delete=models.PROTECT,
        related_name='project',
    )
    title = models.CharField(max_length=180)
    description = models.TextField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)
    started_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', 'created_at'])]

    def __str__(self):
        return self.title


class ProjectTask(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        IN_PROGRESS = 'in_progress', 'In progress'
        SUBMITTED = 'submitted', 'Completion submitted'
        CHANGES_REQUESTED = 'changes_requested', 'Changes requested'
        APPROVED = 'approved', 'Approved'

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name='tasks')
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='project_tasks_created',
    )
    started_at = models.DateTimeField(blank=True, null=True)
    submitted_at = models.DateTimeField(blank=True, null=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['project', 'sort_order'], name='unique_project_task_order'),
        ]

    def delete(self, *args, **kwargs):
        if self.status != self.Status.PENDING:
            raise ValidationError('A task that has started cannot be deleted.')
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f'{self.project.title}: {self.title}'


class TaskUpdate(models.Model):
    task = models.ForeignKey(ProjectTask, on_delete=models.PROTECT, related_name='updates')
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='task_updates',
    )
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']

    def __str__(self):
        return f'Task #{self.task_id}: {self.to_status}'
