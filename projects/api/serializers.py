from rest_framework import serializers

from projects.models import Project, ProjectTask, TaskUpdate
from quotations.api.serializers import WorkAgreementSerializer

class TaskUpdateSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source='actor.full_name', read_only=True)

    class Meta:
        model = TaskUpdate
        fields = ('id', 'actor_name', 'from_status', 'to_status', 'note', 'created_at')
        read_only_fields = fields


class ProjectTaskSerializer(serializers.ModelSerializer):
    updates = TaskUpdateSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)

    class Meta:
        model = ProjectTask
        fields = (
            'id', 'project', 'title', 'description', 'sort_order', 'status',
            'created_by_name', 'started_at', 'submitted_at', 'approved_at',
            'created_at', 'updated_at', 'updates',
        )
        read_only_fields = fields


class ProjectTaskCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectTask
        fields = ('title', 'description')

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError('Task title cannot be blank.')
        return value.strip()


class TaskTransitionSerializer(serializers.Serializer):
    transition = serializers.ChoiceField(
        choices=('start', 'submit', 'approve', 'request_changes'),
    )
    note = serializers.CharField(required=False, allow_blank=True, max_length=5000)

    def validate(self, attrs):
        if attrs['transition'] in ('submit', 'request_changes') and not attrs.get('note', '').strip():
            raise serializers.ValidationError({'note': 'Add a progress or change-request note.'})
        return attrs


class ProjectSerializer(serializers.ModelSerializer):
    agreement = WorkAgreementSerializer(read_only=True)
    tasks = ProjectTaskSerializer(many=True, read_only=True)

    class Meta:
        model = Project
        fields = (
            'id', 'title', 'description', 'status', 'agreement', 'tasks',
            'started_at', 'completed_at', 'created_at', 'updated_at',
        )
        read_only_fields = fields
