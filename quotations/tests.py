from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from categories.models import ServiceCategory
from profiles.models import Address, WorkerProfile
from quotations.models import JobRequest, Quotation, QuotationRevision, WorkAgreement
from services.models import Service

User = get_user_model()


class QuotationWorkflowTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            email='job-customer@example.com',
            phone='9000000001',
            full_name='Job Customer',
            password='SecurePass123!',
            is_customer=True,
        )
        self.worker_user = User.objects.create_user(
            email='job-worker@example.com',
            phone='9000000002',
            full_name='Job Worker',
            password='SecurePass123!',
            is_customer=False,
            is_worker=True,
        )
        self.worker, _ = WorkerProfile.objects.get_or_create(user=self.worker_user)
        self.other_worker_user = User.objects.create_user(
            email='other-job-worker@example.com',
            phone='9000000003',
            full_name='Other Worker',
            password='SecurePass123!',
            is_customer=False,
            is_worker=True,
        )
        self.other_worker, _ = WorkerProfile.objects.get_or_create(user=self.other_worker_user)
        self.other_customer = User.objects.create_user(
            email='other-job-customer@example.com',
            phone='9000000004',
            full_name='Other Customer',
            password='SecurePass123!',
            is_customer=True,
        )
        self.category = ServiceCategory.objects.create(name='Electrical', slug='electrical')
        self.service = Service.objects.create(
            category=self.category,
            name='Wiring',
            slug='wiring',
        )
        self.address = Address.objects.create(
            user=self.customer,
            label='Home',
            address_line1='12 Private Street',
            locality='Kukatpally',
            city='Hyderabad',
            state='Telangana',
            pincode='500072',
        )
        self.client = APIClient()

    def create_job(self):
        self.client.force_authenticate(self.customer)
        response = self.client.post(
            '/api/quotations/jobs/',
            {
                'category_id': self.category.id,
                'service_id': self.service.id,
                'address_id': self.address.id,
                'title': 'Repair house wiring',
                'description': 'Inspect and repair two rooms.',
                'budget_min': '500.00',
                'budget_max': '1500.00',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        return JobRequest.objects.get(pk=response.data['id'])

    def create_quotation(self, job, worker=None, amount='1200.00'):
        worker = worker or self.worker
        self.client.force_authenticate(worker.user)
        response = self.client.post(
            '/api/quotations/',
            {
                'job_request_id': job.id,
                'amount': amount,
                'message': 'Includes inspection and repair.',
                'estimated_days': 2,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        return Quotation.objects.get(pk=response.data['id'])

    def test_customer_creates_private_job_and_workers_discover_only_open_jobs(self):
        job = self.create_job()
        self.assertEqual(job.customer, self.customer)
        self.assertEqual(job.status, JobRequest.Status.OPEN)

        self.client.force_authenticate(self.worker_user)
        response = self.client.get('/api/quotations/jobs/?role=worker')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        job_data = response.data['results'][0]
        self.assertEqual(job_data['id'], job.id)
        self.assertNotIn('address', job_data)
        self.assertNotIn('address_line1', str(job_data))

        self.client.force_authenticate(self.other_customer)
        self.assertEqual(
            self.client.post(f'/api/quotations/jobs/{job.id}/cancel/').status_code,
            404,
        )

    def test_customer_counter_worker_response_and_acceptance_create_immutable_agreement(self):
        job = self.create_job()
        quotation = self.create_quotation(job)
        competing_quotation = self.create_quotation(job, self.other_worker, '1400.00')
        self.assertEqual(
            JobRequest.objects.get(pk=job.pk).status,
            JobRequest.Status.IN_REVIEW,
        )

        self.client.force_authenticate(self.customer)
        counter = self.client.post(
            f'/api/quotations/{quotation.id}/counter/',
            {'amount': '1000.00', 'message': 'Please include cleanup.', 'estimated_days': 2},
            format='json',
        )
        self.assertEqual(counter.status_code, 200, counter.data)
        revision_id = counter.data['revisions'][0]['id']

        self.client.force_authenticate(self.worker_user)
        response = self.client.post(
            f'/api/quotations/{quotation.id}/respond-counter/',
            {'revision_id': revision_id, 'decision': 'accept', 'response_message': 'Agreed.'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        quotation.refresh_from_db()
        self.assertEqual(str(quotation.amount), '1000.00')
        self.assertEqual(
            QuotationRevision.objects.get(pk=revision_id).status,
            QuotationRevision.Status.ACCEPTED,
        )

        self.client.force_authenticate(self.customer)
        accepted = self.client.post(f'/api/quotations/{quotation.id}/accept/')
        self.assertEqual(accepted.status_code, 201, accepted.data)
        agreement = WorkAgreement.objects.get(job_request=job)
        self.assertEqual(agreement.customer, self.customer)
        self.assertEqual(agreement.worker, self.worker)
        self.assertEqual(agreement.scope_snapshot['title'], 'Repair house wiring')
        self.assertEqual(agreement.terms_snapshot['amount'], '1000.00')
        self.assertEqual(
            agreement.scope_snapshot['service_location']['address_line1'],
            '12 Private Street',
        )
        self.assertEqual(accepted.data['scope_snapshot'], agreement.scope_snapshot)
        self.assertEqual(
            JobRequest.objects.get(pk=job.pk).status,
            JobRequest.Status.AWARDED,
        )
        self.assertEqual(
            Quotation.objects.get(pk=competing_quotation.pk).status,
            Quotation.Status.DECLINED,
        )
        with self.assertRaises(DjangoValidationError):
            agreement.save()
        with self.assertRaises(DjangoValidationError):
            agreement.delete()

        listed = self.client.get('/api/quotations/?role=customer')
        saved_quote = next(item for item in listed.data['results'] if item['id'] == quotation.id)
        self.assertEqual(saved_quote['agreement']['id'], agreement.id)
        self.assertEqual(
            saved_quote['agreement']['scope_snapshot']['service_location']['address_line1'],
            '12 Private Street',
        )

        self.client.force_authenticate(self.worker_user)
        worker_agreement = self.client.get(f'/api/quotations/{quotation.id}/agreement/')
        self.assertEqual(worker_agreement.status_code, 200, worker_agreement.data)
        self.client.force_authenticate(self.other_worker_user)
        self.assertEqual(self.client.get(f'/api/quotations/{quotation.id}/agreement/').status_code, 404)

        self.client.force_authenticate(self.customer)
        duplicate_accept = self.client.post(f'/api/quotations/{competing_quotation.id}/accept/')
        self.assertNotEqual(duplicate_accept.status_code, 201)

    def test_invalid_ownership_duplicate_quotes_and_job_constraints_are_rejected(self):
        job = self.create_job()
        self.client.force_authenticate(self.other_customer)
        invalid_job = self.client.post(
            '/api/quotations/jobs/',
            {
                'category_id': self.category.id,
                'address_id': self.address.id,
                'title': 'Wrong address owner',
                'description': 'This must be rejected.',
            },
            format='json',
        )
        self.assertEqual(invalid_job.status_code, 400)

        self.client.force_authenticate(self.customer)
        self.assertEqual(
            self.client.post(
                '/api/quotations/jobs/',
                {
                    'category_id': self.category.id,
                    'service_id': self.service.id,
                    'title': 'Invalid budget',
                    'description': 'Maximum is below minimum.',
                    'budget_min': '900.00',
                    'budget_max': '500.00',
                },
                format='json',
            ).status_code,
            400,
        )

        self.client.force_authenticate(self.worker_user)
        self.assertEqual(
            self.client.post(
                '/api/quotations/',
                {'job_request_id': job.id, 'amount': '0.00'},
                format='json',
            ).status_code,
            400,
        )
        own_job = JobRequest.objects.create(
            customer=self.worker_user,
            category=self.category,
            title='Worker own job',
            description='Not quoteable by its owner.',
        )
        self.assertEqual(
            self.client.post(
                '/api/quotations/',
                {'job_request_id': own_job.id, 'amount': '100.00'},
                format='json',
            ).status_code,
            400,
        )
        first = self.create_quotation(job)
        duplicate = self.client.post(
            '/api/quotations/',
            {'job_request_id': job.id, 'amount': '1300.00'},
            format='json',
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertTrue(Quotation.objects.filter(pk=first.pk).exists())

    def test_job_and_quotation_details_are_scoped_to_their_parties(self):
        job = self.create_job()
        quotation = self.create_quotation(job)

        self.client.force_authenticate(self.other_worker_user)
        job_response = self.client.get(f'/api/quotations/jobs/{job.id}/')
        self.assertEqual(job_response.status_code, 200)
        self.assertNotIn('address_line1', str(job_response.data))
        self.assertEqual(self.client.get(f'/api/quotations/{quotation.id}/').status_code, 404)

        self.client.force_authenticate(self.other_customer)
        self.assertEqual(self.client.get(f'/api/quotations/{quotation.id}/').status_code, 404)
        self.assertEqual(
            self.client.post(f'/api/quotations/{quotation.id}/accept/').status_code,
            404,
        )

    def test_declining_last_quote_reopens_job_and_worker_can_withdraw(self):
        job = self.create_job()
        quotation = self.create_quotation(job)
        self.client.force_authenticate(self.customer)
        declined = self.client.post(f'/api/quotations/{quotation.id}/decline/')
        self.assertEqual(declined.status_code, 200, declined.data)
        self.assertEqual(
            JobRequest.objects.get(pk=job.pk).status,
            JobRequest.Status.OPEN,
        )

        second_job = self.create_job()
        second_quotation = self.create_quotation(second_job)
        self.client.force_authenticate(self.worker_user)
        withdrawn = self.client.post(f'/api/quotations/{second_quotation.id}/withdraw/')
        self.assertEqual(withdrawn.status_code, 200, withdrawn.data)
        self.assertEqual(
            Quotation.objects.get(pk=second_quotation.pk).status,
            Quotation.Status.WITHDRAWN,
        )

    def test_customer_cancellation_closes_quotes_and_pending_counters(self):
        job = self.create_job()
        quotation = self.create_quotation(job)
        self.client.force_authenticate(self.customer)
        counter = self.client.post(
            f'/api/quotations/{quotation.id}/counter/',
            {'amount': '1000.00'},
            format='json',
        )
        self.assertEqual(counter.status_code, 200, counter.data)
        revision_id = counter.data['revisions'][0]['id']

        cancelled = self.client.post(f'/api/quotations/jobs/{job.id}/cancel/')
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(
            JobRequest.objects.get(pk=job.pk).status,
            JobRequest.Status.CANCELLED,
        )
        self.assertEqual(
            Quotation.objects.get(pk=quotation.pk).status,
            Quotation.Status.DECLINED,
        )
        self.assertEqual(
            QuotationRevision.objects.get(pk=revision_id).status,
            QuotationRevision.Status.REJECTED,
        )
        self.client.force_authenticate(self.worker_user)
        self.assertEqual(
            self.client.post(
                f'/api/quotations/{quotation.id}/respond-counter/',
                {'revision_id': revision_id, 'decision': 'accept'},
                format='json',
            ).status_code,
            400,
        )

