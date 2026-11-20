from datetime import date
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from bookings.models import Booking, BookingStatusHistory
from categories.models import ServiceCategory
from profiles.models import Address, WorkerProfile, WorkerService
from services.models import Service

User = get_user_model()


class BookingAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create_user(
            email='cust@test.invalid', phone='9849099001', password='Password123!', full_name='Test Customer', is_customer=True
        )
        self.worker_user = User.objects.create_user(
            email='work@test.invalid', phone='9849099002', password='Password123!', full_name='Test Worker', is_worker=True, is_customer=False
        )
        self.worker = WorkerProfile.objects.create(user=self.worker_user, starting_price=300)
        self.category = ServiceCategory.objects.create(name='Carpentry', slug='carpentry')
        self.service = Service.objects.create(category=self.category, name='Wood repair', slug='wood-repair')
        self.address = Address.objects.create(
            user=self.customer, label='Home', address_line1='Flat 101, Test Road', locality='Kukatpally',
            city='Hyderabad', state='Telangana', pincode='500072', is_default=True
        )

    def test_customer_can_create_booking(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.post('/api/bookings/', {
            'worker_id': self.worker.id,
            'service_id': self.service.id,
            'address_id': self.address.id,
            'scheduled_date': str(date.today()),
            'customer_notes': 'Please repair door hinge',
            'estimated_amount': '300.00',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Booking.objects.count(), 1)
        booking = Booking.objects.first()
        self.assertEqual(booking.status, Booking.Status.PENDING)
        self.assertEqual(booking.customer, self.customer)
        self.assertEqual(booking.worker, self.worker)
        self.assertEqual(BookingStatusHistory.objects.filter(booking=booking).count(), 1)

    def test_worker_can_confirm_and_complete_booking(self):
        booking = Booking.objects.create(
            customer=self.customer, worker=self.worker, service=self.service, address=self.address,
            scheduled_date=date.today(), status=Booking.Status.PENDING, estimated_amount=300
        )
        self.client.force_authenticate(user=self.worker_user)

        # Confirm
        response = self.client.post(f'/api/bookings/{booking.id}/status/', {'status': 'confirmed'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)

        # Complete
        response = self.client.post(f'/api/bookings/{booking.id}/status/', {
            'status': 'completed', 'final_amount': '350.00', 'worker_notes': 'Job done cleanly'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.COMPLETED)
        self.assertEqual(booking.final_amount, 350)
        self.assertIsNotNone(booking.completed_at)

        self.worker.refresh_from_db()
        self.assertEqual(self.worker.total_bookings, 1)

    def test_customer_can_cancel_pending_booking(self):
        booking = Booking.objects.create(
            customer=self.customer, worker=self.worker, service=self.service, address=self.address,
            scheduled_date=date.today(), status=Booking.Status.PENDING
        )
        self.client.force_authenticate(user=self.customer)
        response = self.client.post(f'/api/bookings/{booking.id}/status/', {
            'status': 'cancelled', 'cancellation_reason': 'Changed my plans'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)
        self.assertIsNotNone(booking.cancelled_at)
