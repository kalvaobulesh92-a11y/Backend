from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from categories.models import ServiceCategory
from profiles.models import WorkerProfile, WorkerService
from services.models import Service

User = get_user_model()


class PriceEstimateTests(TestCase):
    def setUp(self):
        self.category = ServiceCategory.objects.create(
            name='Pricing Plumbing',
            slug='pricing-plumbing',
        )
        self.service = Service.objects.create(
            category=self.category,
            name='Pricing Pipe Repair',
            slug='pricing-pipe-repair',
        )
        self.other_category = ServiceCategory.objects.create(
            name='Pricing Electrical',
            slug='pricing-electrical',
        )
        self.other_service = Service.objects.create(
            category=self.other_category,
            name='Pricing Wiring',
            slug='pricing-wiring',
        )
        self.client = APIClient()

    def add_listing(self, number, price, service=None, pricing_type='fixed', available=True):
        user = User.objects.create_user(
            email=f'pricing-worker-{number}@example.com',
            phone=f'9300000{number:03d}',
            full_name=f'Pricing Worker {number}',
            password='SecurePass123!',
            is_customer=False,
            is_worker=True,
        )
        profile = WorkerProfile.objects.create(
            user=user,
            pricing_type=pricing_type,
            is_available=available,
        )
        return WorkerService.objects.create(
            worker=profile,
            category=self.category,
            service=service,
            price=price,
        )

    def estimate(self, category=None, service=None):
        category = category or self.category
        params = {'category_id': category.id}
        if service:
            params['service_id'] = service.id
        return self.client.get('/api/pricing/estimate/', params)

    def test_sparse_catalog_returns_no_invented_price_or_worker_details(self):
        self.add_listing(1, '500.00', service=self.service)

        response = self.estimate(service=self.service)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'insufficient_data')
        self.assertEqual(response.data['estimates'], [])
        self.assertNotIn('Pricing Worker', str(response.data))
        self.assertIn(
            'not verified or completed transaction amounts',
            str(response.data['limitations']),
        )

    def test_estimate_uses_median_and_middle_range_for_three_comparable_listings(self):
        for number, price in enumerate(('300.00', '100.00', '200.00'), start=1):
            self.add_listing(number, price, service=self.service)

        response = self.estimate(service=self.service)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'available')
        estimate = response.data['estimates'][0]
        self.assertEqual(estimate['sample_size'], 3)
        self.assertEqual(estimate['confidence'], 'low')
        self.assertEqual(estimate['median'], '200.00')
        self.assertEqual(estimate['middle_range'], {'low': '100.00', 'high': '300.00'})
        self.assertIn('Nearest-rank', estimate['range_method'])
        self.assertEqual(estimate['pricing_type'], 'fixed')

    def test_confidence_remains_capped_at_moderate_for_larger_samples(self):
        for number, price in enumerate(
            ('100.00', '200.00', '300.00', '400.00', '500.00'),
            start=1,
        ):
            self.add_listing(number, price, service=self.service)

        response = self.estimate(service=self.service)

        self.assertEqual(response.data['estimates'][0]['confidence'], 'moderate')
        self.assertIn('never high', response.data['confidence_method'])

    def test_service_estimate_does_not_mix_category_only_or_other_service_prices(self):
        for number, price in enumerate(('100.00', '200.00', '300.00'), start=1):
            self.add_listing(number, price, service=self.service)
        for number, price in enumerate(('700.00', '800.00', '900.00'), start=4):
            self.add_listing(number, price, service=None)
        for number, price in enumerate(('1100.00', '1200.00', '1300.00'), start=7):
            self.add_listing(number, price, service=self.other_service)
        self.add_listing(10, '1500.00', service=self.service, pricing_type='hourly')

        response = self.estimate(service=self.service)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data['estimates']), 1)
        self.assertEqual(response.data['estimates'][0]['median'], '200.00')
        self.assertEqual(response.data['estimates'][0]['sample_size'], 3)
        self.assertEqual(response.data['suppressed_groups'], 1)

    def test_inactive_and_unavailable_workers_are_excluded(self):
        for number, price in enumerate(('100.00', '200.00'), start=1):
            self.add_listing(number, price, service=self.service)
        self.add_listing(3, '300.00', service=self.service, available=False)
        inactive = self.add_listing(4, '400.00', service=self.service)
        inactive.worker.user.is_active = False
        inactive.worker.user.save(update_fields=['is_active'])

        response = self.estimate(service=self.service)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'insufficient_data')

    def test_invalid_service_category_pair_is_rejected(self):
        response = self.estimate(service=self.other_service)

        self.assertEqual(response.status_code, 400)
        self.assertIn('service_id', response.data)
