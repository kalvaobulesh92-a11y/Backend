from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import IsCustomerOrWorker
from profiles.models import WorkerProfile
from projects.services import create_project_for_agreement
from quotations.models import JobRequest, Quotation, QuotationRevision, WorkAgreement
from workbreakdowns.models import WorkBreakdown
from .serializers import (
    JobRequestCreateSerializer,
    JobRequestSerializer,
    QuotationCreateSerializer,
    QuotationProposalSerializer,
    QuotationRevisionResponseSerializer,
    QuotationSerializer,
    WorkAgreementSerializer,
)


def _require_role(user, role):
    if not getattr(user, f'is_{role}', False):
        raise PermissionDenied(f'{role.title()} access is required for this operation.')


def _refresh_job_status(job):
    if job.status == JobRequest.Status.IN_REVIEW and not job.quotations.filter(
        status=Quotation.Status.PENDING
    ).exists():
        job.status = JobRequest.Status.OPEN
        job.save(update_fields=['status', 'updated_at'])


class JobRequestViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrWorker]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return JobRequest.objects.none()
        queryset = JobRequest.objects.annotate(
            has_quotations=Exists(Quotation.objects.filter(job_request=OuterRef('pk')))
        ).select_related('customer', 'category', 'service').prefetch_related(
            'work_breakdown__tasks',
            'work_breakdown__revisions__created_by',
        )
        role = self.request.query_params.get('role')
        if user.is_staff or user.is_superuser:
            if role == 'worker':
                queryset = queryset.filter(status__in=[
                    JobRequest.Status.OPEN,
                    JobRequest.Status.IN_REVIEW,
                ])
            elif role == 'customer':
                queryset = queryset.filter(customer=user)
        elif role == 'worker':
            if not user.is_worker:
                return JobRequest.objects.none()
            queryset = queryset.filter(
                status__in=[JobRequest.Status.OPEN, JobRequest.Status.IN_REVIEW]
            ).exclude(customer=user)
        elif role == 'customer':
            if not user.is_customer:
                return JobRequest.objects.none()
            queryset = queryset.filter(customer=user)
        elif user.is_customer:
            queryset = queryset.filter(customer=user)
        elif user.is_worker:
            queryset = queryset.filter(
                status__in=[JobRequest.Status.OPEN, JobRequest.Status.IN_REVIEW]
            ).exclude(customer=user)
        else:
            return JobRequest.objects.none()
        return queryset.order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return JobRequestCreateSerializer
        return JobRequestSerializer

    def create(self, request, *args, **kwargs):
        _require_role(request.user, 'customer')
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(customer=self.request.user)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def cancel(self, request, pk=None):
        _require_role(request.user, 'customer')
        job = self.get_object()
        job = JobRequest.objects.select_for_update().get(pk=job.pk)
        if job.customer_id != request.user.id:
            raise PermissionDenied('You cannot cancel this job request.')
        if job.status in (JobRequest.Status.AWARDED, JobRequest.Status.CANCELLED, JobRequest.Status.CLOSED):
            raise ValidationError(f'A job request in {job.status} status cannot be cancelled.')
        job.status = JobRequest.Status.CANCELLED
        job.save(update_fields=['status', 'updated_at'])
        job.quotations.filter(status=Quotation.Status.PENDING).update(status=Quotation.Status.DECLINED)
        QuotationRevision.objects.filter(
            quotation__job_request=job,
            status=QuotationRevision.Status.PENDING,
        ).update(
            status=QuotationRevision.Status.REJECTED,
            responded_by=request.user,
            responded_at=timezone.now(),
            response_message='Job request cancelled by customer.',
        )
        return Response(JobRequestSerializer(job, context=self.get_serializer_context()).data)


class QuotationViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrWorker]
    http_method_names = ['get', 'post', 'head', 'options']
    serializer_class = QuotationSerializer

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Quotation.objects.none()
        queryset = Quotation.objects.select_related(
            'job_request', 'job_request__customer', 'job_request__category', 'job_request__service',
            'job_request__address', 'worker', 'worker__user', 'work_agreement',
        ).prefetch_related('revisions__proposed_by', 'revisions__responded_by')
        role = self.request.query_params.get('role')
        if user.is_staff or user.is_superuser:
            if role == 'customer':
                queryset = queryset.filter(job_request__customer=user)
            elif role == 'worker':
                queryset = queryset.filter(worker__user=user)
        elif role == 'customer':
            if not user.is_customer:
                return Quotation.objects.none()
            queryset = queryset.filter(job_request__customer=user)
        elif role == 'worker':
            if not user.is_worker:
                return Quotation.objects.none()
            queryset = queryset.filter(worker__user=user)
        elif user.is_customer and user.is_worker:
            queryset = queryset.filter(Q(job_request__customer=user) | Q(worker__user=user))
        elif user.is_customer:
            queryset = queryset.filter(job_request__customer=user)
        elif user.is_worker:
            queryset = queryset.filter(worker__user=user)
        else:
            return Quotation.objects.none()

        job_id = self.request.query_params.get('job_request')
        if job_id:
            if not job_id.isdecimal():
                return Quotation.objects.none()
            queryset = queryset.filter(job_request_id=int(job_id))
        return queryset.order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return QuotationCreateSerializer
        return QuotationSerializer

    def create(self, request, *args, **kwargs):
        _require_role(request.user, 'worker')
        return super().create(request, *args, **kwargs)

    @transaction.atomic
    def perform_create(self, serializer):
        user = self.request.user
        _require_role(user, 'worker')
        worker, _ = WorkerProfile.objects.get_or_create(user=user)
        job = serializer.validated_data['job_request']
        job = JobRequest.objects.select_for_update().get(pk=job.pk)
        if job.status not in (JobRequest.Status.OPEN, JobRequest.Status.IN_REVIEW):
            raise ValidationError({'job_request_id': 'This job is no longer accepting quotations.'})
        if job.customer_id == user.id:
            raise ValidationError({'job_request_id': 'You cannot quote on your own job.'})
        if Quotation.objects.filter(job_request=job, worker=worker).exists():
            raise ValidationError({'job_request_id': 'You have already quoted on this job.'})
        serializer.save(worker=worker, job_request=job)
        if job.status == JobRequest.Status.OPEN:
            job.status = JobRequest.Status.IN_REVIEW
            job.save(update_fields=['status', 'updated_at'])

    def _active_quotation(self, quotation, allow_pending_revision=False):
        if quotation.status != Quotation.Status.PENDING:
            raise ValidationError(f'A quotation in {quotation.status} status cannot be changed.')
        if quotation.valid_until and quotation.valid_until <= timezone.now():
            raise ValidationError('This quotation has expired.')
        if (
            not allow_pending_revision
            and quotation.revisions.filter(status=QuotationRevision.Status.PENDING).exists()
        ):
            raise ValidationError('Respond to the pending counter-proposal before continuing.')

    def _quotation_response(self, quotation):
        quotation.refresh_from_db()
        return Response(QuotationSerializer(quotation, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def counter(self, request, pk=None):
        quotation = self.get_object()
        if quotation.job_request.customer_id != request.user.id or not request.user.is_customer:
            raise PermissionDenied('Only the customer who posted this job can propose a counter-offer.')
        quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
        self._active_quotation(quotation)
        serializer = QuotationProposalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        QuotationRevision.objects.create(
            quotation=quotation,
            proposed_by=request.user,
            amount=serializer.validated_data['amount'],
            message=serializer.validated_data.get('message', ''),
            estimated_days=serializer.validated_data.get('estimated_days'),
        )
        return self._quotation_response(quotation)

    @action(detail=True, methods=['post'], url_path='respond-counter')
    @transaction.atomic
    def respond_counter(self, request, pk=None):
        quotation = self.get_object()
        if quotation.worker.user_id != request.user.id or not request.user.is_worker:
            raise PermissionDenied('Only the quoted worker can respond to a counter-offer.')
        quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
        self._active_quotation(quotation, allow_pending_revision=True)
        serializer = QuotationRevisionResponseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        revision = QuotationRevision.objects.select_for_update().filter(
            pk=serializer.validated_data['revision_id'],
            quotation=quotation,
            status=QuotationRevision.Status.PENDING,
        ).first()
        if not revision:
            raise ValidationError({'revision_id': 'No pending counter-offer matches this revision.'})
        if revision.proposed_by_id != quotation.job_request.customer_id:
            raise ValidationError({'revision_id': 'Only a customer counter-offer can be accepted here.'})
        now = timezone.now()
        revision.responded_by = request.user
        revision.responded_at = now
        revision.response_message = serializer.validated_data.get('response_message', '')
        if serializer.validated_data['decision'] == 'accept':
            revision.status = QuotationRevision.Status.ACCEPTED
            quotation.amount = revision.amount
            quotation.message = revision.message
            quotation.estimated_days = revision.estimated_days
            quotation.save(update_fields=['amount', 'message', 'estimated_days', 'updated_at'])
        else:
            revision.status = QuotationRevision.Status.REJECTED
        revision.save(update_fields=[
            'status', 'responded_by', 'responded_at', 'response_message',
        ])
        return self._quotation_response(quotation)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def revise(self, request, pk=None):
        quotation = self.get_object()
        if quotation.worker.user_id != request.user.id or not request.user.is_worker:
            raise PermissionDenied('Only the quoted worker can revise this quotation.')
        quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
        self._active_quotation(quotation)
        serializer = QuotationProposalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        now = timezone.now()
        values = serializer.validated_data
        QuotationRevision.objects.create(
            quotation=quotation,
            proposed_by=request.user,
            amount=values['amount'],
            message=values.get('message', ''),
            estimated_days=values.get('estimated_days'),
            status=QuotationRevision.Status.REVISED,
            responded_by=request.user,
            responded_at=now,
        )
        quotation.amount = values['amount']
        quotation.message = values.get('message', '')
        quotation.estimated_days = values.get('estimated_days')
        quotation.save(update_fields=['amount', 'message', 'estimated_days', 'updated_at'])
        return self._quotation_response(quotation)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def accept(self, request, pk=None):
        quotation = self.get_object()
        _require_role(request.user, 'customer')
        if quotation.job_request.customer_id != request.user.id:
            raise PermissionDenied('Only the customer who posted this job can accept a quotation.')

        job = JobRequest.objects.select_for_update().get(pk=quotation.job_request_id)
        quotation = Quotation.objects.select_for_update().select_related(
            'worker', 'worker__user', 'job_request__category', 'job_request__service',
        ).get(pk=quotation.pk)
        self._active_quotation(quotation)
        if job.status not in (JobRequest.Status.OPEN, JobRequest.Status.IN_REVIEW):
            raise ValidationError('This job request is no longer available for acceptance.')

        accepted_at = timezone.now()
        quotation.status = Quotation.Status.ACCEPTED
        quotation.accepted_at = accepted_at
        quotation.save(update_fields=['status', 'accepted_at', 'updated_at'])
        job.status = JobRequest.Status.AWARDED
        job.save(update_fields=['status', 'updated_at'])
        job.quotations.exclude(pk=quotation.pk).filter(status=Quotation.Status.PENDING).update(
            status=Quotation.Status.DECLINED
        )
        scope_snapshot = {
            'title': job.title,
            'description': job.description,
            'category': job.category.name,
            'service': job.service.name if job.service_id else None,
            'preferred_date': job.preferred_date.isoformat() if job.preferred_date else None,
            'service_location': {
                'address_line1': job.address.address_line1,
                'address_line2': job.address.address_line2,
                'locality': job.address.locality,
                'city': job.address.city,
                'state': job.address.state,
                'pincode': job.address.pincode,
                'latitude': str(job.address.latitude) if job.address.latitude is not None else None,
                'longitude': str(job.address.longitude) if job.address.longitude is not None else None,
            } if job.address_id else None,
        }
        try:
            breakdown = WorkBreakdown.objects.select_for_update().get(job_request=job)
        except WorkBreakdown.DoesNotExist:
            breakdown = None
        if breakdown and breakdown.status == WorkBreakdown.Status.APPROVED:
            revision = breakdown.revisions.filter(
                revision_number=breakdown.approved_revision,
                is_approved=True,
            ).first()
            if revision is None:
                raise ValidationError('The approved work breakdown revision could not be loaded.')
            scope_snapshot['work_breakdown'] = {
                'revision': revision.revision_number,
                'tasks': revision.snapshot,
            }

        agreement = WorkAgreement.objects.create(
            job_request=job,
            quotation=quotation,
            customer=request.user,
            worker=quotation.worker,
            scope_snapshot=scope_snapshot,
            terms_snapshot={
                'amount': str(quotation.amount),
                'currency': 'INR',
                'message': quotation.message,
                'estimated_days': quotation.estimated_days,
                'valid_until': quotation.valid_until.isoformat() if quotation.valid_until else None,
            },
            accepted_at=accepted_at,
        )
        create_project_for_agreement(agreement)
        return Response(
            WorkAgreementSerializer(agreement, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['get'])
    def agreement(self, request, pk=None):
        quotation = self.get_object()
        if not (request.user.is_customer or request.user.is_worker):
            raise PermissionDenied('A customer or worker account is required.')
        try:
            agreement = quotation.work_agreement
        except WorkAgreement.DoesNotExist:
            raise ValidationError('No accepted work agreement exists for this quotation.')
        return Response(WorkAgreementSerializer(agreement, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def decline(self, request, pk=None):
        _require_role(request.user, 'customer')
        quotation = self.get_object()
        if quotation.job_request.customer_id != request.user.id:
            raise PermissionDenied('Only the job owner can decline this quotation.')
        quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
        self._active_quotation(quotation, allow_pending_revision=True)
        quotation.status = Quotation.Status.DECLINED
        quotation.save(update_fields=['status', 'updated_at'])
        now = timezone.now()
        quotation.revisions.filter(status=QuotationRevision.Status.PENDING).update(
            status=QuotationRevision.Status.REJECTED,
            responded_by=request.user,
            responded_at=now,
            response_message='Quotation declined by customer.',
        )
        job = JobRequest.objects.select_for_update().get(pk=quotation.job_request_id)
        _refresh_job_status(job)
        return self._quotation_response(quotation)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def withdraw(self, request, pk=None):
        quotation = self.get_object()
        if quotation.worker.user_id != request.user.id or not request.user.is_worker:
            raise PermissionDenied('Only the worker who submitted this quotation can withdraw it.')
        quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
        self._active_quotation(quotation, allow_pending_revision=True)
        quotation.status = Quotation.Status.WITHDRAWN
        quotation.save(update_fields=['status', 'updated_at'])
        now = timezone.now()
        quotation.revisions.filter(status=QuotationRevision.Status.PENDING).update(
            status=QuotationRevision.Status.REJECTED,
            responded_by=request.user,
            responded_at=now,
            response_message='Quotation withdrawn by worker.',
        )
        job = JobRequest.objects.select_for_update().get(pk=quotation.job_request_id)
        _refresh_job_status(job)
        return self._quotation_response(quotation)
