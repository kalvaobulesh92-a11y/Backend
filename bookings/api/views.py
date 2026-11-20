from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import IsCustomerOrWorker
from bookings.models import Booking, BookingStatusHistory
from .serializers import (
    BookingCreateSerializer,
    BookingSerializer,
    BookingStatusUpdateSerializer,
)


class BookingViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrWorker]
    serializer_class = BookingSerializer

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Booking.objects.none()

        qs = Booking.objects.select_related(
            'customer', 'worker', 'worker__user', 'service', 'service__category', 'address'
        ).prefetch_related('status_history__changed_by')

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
            # Dual role: default to customer unless worker specified
            qs = qs.filter(Q(customer=user) | Q(worker__user=user))

        booking_status = self.request.query_params.get('status')
        if booking_status:
            qs = qs.filter(status=booking_status)

        return qs.order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return BookingCreateSerializer
        if self.action == 'update_status':
            return BookingStatusUpdateSerializer
        return BookingSerializer

    @transaction.atomic
    def perform_create(self, serializer):
        user = self.request.user
        if not user.is_customer:
            raise PermissionDenied('Customer access is required to request a booking.')

        booking = serializer.save(
            customer=user,
            status=Booking.Status.PENDING,
        )
        BookingStatusHistory.objects.create(
            booking=booking,
            changed_by=user,
            previous_status='',
            new_status=Booking.Status.PENDING,
            note=booking.customer_notes or 'Booking requested by customer.',
        )

    @action(detail=True, methods=['patch', 'post'], url_path='status')
    @transaction.atomic
    def update_status(self, request, pk=None):
        booking = self.get_object()
        serializer = BookingStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        new_status = serializer.validated_data['status']
        prev_status = booking.status
        worker_notes = serializer.validated_data.get('worker_notes', '')
        cancellation_reason = serializer.validated_data.get('cancellation_reason', '')
        final_amount = serializer.validated_data.get('final_amount')

        is_worker = booking.worker.user_id == user.id
        is_customer = booking.customer_id == user.id

        if not (is_worker or is_customer or user.is_staff):
            raise PermissionDenied('You are not authorized to update this booking.')

        # Status transition business rules
        if new_status == Booking.Status.CANCELLED:
            if prev_status in (Booking.Status.COMPLETED, Booking.Status.CANCELLED):
                raise ValidationError(f'Cannot cancel a booking that is already {prev_status}.')
            booking.status = Booking.Status.CANCELLED
            booking.cancelled_at = timezone.now()
            booking.cancellation_reason = cancellation_reason or f'Cancelled by {"worker" if is_worker else "customer"}.'
            note = booking.cancellation_reason

        elif is_worker:
            if new_status == Booking.Status.CONFIRMED:
                if prev_status != Booking.Status.PENDING:
                    raise ValidationError('Only pending bookings can be confirmed.')
                booking.status = Booking.Status.CONFIRMED
                note = 'Booking confirmed by professional.'

            elif new_status == Booking.Status.IN_PROGRESS:
                if prev_status not in (Booking.Status.CONFIRMED, Booking.Status.PENDING):
                    raise ValidationError('Booking must be confirmed before starting work.')
                booking.status = Booking.Status.IN_PROGRESS
                note = 'Service in progress.'

            elif new_status == Booking.Status.COMPLETED:
                if prev_status not in (Booking.Status.CONFIRMED, Booking.Status.IN_PROGRESS):
                    raise ValidationError('Cannot mark as completed from current status.')
                booking.status = Booking.Status.COMPLETED
                booking.completed_at = timezone.now()
                if final_amount is not None:
                    booking.final_amount = final_amount
                elif booking.estimated_amount is not None:
                    booking.final_amount = booking.estimated_amount
                if worker_notes:
                    booking.worker_notes = worker_notes
                note = worker_notes or 'Work marked as completed by professional.'

                # Update worker stats
                type(booking.worker).objects.filter(pk=booking.worker_id).update(
                    total_bookings=F('total_bookings') + 1
                )
            else:
                raise ValidationError(f'Invalid status change to {new_status}.')

        else:
            # Customer trying non-cancel change
            raise PermissionDenied('Only the service professional can update job progress.')

        booking.save()

        BookingStatusHistory.objects.create(
            booking=booking,
            changed_by=user,
            previous_status=prev_status,
            new_status=new_status,
            note=note,
        )

        response_serializer = BookingSerializer(booking)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='approve-completion')
    @transaction.atomic
    def approve_completion(self, request, pk=None):
        booking = self.get_object()
        if booking.customer_id != request.user.id or not request.user.is_customer:
            raise PermissionDenied('Only the booking customer can approve completed work.')

        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if booking.status != Booking.Status.COMPLETED:
            raise ValidationError('Only completed bookings can be approved.')
        if booking.customer_approved_completed_at:
            return Response(BookingSerializer(booking).data)

        now = timezone.now()
        booking.customer_approved_completed_at = now
        booking.save(update_fields=['customer_approved_completed_at', 'updated_at'])
        BookingStatusHistory.objects.create(
            booking=booking,
            changed_by=request.user,
            previous_status=Booking.Status.COMPLETED,
            new_status=Booking.Status.COMPLETED,
            note='Completed work approved by the customer.',
        )
        return Response(BookingSerializer(booking).data)
