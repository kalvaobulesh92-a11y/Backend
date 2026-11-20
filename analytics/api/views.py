from django.contrib.auth import get_user_model
from django.db.models import Count
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdmin
from bookings.models import Booking
from categories.models import ServiceCategory
from enquiries.models import Enquiry
from profiles.models import WorkerProfile
from reviews.models import Review
from services.models import Service

User = get_user_model()


class AnalyticsSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def get(self, request):
        total_users = User.objects.count()
        total_customers = User.objects.filter(is_customer=True).count()
        total_workers = WorkerProfile.objects.count()

        status_counts = dict(
            Booking.objects.values('status').annotate(count=Count('id')).values_list('status', 'count')
        )
        total_bookings = sum(status_counts.values())

        recent_bookings = Booking.objects.select_related(
            'customer', 'worker__user', 'service'
        ).order_by('-created_at')[:5]

        recent_bookings_data = [
            {
                'id': b.id,
                'customer_name': b.customer.full_name,
                'customer_phone': b.customer.phone,
                'worker_name': b.worker.user.full_name,
                'worker_phone': b.worker.user.phone,
                'service_name': b.service.name if b.service else 'General service',
                'status': b.status,
                'scheduled_date': b.scheduled_date,
                'estimated_amount': str(b.estimated_amount) if b.estimated_amount else None,
                'created_at': b.created_at,
            }
            for b in recent_bookings
        ]

        recent_users = User.objects.order_by('-date_joined')[:5]
        recent_users_data = [
            {
                'id': u.id,
                'full_name': u.full_name,
                'email': u.email,
                'phone': u.phone,
                'is_customer': u.is_customer,
                'is_worker': u.is_worker,
                'is_admin': u.is_admin,
                'date_joined': u.date_joined,
            }
            for u in recent_users
        ]

        return Response({
            'overview': {
                'total_users': total_users,
                'total_customers': total_customers,
                'total_workers': total_workers,
                'total_bookings': total_bookings,
                'total_enquiries': Enquiry.objects.count(),
                'total_reviews': Review.objects.count(),
                'total_categories': ServiceCategory.objects.count(),
                'total_services': Service.objects.count(),
            },
            'bookings_by_status': {
                'pending': status_counts.get('pending', 0),
                'confirmed': status_counts.get('confirmed', 0),
                'in_progress': status_counts.get('in_progress', 0),
                'completed': status_counts.get('completed', 0),
                'cancelled': status_counts.get('cancelled', 0),
                'disputed': status_counts.get('disputed', 0),
            },
            'recent_bookings': recent_bookings_data,
            'recent_users': recent_users_data,
        }, status=status.HTTP_200_OK)
