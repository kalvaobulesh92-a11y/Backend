from django.db.models import Q
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import IsCustomerOrWorker
from enquiries.models import Enquiry
from .serializers import (
    EnquiryCreateSerializer,
    EnquirySerializer,
    EnquiryStatusUpdateSerializer,
)


class EnquiryViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrWorker]
    serializer_class = EnquirySerializer

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Enquiry.objects.none()

        qs = Enquiry.objects.select_related(
            'customer', 'worker', 'worker__user', 'category', 'service', 'address'
        )

        role = self.request.query_params.get('role')
        if user.is_staff or user.is_superuser:
            if role == 'worker':
                qs = qs.filter(worker__user=user)
            elif role == 'customer':
                qs = qs.filter(customer=user)
        elif role == 'worker' and user.is_worker:
            qs = qs.filter(worker__user=user)
        elif role == 'customer' and user.is_customer:
            qs = qs.filter(customer=user)
        elif user.is_worker and not user.is_customer:
            qs = qs.filter(worker__user=user)
        elif user.is_customer and not user.is_worker:
            qs = qs.filter(customer=user)
        else:
            qs = qs.filter(Q(customer=user) | Q(worker__user=user))

        enquiry_status = self.request.query_params.get('status')
        if enquiry_status:
            qs = qs.filter(status=enquiry_status)

        return qs.order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return EnquiryCreateSerializer
        if self.action == 'update_status':
            return EnquiryStatusUpdateSerializer
        return EnquirySerializer

    def perform_create(self, serializer):
        user = self.request.user
        if not user.is_customer:
            raise PermissionDenied('Customer access is required to send an enquiry.')
        serializer.save(customer=user, status=Enquiry.Status.PENDING)

    @action(detail=True, methods=['patch', 'post'], url_path='status')
    def update_status(self, request, pk=None):
        enquiry = self.get_object()
        serializer = EnquiryStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        new_status = serializer.validated_data['status']
        is_worker = enquiry.worker.user_id == user.id
        is_customer = enquiry.customer_id == user.id

        if not (is_worker or is_customer or user.is_staff):
            raise PermissionDenied('Not authorized to update this enquiry.')

        if new_status == Enquiry.Status.CANCELLED and not is_customer:
            raise PermissionDenied('Only the customer can cancel the enquiry.')
        if new_status in (Enquiry.Status.ACCEPTED, Enquiry.Status.DECLINED) and not is_worker:
            raise PermissionDenied('Only the service professional can accept or decline.')

        enquiry.status = new_status
        enquiry.save(update_fields=['status', 'updated_at'])

        return Response(EnquirySerializer(enquiry).data, status=status.HTTP_200_OK)
