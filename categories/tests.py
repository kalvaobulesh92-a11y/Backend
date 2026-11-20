import tempfile

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.management import CommandError
from django.core.management import call_command
from django.test import TestCase
from django.test import override_settings
from rest_framework.test import APIClient
from PIL import Image

from bookings.models import Booking, BookingStatusHistory
from categories.models import ServiceCategory
from complaints.models import Complaint
from enquiries.models import Enquiry
from favourites.models import Favourite
from messaging.models import Conversation, Message
from notifications.models import Notification
from payments.models import Payment
from profiles.models import (
    Address,
    Availability,
    CustomerProfile,
    Portfolio,
    WorkerProfile,
    WorkerService,
    WorkerServiceArea,
    WorkerSkill,
)
from quotations.models import JobRequest, Quotation
from reviews.models import Review
from services.models import Service
from verification.models import VerificationDocument


User = get_user_model()
SEEDED_MODELS = (
    User,
    ServiceCategory,
    Service,
    CustomerProfile,
    Address,
    WorkerProfile,
    WorkerSkill,
    WorkerService,
    WorkerServiceArea,
    Availability,
    Portfolio,
    Enquiry,
    Booking,
    BookingStatusHistory,
    JobRequest,
    Quotation,
    Conversation,
    Message,
    Notification,
    Review,
    VerificationDocument,
    Complaint,
    Favourite,
    Payment,
)


class CategoryAndServiceAPITestCase(TestCase):
    def setUp(self):
        self.category = ServiceCategory.objects.create(
            name='Electrical', slug='electrical', description='Electrical services', is_active=True
        )
        self.service = Service.objects.create(
            category=self.category,
            name='Electrician',
            slug='electrician',
            description='Home wiring and repairs',
            is_active=True,
        )
        self.client = APIClient()

    def test_category_list_and_service_filter_endpoints(self):
        response = self.client.get('/api/categories/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(item['slug'] == 'electrical' for item in response.data['results']))

        filtered = self.client.get(f'/api/services/?category={self.category.id}')
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.data['results'][0]['name'], 'Electrician')


@override_settings(DEBUG=True)
class HyderabadSeedCommandTestCase(TestCase):
    @override_settings(DEBUG=False)
    def test_seed_refuses_to_run_outside_debug_mode(self):
        with self.assertRaises(CommandError):
            call_command('seed_hyderabad', verbosity=0)

    def test_seed_is_idempotent_and_creates_unverified_discoverable_workers(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                call_command('seed_hyderabad', verbosity=0)

                self.assertEqual(ServiceCategory.objects.count(), 6)
                self.assertEqual(Service.objects.count(), 12)
                self.assertEqual(User.objects.filter(is_worker=True).count(), 5)
                self.assertEqual(WorkerProfile.objects.filter(verification_status='unverified').count(), 5)
                self.assertEqual(WorkerServiceArea.objects.count(), 5)
                self.assertTrue(all(model.objects.exists() for model in SEEDED_MODELS))
                with default_storage.open(Portfolio.objects.first().image.name, 'rb') as image_file:
                    Image.open(image_file).verify()
                demo_workers = User.objects.filter(is_worker=True, email__endswith='@example.invalid')
                self.assertEqual(demo_workers.count(), 5)
                for worker in demo_workers:
                    self.assertTrue(worker.profile_picture)
                    with default_storage.open(worker.profile_picture.name, 'rb') as image_file:
                        Image.open(image_file).verify()

                electrician = User.objects.get(email='demo.electrician-kukatpally@example.invalid')
                self.assertFalse(electrician.has_usable_password())
                self.assertFalse(electrician.is_customer)
                self.assertTrue(electrician.is_worker)

                completed_booking = Booking.objects.get(status=Booking.Status.COMPLETED)
                self.assertTrue(Review.objects.filter(booking=completed_booking).exists())
                self.assertEqual(
                    Payment.objects.get(booking=completed_booking).status,
                    Payment.Status.CREATED,
                )
                self.assertTrue(VerificationDocument.objects.filter(status='pending').exists())

                counts_after_first_run = [model.objects.count() for model in SEEDED_MODELS]
                call_command('seed_hyderabad', verbosity=0)
                self.assertEqual(
                    [model.objects.count() for model in SEEDED_MODELS],
                    counts_after_first_run,
                )

                response = APIClient().get(
                    '/api/locations/nearby-workers/',
                    {
                        'latitude': '17.484',
                        'longitude': '78.392',
                        'radius_km': '5',
                        'category': 'electrical',
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.data['results'][0]['worker']['user']['full_name'],
                    'Demo Electrician - Kukatpally',
                )
