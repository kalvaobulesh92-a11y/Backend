from django.db.models import Q
from rest_framework import serializers

from workbreakdowns.models import (
    TaskTemplate,
    WorkBreakdown,
    WorkBreakdownRevision,
    WorkBreakdownTask,
)


class WorkBreakdownTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkBreakdownTask
        fields = ('id', 'title', 'description', 'sort_order', 'estimated_days', 'created_at', 'updated_at')
        read_only_fields = fields


class WorkBreakdownRevisionSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)

    class Meta:
        model = WorkBreakdownRevision
        fields = ('id', 'revision_number', 'snapshot', 'created_by_name', 'is_approved', 'created_at')
        read_only_fields = fields


class WorkBreakdownSerializer(serializers.ModelSerializer):
    tasks = WorkBreakdownTaskSerializer(many=True, read_only=True)
    revisions = WorkBreakdownRevisionSerializer(many=True, read_only=True)
    job_title = serializers.CharField(source='job_request.title', read_only=True)

    class Meta:
        model = WorkBreakdown
        fields = (
            'id', 'job_request', 'job_title', 'status', 'revision_number',
            'approved_revision', 'approved_at', 'tasks', 'revisions', 'created_at', 'updated_at',
        )
        read_only_fields = fields


class WorkBreakdownTaskCreateSerializer(serializers.ModelSerializer):
    breakdown_id = serializers.PrimaryKeyRelatedField(
        queryset=WorkBreakdown.objects.all(),
        source='breakdown',
    )
    estimated_days = serializers.IntegerField(min_value=1, max_value=365, required=False, allow_null=True)

    class Meta:
        model = WorkBreakdownTask
        fields = ('breakdown_id', 'title', 'description', 'estimated_days')

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError('Task title cannot be blank.')
        return value.strip()


class WorkBreakdownTaskEditSerializer(serializers.ModelSerializer):
    estimated_days = serializers.IntegerField(min_value=1, max_value=365, required=False, allow_null=True)

    class Meta:
        model = WorkBreakdownTask
        fields = ('title', 'description', 'estimated_days')

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError('Task title cannot be blank.')
        return value.strip()


def suggested_tasks_for(job):
    templates_query = TaskTemplate.objects.filter(category=job.category, is_active=True)
    if job.service_id:
        templates_query = templates_query.filter(
            Q(service=job.service) | Q(service__isnull=True)
        )
    else:
        templates_query = templates_query.filter(service__isnull=True)
    templates = list(templates_query)
    if job.service_id:
        templates.sort(key=lambda template: (
            template.service_id != job.service_id,
            template.sort_order,
            template.pk,
        ))
    if templates:
        return [
            {
                'title': template.title,
                'description': template.description,
                'sort_order': index,
                'estimated_days': template.estimated_days,
            }
            for index, template in enumerate(templates)
        ]
    return [{
        'title': job.title,
        'description': job.description,
        'sort_order': 0,
        'estimated_days': None,
    }]
