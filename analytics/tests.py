from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

User = get_user_model()


class AnalyticsAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            email='admin_stat@test.invalid', phone='9849099007', password='Password123!', full_name='Admin User'
        )
        self.regular_user = User.objects.create_user(
            email='regular@test.invalid', phone='9849099008', password='Password123!', full_name='Regular User'
        )

    def test_admin_can_access_analytics_summary(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/analytics/summary/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('overview', response.data)
        self.assertIn('bookings_by_status', response.data)
        self.assertIn('recent_bookings', response.data)
        self.assertIn('recent_users', response.data)

    def test_regular_user_forbidden_from_analytics(self):
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/analytics/summary/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
