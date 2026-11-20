from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image
from rest_framework.test import APIClient

from categories.models import ServiceCategory
from profiles.models import (
    Availability,
    CustomerProfile,
    Portfolio,
    WorkerProfile,
    WorkerService,
    WorkerServiceArea,
)
from services.models import Service

User = get_user_model()


class UserProfileAPITestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='profile@example.com',
            phone='9999999999',
            full_name='Test Customer',
            password='SecurePass123!',
            is_customer=True,
            is_worker=True,
        )
        self.worker, _ = WorkerProfile.objects.get_or_create(user=self.user)
        CustomerProfile.objects.get_or_create(user=self.user)
        self.client = APIClient()

    def test_customer_and_worker_profile_endpoints(self):
        self.client.force_authenticate(self.user)

        customer_response = self.client.get('/api/profiles/me/')
        self.assertEqual(customer_response.status_code, 200)
        self.assertEqual(customer_response.data['user']['full_name'], 'Test Customer')

        worker_list = self.client.get('/api/profiles/workers/')
        self.assertEqual(worker_list.status_code, 200)
        self.assertGreater(worker_list.data['count'], 0)

        worker_me = self.client.get('/api/profiles/workers/me/')
        self.assertEqual(worker_me.status_code, 200)

        patched = self.client.patch(
            '/api/profiles/workers/me/',
            {'bio': 'Trusted electrician for homes and shops', 'experience_years': 4},
            format='json',
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.data['bio'], 'Trusted electrician for homes and shops')

    def test_worker_can_manage_only_own_services_and_service_areas(self):
        category = ServiceCategory.objects.create(name='Electrical', slug='electrical')
        service = Service.objects.create(category=category, name='Wiring', slug='wiring')
        self.client.force_authenticate(self.user)

        service_response = self.client.post(
            '/api/profiles/workers/me/services/',
            {'category': category.id, 'service': service.id, 'price': '350.00', 'is_primary': True},
            format='json',
        )
        self.assertEqual(service_response.status_code, 201)
        self.assertEqual(WorkerService.objects.get().worker, self.worker)

        area_response = self.client.post(
            '/api/profiles/workers/me/service-areas/',
            {
                'locality': 'Kukatpally',
                'city': 'Hyderabad',
                'state': 'Telangana',
                'pincode': '500072',
                'latitude': '17.493300',
                'longitude': '78.399600',
                'radius_km': 5,
            },
            format='json',
        )
        self.assertEqual(area_response.status_code, 201)
        self.assertEqual(WorkerServiceArea.objects.get().worker, self.worker)
        area_id = area_response.data['id']
        updated_area = self.client.patch(
            f'/api/profiles/workers/me/service-areas/{area_id}/',
            {'radius_km': 10},
            format='json',
        )
        self.assertEqual(updated_area.status_code, 200, updated_area.data)
        self.assertEqual(updated_area.data['radius_km'], 10)

        invalid_area = self.client.post(
            '/api/profiles/workers/me/service-areas/',
            {'locality': 'Invalid', 'latitude': '91', 'longitude': '78', 'radius_km': 5},
            format='json',
        )
        self.assertEqual(invalid_area.status_code, 400)

        other_worker = User.objects.create_user(
            email='other-worker@example.com',
            phone='9999999998',
            full_name='Other Worker',
            password='SecurePass123!',
            is_customer=False,
            is_worker=True,
        )
        self.client.force_authenticate(other_worker)
        self.assertEqual(
            self.client.get('/api/profiles/workers/me/services/').data['results'],
            [],
        )
        self.assertEqual(
            self.client.delete(f"/api/profiles/workers/me/services/{service_response.data['id']}/").status_code,
            404,
        )
        self.client.force_authenticate(self.user)
        self.assertEqual(
            self.client.delete(f'/api/profiles/workers/me/services/{service_response.data["id"]}/').status_code,
            204,
        )
        self.assertEqual(
            self.client.delete(f'/api/profiles/workers/me/service-areas/{area_id}/').status_code,
            204,
        )

    def test_worker_can_manage_valid_non_overlapping_availability(self):
        self.client.force_authenticate(self.user)
        first_slot = self.client.post(
            '/api/profiles/workers/me/availability/',
            {'day_of_week': 0, 'start_time': '09:00', 'end_time': '12:00', 'is_available': True},
            format='json',
        )
        self.assertEqual(first_slot.status_code, 201, first_slot.data)
        self.assertEqual(first_slot.data['day_name'], 'Monday')
        self.assertEqual(Availability.objects.get().worker, self.worker)

        invalid_order = self.client.post(
            '/api/profiles/workers/me/availability/',
            {'day_of_week': 0, 'start_time': '13:00', 'end_time': '12:00'},
            format='json',
        )
        self.assertEqual(invalid_order.status_code, 400)

        overlapping = self.client.post(
            '/api/profiles/workers/me/availability/',
            {'day_of_week': 0, 'start_time': '11:00', 'end_time': '13:00'},
            format='json',
        )
        self.assertEqual(overlapping.status_code, 400)

        self.assertEqual(
            self.client.patch(
                f"/api/profiles/workers/me/availability/{first_slot.data['id']}/",
                {'end_time': '13:00'},
                format='json',
            ).status_code,
            200,
        )

        other_worker = User.objects.create_user(
            email='availability-owner@example.com',
            phone='9999999997',
            full_name='Another Worker',
            password='SecurePass123!',
            is_customer=False,
            is_worker=True,
        )
        self.client.force_authenticate(other_worker)
        self.assertEqual(self.client.get('/api/profiles/workers/me/availability/').data['results'], [])
        self.assertEqual(
            self.client.delete(
                f"/api/profiles/workers/me/availability/{first_slot.data['id']}/"
            ).status_code,
            404,
        )

    def test_worker_can_manage_only_own_portfolio_images(self):
        image_buffer = BytesIO()
        Image.new('RGB', (2, 2), color='blue').save(image_buffer, format='PNG')
        self.client.force_authenticate(self.user)
        oversized_image = SimpleUploadedFile(
            'large.png',
            image_buffer.getvalue() + b'\0' * (10 * 1024 * 1024),
            content_type='image/png',
        )
        oversized_response = self.client.post(
            '/api/profiles/workers/me/portfolio/',
            {'title': 'Oversized image', 'image': oversized_image},
            format='multipart',
        )
        self.assertEqual(oversized_response.status_code, 400)

        image = SimpleUploadedFile('work.png', image_buffer.getvalue(), content_type='image/png')
        response = self.client.post(
            '/api/profiles/workers/me/portfolio/',
            {'title': 'Kitchen wiring', 'description': 'Completed a home project.', 'image': image},
            format='multipart',
        )
        self.assertEqual(response.status_code, 201, response.data)
        portfolio = Portfolio.objects.get()
        self.addCleanup(portfolio.image.delete, save=False)
        self.assertEqual(portfolio.worker, self.worker)

        other_worker = User.objects.create_user(
            email='portfolio-owner@example.com',
            phone='9999999996',
            full_name='Another Worker',
            password='SecurePass123!',
            is_customer=False,
            is_worker=True,
        )
        self.client.force_authenticate(other_worker)
        self.assertEqual(self.client.get('/api/profiles/workers/me/portfolio/').data['results'], [])
        self.assertEqual(
            self.client.patch(
                f'/api/profiles/workers/me/portfolio/{portfolio.id}/',
                {'title': 'Changed by another worker'},
                format='json',
            ).status_code,
            404,
        )

        self.client.force_authenticate(self.user)
        updated = self.client.patch(
            f'/api/profiles/workers/me/portfolio/{portfolio.id}/',
            {'title': 'Updated project title'},
            format='multipart',
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data['title'], 'Updated project title')
        self.assertEqual(
            self.client.delete(f'/api/profiles/workers/me/portfolio/{portfolio.id}/').status_code,
            204,
        )
