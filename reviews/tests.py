from datetime import date
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from bookings.models import Booking
from profiles.models import Address, WorkerProfile
from reviews.models import Review

User = get_user_model()


class ReviewAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create_user(
            email='rev_cust@test.invalid', phone='9849099005', password='Password123!', full_name='Review Customer', is_customer=True
        )
        self.worker_user = User.objects.create_user(
            email='rev_work@test.invalid', phone='9849099006', password='Password123!', full_name='Review Worker', is_worker=True, is_customer=False
        )
        self.worker = WorkerProfile.objects.create(user=self.worker_user)
        self.address = Address.objects.create(
            user=self.customer, label='Home', address_line1='Flat 202', locality='Madhapur', pincode='500081'
        )
        self.booking = Booking.objects.create(
            customer=self.customer, worker=self.worker, address=self.address,
            scheduled_date=date.today(), status=Booking.Status.COMPLETED
        )

    def test_customer_can_review_completed_booking_and_update_worker_rating(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.post('/api/reviews/', {
            'booking_id': self.booking.id,
            'rating': 5,
            'title': 'Outstanding work!',
            'comment': 'Arrived on time and solved the issue quickly.',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Review.objects.count(), 1)
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.total_reviews, 1)
        self.assertEqual(float(self.worker.average_rating), 5.0)

    def test_worker_can_reply_to_review(self):
        review = Review.objects.create(
            booking=self.booking, customer=self.customer, worker=self.worker,
            rating=5, title='Great!', comment='Superb'
        )
        self.client.force_authenticate(user=self.worker_user)
        response = self.client.post(f'/api/reviews/{review.id}/reply/', {
            'worker_reply': 'Thank you for your feedback!'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        review.refresh_from_db()
        self.assertEqual(review.worker_reply, 'Thank you for your feedback!')
        self.assertIsNotNone(review.worker_replied_at)
