from datetime import date
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from categories.models import ServiceCategory
from enquiries.models import Enquiry
from profiles.models import WorkerProfile
from services.models import Service

User = get_user_model()


class EnquiryAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create_user(
            email='cust_enq@test.invalid', phone='9849099003', password='Password123!', full_name='Customer Two', is_customer=True
        )
        self.worker_user = User.objects.create_user(
            email='work_enq@test.invalid', phone='9849099004', password='Password123!', full_name='Worker Two', is_worker=True, is_customer=False
        )
        self.worker = WorkerProfile.objects.create(user=self.worker_user)
        self.category = ServiceCategory.objects.create(name='Plumbing', slug='plumbing')
        self.service = Service.objects.create(category=self.category, name='Pipe fix', slug='pipe-fix')

    def test_customer_can_send_enquiry_with_contact_preference(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.post('/api/enquiries/', {
            'worker_id': self.worker.id,
            'category_id': self.category.id,
            'service_id': self.service.id,
            'subject': 'Leak in kitchen pipe',
            'message': 'Need urgent assistance this evening',
            'contact_preference': 'whatsapp',
            'preferred_date': str(date.today()),
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Enquiry.objects.count(), 1)
        enquiry = Enquiry.objects.first()
        self.assertEqual(enquiry.contact_preference, 'whatsapp')
        self.assertEqual(enquiry.status, Enquiry.Status.PENDING)

    def test_worker_can_accept_enquiry(self):
        enquiry = Enquiry.objects.create(
            customer=self.customer, worker=self.worker, category=self.category,
            subject='Urgent check', message='Please reply', contact_preference='call'
        )
        self.client.force_authenticate(user=self.worker_user)
        response = self.client.post(f'/api/enquiries/{enquiry.id}/status/', {'status': 'accepted'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        enquiry.refresh_from_db()
        self.assertEqual(enquiry.status, Enquiry.Status.ACCEPTED)
