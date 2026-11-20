from django.db import transaction
from django.db.models import Avg, Count, Q
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import IsCustomer, IsWorker
from reviews.models import Review
from .serializers import ReviewCreateSerializer, ReviewReplySerializer, ReviewSerializer


class ReviewViewSet(viewsets.ModelViewSet):
    serializer_class = ReviewSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [permissions.AllowAny()]
        if self.action == 'create':
            return [permissions.IsAuthenticated(), IsCustomer()]
        if self.action == 'reply':
            return [permissions.IsAuthenticated(), IsWorker()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        worker_id = self.request.query_params.get('worker')
        if worker_id:
            return Review.objects.filter(
                worker_id=worker_id, is_public=True
            ).select_related('customer', 'worker', 'worker__user').order_by('-created_at')

        user = self.request.user
        if not user.is_authenticated:
            return Review.objects.none()

        if user.is_staff or user.is_superuser:
            return Review.objects.all().select_related('customer', 'worker', 'worker__user').order_by('-created_at')

        return Review.objects.filter(
            Q(customer=user) | Q(worker__user=user)
        ).select_related('customer', 'worker', 'worker__user').order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return ReviewCreateSerializer
        if self.action == 'reply':
            return ReviewReplySerializer
        return ReviewSerializer

    @transaction.atomic
    def perform_create(self, serializer):
        booking = serializer.validated_data['booking']
        worker = booking.worker
        review = serializer.save(
            customer=self.request.user,
            worker=worker,
            is_public=True,
        )

        # Recalculate worker average rating and review count
        stats = Review.objects.filter(worker=worker, is_public=True).aggregate(
            avg_rating=Avg('rating'),
            total_reviews=Count('id')
        )
        worker.average_rating = round(stats['avg_rating'] or 0.0, 2)
        worker.total_reviews = stats['total_reviews'] or 0
        worker.save(update_fields=['average_rating', 'total_reviews', 'updated_at'])

    @action(detail=True, methods=['patch', 'post'], url_path='reply')
    def reply(self, request, pk=None):
        review = self.get_object()
        user = request.user
        if review.worker.user_id != user.id and not user.is_staff:
            raise PermissionDenied('Only the reviewed professional can reply.')

        serializer = ReviewReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        review.worker_reply = serializer.validated_data['worker_reply']
        review.worker_replied_at = timezone.now()
        review.save(update_fields=['worker_reply', 'worker_replied_at', 'updated_at'])

        return Response(ReviewSerializer(review).data, status=status.HTTP_200_OK)
