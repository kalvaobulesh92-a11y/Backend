from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import IsCustomer
from quotations.models import JobRequest
from workbreakdowns.models import WorkBreakdown, WorkBreakdownTask
from .serializers import (
    WorkBreakdownSerializer,
    WorkBreakdownTaskCreateSerializer,
    WorkBreakdownTaskEditSerializer,
    WorkBreakdownTaskSerializer,
    suggested_tasks_for,
)

MAX_BREAKDOWN_TASKS = 30


class IsWorkBreakdownCustomer(IsCustomer):
    def has_object_permission(self, request, view, obj):
        return bool(
            self.has_permission(request, view)
            and obj.breakdown.customer_id == request.user.pk
        )


def _owned_job_or_404(request, job_id, lock=False):
    queryset = JobRequest.objects
    if lock:
        queryset = queryset.select_for_update()
    return get_object_or_404(queryset, pk=job_id, customer=request.user)


def _assert_editable(breakdown):
    if breakdown.status != WorkBreakdown.Status.DRAFT:
        raise ValidationError('An approved work breakdown cannot be edited.')
    if breakdown.job_request.status != JobRequest.Status.OPEN:
        raise ValidationError('The work breakdown is locked after quotations begin.')
    if breakdown.job_request.quotations.exists():
        raise ValidationError('The work breakdown is locked after quotations begin.')


def _lock_editable_breakdown(breakdown_id):
    job_id = WorkBreakdown.objects.only('job_request_id').get(pk=breakdown_id).job_request_id
    job = JobRequest.objects.select_for_update().get(pk=job_id)
    breakdown = WorkBreakdown.objects.select_for_update().select_related('job_request').get(
        pk=breakdown_id
    )
    _assert_editable(breakdown)
    return breakdown


class JobWorkBreakdownView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated, IsCustomer]
    queryset = WorkBreakdown.objects.none()
    serializer_class = WorkBreakdownSerializer

    def get(self, request, job_id):
        job = _owned_job_or_404(request, job_id)
        breakdown = get_object_or_404(
            WorkBreakdown.objects.prefetch_related('tasks', 'revisions__created_by'),
            job_request=job,
        )
        return Response(WorkBreakdownSerializer(breakdown, context=self.get_serializer_context()).data)


class SuggestWorkBreakdownView(JobWorkBreakdownView):
    @transaction.atomic
    def post(self, request, job_id):
        job = _owned_job_or_404(request, job_id, lock=True)
        try:
            breakdown = WorkBreakdown.objects.select_for_update().get(job_request=job)
            _assert_editable(breakdown)
            if breakdown.tasks.exists():
                return Response(WorkBreakdownSerializer(breakdown).data)
        except WorkBreakdown.DoesNotExist:
            breakdown = WorkBreakdown.objects.create(job_request=job, customer=request.user)

        suggestions = suggested_tasks_for(job)
        if len(suggestions) > MAX_BREAKDOWN_TASKS:
            raise ValidationError(
                f'Task templates exceed the maximum of {MAX_BREAKDOWN_TASKS} tasks.'
            )
        for item in suggestions:
            WorkBreakdownTask.objects.create(breakdown=breakdown, **item)
        breakdown.record_revision(request.user)
        return Response(
            WorkBreakdownSerializer(breakdown, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )


class ApproveWorkBreakdownView(JobWorkBreakdownView):
    @transaction.atomic
    def post(self, request, job_id):
        job = _owned_job_or_404(request, job_id, lock=True)
        breakdown = get_object_or_404(
            WorkBreakdown.objects.select_for_update().prefetch_related('tasks'),
            job_request=job,
        )
        if breakdown.status == WorkBreakdown.Status.APPROVED:
            return Response(WorkBreakdownSerializer(breakdown).data)
        _assert_editable(breakdown)
        if not breakdown.tasks.exists():
            raise ValidationError('Add at least one task before approving the breakdown.')
        breakdown.approved_at = timezone.now()
        breakdown.record_revision(request.user, approved=True)
        return Response(WorkBreakdownSerializer(breakdown).data)


class WorkBreakdownTaskViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsWorkBreakdownCustomer]
    queryset = WorkBreakdownTask.objects.none()
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return self.queryset
        return WorkBreakdownTask.objects.filter(
            breakdown__customer=self.request.user
        ).select_related('breakdown', 'breakdown__job_request').order_by('sort_order', 'id')

    def get_serializer_class(self):
        if self.action == 'create':
            return WorkBreakdownTaskCreateSerializer
        if self.action in ('update', 'partial_update'):
            return WorkBreakdownTaskEditSerializer
        return WorkBreakdownTaskSerializer

    @transaction.atomic
    def perform_create(self, serializer):
        breakdown_id = serializer.validated_data['breakdown'].pk
        breakdown = WorkBreakdown.objects.get(pk=breakdown_id)
        if breakdown.customer_id != self.request.user.id:
            raise PermissionDenied("You cannot edit another customer's work breakdown.")
        breakdown = _lock_editable_breakdown(breakdown.pk)
        if breakdown.tasks.count() >= MAX_BREAKDOWN_TASKS:
            raise ValidationError(f'A work breakdown can contain at most {MAX_BREAKDOWN_TASKS} tasks.')
        last_order = breakdown.tasks.aggregate(last_order=Max('sort_order'))['last_order']
        task = serializer.save(
            breakdown=breakdown,
            sort_order=(last_order if last_order is not None else -1) + 1,
        )
        breakdown.record_revision(self.request.user)
        self._saved_task = task

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        return Response(
            WorkBreakdownTaskSerializer(self._saved_task, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @transaction.atomic
    def perform_update(self, serializer):
        breakdown = _lock_editable_breakdown(serializer.instance.breakdown_id)
        task = serializer.save()
        breakdown.record_revision(self.request.user)
        self._saved_task = task

    def partial_update(self, request, *args, **kwargs):
        response = super().partial_update(request, *args, **kwargs)
        return Response(
            WorkBreakdownTaskSerializer(self._saved_task, context=self.get_serializer_context()).data
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        breakdown = _lock_editable_breakdown(instance.breakdown_id)
        instance.delete()
        breakdown.record_revision(self.request.user)
