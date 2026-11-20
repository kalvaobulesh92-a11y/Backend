from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from categories.models import ServiceCategory
from profiles.models import WorkerProfile, WorkerService, WorkerServiceArea
from services.models import Service

User = get_user_model()


class NearbyWorkerAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.category = ServiceCategory.objects.create(
            name='Electrical',
            slug='electrical',
            is_active=True,
        )
        self.service = Service.objects.create(
            category=self.category,
            name='Electrician',
            slug='electrician',
            is_active=True,
        )
        self.worker = self.create_worker(
            'worker@example.com',
            'Nearby Electrician',
            latitude=17.485,
            longitude=78.395,
            area_radius=5,
        )
        self.create_worker(
            'closer-worker@example.com',
            'Another Electrician',
            latitude=17.493,
            longitude=78.40,
            area_radius=5,
        )
        self.create_worker(
            'far-worker@example.com',
            'Far Electrician',
            latitude=17.60,
            longitude=78.395,
            area_radius=20,
        )

    def create_worker(self, email, name, latitude, longitude, area_radius):
        user = User.objects.create_user(
            email=email,
            phone=f'9{User.objects.count():09d}',
            full_name=name,
            password='SecurePass123!',
            is_customer=True,
            is_worker=True,
        )
        profile = WorkerProfile.objects.create(
            user=user,
            verification_status='verified',
            average_rating=4.5,
        )
        WorkerService.objects.create(
            worker=profile,
            category=self.category,
            service=self.service,
            is_primary=True,
        )
        WorkerServiceArea.objects.create(
            worker=profile,
            locality='Kukatpally',
            latitude=latitude,
            longitude=longitude,
            radius_km=area_radius,
        )
        return profile

    def test_nearby_workers_are_distance_sorted_and_do_not_expose_email(self):
        response = self.client.get(
            '/api/locations/nearby-workers/',
            {
                'latitude': '17.484',
                'longitude': '78.392',
                'radius_km': '5',
                'category': 'electrical',
                'service': 'electrician',
                'verified': 'true',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 2)
        result = response.data['results'][0]
        self.assertEqual(result['worker']['id'], self.worker.id)
        self.assertGreater(result['distance_km'], 0)
        self.assertLessEqual(result['distance_km'], response.data['results'][1]['distance_km'])
        self.assertNotIn('email', result['worker']['user'])
        self.assertNotIn('addresses', result['worker'])

    def test_invalid_radius_and_coordinates_are_rejected(self):
        invalid_radius = self.client.get(
            '/api/locations/nearby-workers/',
            {'latitude': '17.484', 'longitude': '78.392', 'radius_km': '2'},
        )
        invalid_coordinates = self.client.get(
            '/api/locations/nearby-workers/',
            {'latitude': '91', 'longitude': '78.392', 'radius_km': '5'},
        )
        non_finite_coordinates = self.client.get(
            '/api/locations/nearby-workers/',
            {'latitude': 'NaN', 'longitude': '78.392', 'radius_km': '5'},
        )

        self.assertEqual(invalid_radius.status_code, 400)
        self.assertEqual(invalid_coordinates.status_code, 400)
        self.assertEqual(non_finite_coordinates.status_code, 400)

    def test_service_radius_limits_results_even_inside_requested_radius(self):
        WorkerServiceArea.objects.update(radius_km=1)
        response = self.client.get(
            '/api/locations/nearby-workers/',
            {'latitude': '17.52', 'longitude': '78.40', 'radius_km': '5'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'], [])
