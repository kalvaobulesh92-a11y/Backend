from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import IsCustomerOrWorker
from projects.models import Project, ProjectTask, TaskUpdate
from .serializers import (
    ProjectSerializer,
    ProjectTaskCreateSerializer,
    ProjectTaskSerializer,
    TaskTransitionSerializer,
)


def _project_queryset_for(user):
    queryset = Project.objects.select_related(
        'agreement', 'agreement__customer', 'agreement__worker', 'agreement__worker__user',
        'agreement__quotation',
    ).prefetch_related('tasks__updates__actor')
    if user.is_customer and user.is_worker:
        return queryset.filter(
            Q(agreement__customer=user) | Q(agreement__worker__user=user)
        )
    if user.is_customer:
        return queryset.filter(agreement__customer=user)
    if user.is_worker:
        return queryset.filter(agreement__worker__user=user)
    return Project.objects.none()


class ProjectViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrWorker]
    serializer_class = ProjectSerializer
    queryset = Project.objects.none()

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return self.queryset
        return _project_queryset_for(self.request.user).order_by('-created_at')

    @action(detail=True, methods=['get', 'post'])
    @transaction.atomic
    def tasks(self, request, pk=None):
        project = self.get_object()
        if request.method == 'GET':
            return Response(ProjectTaskSerializer(
                project.tasks.prefetch_related('updates__actor'),
                many=True,
                context=self.get_serializer_context(),
            ).data)

        serializer = ProjectTaskCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project = Project.objects.select_for_update().get(pk=project.pk)
        if project.status == Project.Status.COMPLETED:
            raise ValidationError('Tasks cannot be added to a completed project.')
        last_order = project.tasks.aggregate(last_order=Max('sort_order'))['last_order']
        task = serializer.save(
            project=project,
            created_by=request.user,
            sort_order=(last_order if last_order is not None else -1) + 1,
        )
        return Response(
            ProjectTaskSerializer(task, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )


class ProjectTaskViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrWorker]
    serializer_class = ProjectTaskSerializer
    queryset = ProjectTask.objects.none()

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return self.queryset
        user = self.request.user
        return ProjectTask.objects.filter(
            project__in=_project_queryset_for(user).values('pk')
        ).select_related('project', 'created_by').prefetch_related('updates__actor')

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def transition(self, request, pk=None):
        task = self.get_object()
        project = Project.objects.select_for_update().get(pk=task.project_id)
        task = ProjectTask.objects.select_for_update().get(pk=task.pk, project=project)
        serializer = TaskTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transition = serializer.validated_data['transition']
        note = serializer.validated_data.get('note', '').strip()
        agreement = project.agreement
        is_worker = request.user.is_worker and agreement.worker.user_id == request.user.id
        is_customer = request.user.is_customer and agreement.customer_id == request.user.id
        now = timezone.now()
        previous_status = task.status

        if project.status == Project.Status.COMPLETED:
            raise ValidationError('This project has already been completed.')

        if transition == 'start':
            if not is_worker:
                raise PermissionDenied('Only the assigned worker can start this task.')
            if task.status not in (ProjectTask.Status.PENDING, ProjectTask.Status.CHANGES_REQUESTED):
                raise ValidationError('Only pending or change-requested tasks can be started.')
            task.status = ProjectTask.Status.IN_PROGRESS
            task.started_at = task.started_at or now
            if project.status == Project.Status.SCHEDULED:
                project.status = Project.Status.IN_PROGRESS
                project.started_at = now
                project.save(update_fields=['status', 'started_at', 'updated_at'])
            task.save(update_fields=['status', 'started_at', 'updated_at'])

        elif transition == 'submit':
            if not is_worker:
                raise PermissionDenied('Only the assigned worker can submit task completion.')
            if task.status != ProjectTask.Status.IN_PROGRESS:
                raise ValidationError('Start the task before submitting it for review.')
            task.status = ProjectTask.Status.SUBMITTED
            task.submitted_at = now
            task.save(update_fields=['status', 'submitted_at', 'updated_at'])

        elif transition in ('approve', 'request_changes'):
            if not is_customer:
                raise PermissionDenied('Only the customer can review submitted work.')
            if task.status != ProjectTask.Status.SUBMITTED:
                raise ValidationError('Only submitted work can be reviewed.')
            if transition == 'approve':
                task.status = ProjectTask.Status.APPROVED
                task.approved_at = now
                task.save(update_fields=['status', 'approved_at', 'updated_at'])
                if not project.tasks.exclude(status=ProjectTask.Status.APPROVED).exists():
                    project.status = Project.Status.COMPLETED
                    project.completed_at = now
                    project.save(update_fields=['status', 'completed_at', 'updated_at'])
            else:
                task.status = ProjectTask.Status.CHANGES_REQUESTED
                task.save(update_fields=['status', 'updated_at'])
        else:
            raise ValidationError('Unsupported task transition.')

        TaskUpdate.objects.create(
            task=task,
            actor=request.user,
            from_status=previous_status,
            to_status=task.status,
            note=note,
        )
        return Response(ProjectTaskSerializer(task, context=self.get_serializer_context()).data)
