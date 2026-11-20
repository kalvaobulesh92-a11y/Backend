from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from categories.models import ServiceCategory
from profiles.api.serializers import UserSummarySerializer
from profiles.models import Address, WorkerProfile
from quotations.models import JobRequest, Quotation, QuotationRevision, WorkAgreement
from services.models import Service
from workbreakdowns.models import WorkBreakdown
from workbreakdowns.api.serializers import WorkBreakdownSerializer

User = get_user_model()


class JobRequestSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.full_name', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    service_name = serializers.CharField(source='service.name', read_only=True, default=None)
    work_breakdown = serializers.SerializerMethodField()
    work_breakdown_editable = serializers.SerializerMethodField()

    class Meta:
        model = JobRequest
        fields = (
            'id', 'customer_name', 'category_name', 'service_name', 'title', 'description',
            'budget_min', 'budget_max', 'preferred_date', 'status', 'work_breakdown',
            'work_breakdown_editable',
            'created_at', 'updated_at',
        )
        read_only_fields = fields

    def get_work_breakdown(self, job):
        try:
            breakdown = job.work_breakdown
        except WorkBreakdown.DoesNotExist:
            return None

        request = self.context.get('request')
        if request and request.user.pk == job.customer_id:
            return WorkBreakdownSerializer(breakdown, context=self.context).data
        if breakdown.status != WorkBreakdown.Status.APPROVED:
            return None
        revision = breakdown.revisions.filter(
            revision_number=breakdown.approved_revision,
            is_approved=True,
        ).first()
        if not revision:
            return None
        return {
            'status': breakdown.status,
            'approved_revision': revision.revision_number,
            'tasks': revision.snapshot,
        }

    def get_work_breakdown_editable(self, job):
        request = self.context.get('request')
        if not request or request.user.pk != job.customer_id:
            return False
        try:
            if job.work_breakdown.status != WorkBreakdown.Status.DRAFT:
                return False
        except WorkBreakdown.DoesNotExist:
            pass
        has_quotations = getattr(job, 'has_quotations', None)
        if has_quotations is None:
            has_quotations = job.quotations.exists()
        return job.status == JobRequest.Status.OPEN and not has_quotations


class JobRequestCreateSerializer(serializers.ModelSerializer):
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=ServiceCategory.objects.filter(is_active=True),
        source='category',
    )
    service_id = serializers.PrimaryKeyRelatedField(
        queryset=Service.objects.filter(is_active=True),
        source='service',
        required=False,
        allow_null=True,
    )
    address_id = serializers.PrimaryKeyRelatedField(
        queryset=Address.objects.all(),
        source='address',
        required=False,
        allow_null=True,
    )
    budget_min = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.00'),
        required=False,
        allow_null=True,
    )
    budget_max = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.00'),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = JobRequest
        fields = (
            'id', 'category_id', 'service_id', 'address_id', 'title', 'description',
            'budget_min', 'budget_max', 'preferred_date',
        )
        read_only_fields = ('id',)

    def validate(self, attrs):
        request = self.context.get('request')
        category = attrs['category']
        service = attrs.get('service')
        address = attrs.get('address')
        if service and service.category_id != category.id:
            raise serializers.ValidationError({
                'service_id': 'Choose a service from the selected category.'
            })
        if address and request and address.user_id != request.user.id:
            raise serializers.ValidationError({'address_id': 'Choose one of your saved addresses.'})
        minimum = attrs.get('budget_min')
        maximum = attrs.get('budget_max')
        if minimum is not None and maximum is not None and minimum > maximum:
            raise serializers.ValidationError({'budget_max': 'Maximum budget must be at least the minimum.'})
        preferred_date = attrs.get('preferred_date')
        if preferred_date and preferred_date < timezone.localdate():
            raise serializers.ValidationError({'preferred_date': 'Preferred date cannot be in the past.'})
        return attrs


class QuotationRevisionSerializer(serializers.ModelSerializer):
    proposed_by_name = serializers.CharField(source='proposed_by.full_name', read_only=True)
    responded_by_name = serializers.CharField(
        source='responded_by.full_name',
        read_only=True,
        default=None,
    )

    class Meta:
        model = QuotationRevision
        fields = (
            'id', 'proposed_by_name', 'amount', 'message', 'estimated_days', 'status',
            'response_message', 'responded_by_name', 'created_at', 'responded_at',
        )
        read_only_fields = fields


class QuotationSerializer(serializers.ModelSerializer):
    job = JobRequestSerializer(source='job_request', read_only=True)
    worker = UserSummarySerializer(source='worker.user', read_only=True)
    revisions = QuotationRevisionSerializer(many=True, read_only=True)
    agreement = serializers.SerializerMethodField()

    class Meta:
        model = Quotation
        fields = (
            'id', 'job_request', 'job', 'worker', 'amount', 'message', 'estimated_days',
            'status', 'valid_until', 'accepted_at', 'created_at', 'updated_at', 'revisions',
            'agreement',
        )
        read_only_fields = fields

    def get_agreement(self, obj):
        try:
            agreement = obj.work_agreement
        except WorkAgreement.DoesNotExist:
            return None
        return WorkAgreementSerializer(agreement, context=self.context).data


class QuotationCreateSerializer(serializers.ModelSerializer):
    job_request_id = serializers.PrimaryKeyRelatedField(
        queryset=JobRequest.objects.all(),
        source='job_request',
    )
    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.01'),
    )
    estimated_days = serializers.IntegerField(min_value=1, max_value=365, required=False, allow_null=True)
    valid_until = serializers.DateTimeField(required=False, allow_null=True)

    class Meta:
        model = Quotation
        fields = ('id', 'job_request_id', 'amount', 'message', 'estimated_days', 'valid_until')
        read_only_fields = ('id',)

    def validate(self, attrs):
        request = self.context.get('request')
        job = attrs['job_request']
        if request and job.customer_id == request.user.id:
            raise serializers.ValidationError({'job_request_id': 'You cannot quote on your own job.'})
        if job.status not in (JobRequest.Status.OPEN, JobRequest.Status.IN_REVIEW):
            raise serializers.ValidationError({'job_request_id': 'This job is no longer accepting quotations.'})
        if request and Quotation.objects.filter(job_request=job, worker__user=request.user).exists():
            raise serializers.ValidationError({'job_request_id': 'You have already quoted on this job.'})
        valid_until = attrs.get('valid_until')
        if valid_until and valid_until <= timezone.now():
            raise serializers.ValidationError({'valid_until': 'Quotation expiry must be in the future.'})
        return attrs


class QuotationProposalSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.01'),
    )
    message = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    estimated_days = serializers.IntegerField(min_value=1, max_value=365, required=False, allow_null=True)


class QuotationRevisionResponseSerializer(serializers.Serializer):
    revision_id = serializers.IntegerField(min_value=1)
    decision = serializers.ChoiceField(choices=('accept', 'reject'))
    response_message = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class WorkAgreementSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.full_name', read_only=True)
    worker = UserSummarySerializer(source='worker.user', read_only=True)
    quotation_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = WorkAgreement
        fields = (
            'id', 'job_request', 'quotation_id', 'customer_name', 'worker',
            'scope_snapshot', 'terms_snapshot', 'accepted_at', 'created_at',
        )
        read_only_fields = fields
