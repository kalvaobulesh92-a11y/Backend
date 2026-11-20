from types import SimpleNamespace

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.permissions import IsAdmin, IsCustomerOwner, IsWorkerOwner
from profiles.models import Address, CustomerProfile, WorkerProfile


User = get_user_model()


class AuthenticationAndRoleApiTests(APITestCase):
    def setUp(self):
        self.registration_data = {
            'email': 'registration@example.com',
            'username': 'registration_user',
            'phone': '9876543210',
            'full_name': 'Registration Test',
            'password': 'Long-Unique-Password!4728',
            'password2': 'Long-Unique-Password!4728',
            'account_type': 'customer',
        }

    def register(self, **overrides):
        payload = {**self.registration_data, **overrides}
        return self.client.post('/api/accounts/register/', payload, format='json')

    def test_customer_registration_creates_customer_profile(self):
        response = self.register()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email=self.registration_data['email'])
        self.assertTrue(user.is_customer)
        self.assertFalse(user.is_worker)
        self.assertTrue(CustomerProfile.objects.filter(user=user).exists())
        self.assertFalse(WorkerProfile.objects.filter(user=user).exists())
        self.assertFalse(response.data['is_admin'])

    def test_worker_registration_creates_unverified_worker_profile(self):
        response = self.register(
            email='worker@example.com',
            username='worker_user',
            phone='9876543211',
            account_type='worker',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='worker@example.com')
        self.assertFalse(user.is_customer)
        self.assertTrue(user.is_worker)
        self.assertFalse(CustomerProfile.objects.filter(user=user).exists())
        self.assertEqual(user.worker_profile.verification_status, 'unverified')

    def test_dual_role_registration_creates_one_user_and_both_profiles(self):
        response = self.register(account_type='both')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email=self.registration_data['email'])
        self.assertTrue(user.is_customer)
        self.assertTrue(user.is_worker)
        self.assertTrue(CustomerProfile.objects.filter(user=user).exists())
        self.assertTrue(WorkerProfile.objects.filter(user=user).exists())
        self.assertEqual(User.objects.filter(email=self.registration_data['email']).count(), 1)

    def test_registration_supports_legacy_is_worker_payload(self):
        payload = {
            key: value
            for key, value in self.registration_data.items()
            if key not in ('account_type', 'username')
        }
        payload['is_worker'] = True
        response = self.client.post('/api/accounts/register/', payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email=self.registration_data['email'])
        self.assertTrue(user.is_customer)
        self.assertTrue(user.is_worker)
        self.assertTrue(user.username)

    def test_duplicate_email_is_rejected(self):
        self.assertEqual(self.register().status_code, status.HTTP_201_CREATED)
        response = self.register(username='another_user', phone='9876543212')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(User.objects.filter(email=self.registration_data['email']).count(), 1)

    def test_duplicate_email_is_rejected_case_insensitively(self):
        self.assertEqual(self.register().status_code, status.HTTP_201_CREATED)
        response = self.register(
            email='REGISTRATION@example.com',
            username='another_user',
            phone='9876543212',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_public_registration_cannot_create_an_admin(self):
        response = self.register(account_type='admin')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(email=self.registration_data['email']).exists())

    def test_duplicate_username_is_rejected_case_insensitively(self):
        self.assertEqual(self.register().status_code, status.HTTP_201_CREATED)
        response = self.register(
            email='another@example.com',
            username='REGISTRATION_USER',
            phone='9876543212',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_returns_tokens_and_me_returns_current_user(self):
        self.assertEqual(self.register().status_code, status.HTTP_201_CREATED)
        response = self.client.post(
            '/api/accounts/login/',
            {'email': self.registration_data['email'], 'password': self.registration_data['password']},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        me_response = self.client.get('/api/accounts/me/')

        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(me_response.data['email'], self.registration_data['email'])
        self.assertNotIn('is_superuser', me_response.data)
        self.assertNotIn('is_staff', me_response.data)

    def test_refresh_token_endpoint_returns_new_access_token(self):
        self.assertEqual(self.register().status_code, status.HTTP_201_CREATED)
        login = self.client.post(
            '/api/accounts/login/',
            {'email': self.registration_data['email'], 'password': self.registration_data['password']},
            format='json',
        )
        response = self.client.post(
            '/api/accounts/token/refresh/',
            {'refresh': login.data['refresh']},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)

    def test_logout_blacklists_the_refresh_token(self):
        self.assertEqual(self.register().status_code, status.HTTP_201_CREATED)
        login = self.client.post(
            '/api/accounts/login/',
            {'email': self.registration_data['email'], 'password': self.registration_data['password']},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        logout = self.client.post(
            '/api/accounts/logout/',
            {'refresh': login.data['refresh']},
            format='json',
        )
        refresh = self.client.post(
            '/api/accounts/token/refresh/',
            {'refresh': login.data['refresh']},
            format='json',
        )

        self.assertEqual(logout.status_code, status.HTTP_205_RESET_CONTENT)
        self.assertEqual(refresh.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_change_password_validates_old_password_and_updates_credentials(self):
        self.assertEqual(self.register().status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email=self.registration_data['email'])
        self.client.force_authenticate(user=user)
        response = self.client.post(
            '/api/accounts/change-password/',
            {
                'old_password': self.registration_data['password'],
                'new_password': 'Another-Long-Password!4728',
                'new_password2': 'Another-Long-Password!4728',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.check_password('Another-Long-Password!4728'))

    def test_worker_activation_is_authenticated_and_idempotent(self):
        self.assertEqual(self.register().status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email=self.registration_data['email'])
        self.client.force_authenticate(user=user)

        first = self.client.post('/api/accounts/activate-worker/', {}, format='json')
        second = self.client.post('/api/accounts/activate-worker/', {}, format='json')

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.is_worker)
        self.assertEqual(WorkerProfile.objects.filter(user=user).count(), 1)
        self.assertEqual(user.worker_profile.verification_status, 'unverified')

    def test_worker_activation_requires_authentication(self):
        response = self.client.post('/api/accounts/activate-worker/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_worker_only_user_cannot_access_customer_profile_or_addresses(self):
        self.register(
            email='worker@example.com',
            username='worker_user',
            phone='9876543211',
            account_type='worker',
        )
        user = User.objects.get(email='worker@example.com')
        self.client.force_authenticate(user=user)

        self.assertEqual(self.client.get('/api/profiles/me/').status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get('/api/profiles/addresses/').status_code, status.HTTP_403_FORBIDDEN)

    def test_worker_profile_self_service_requires_worker_role(self):
        self.register()
        user = User.objects.get(email=self.registration_data['email'])
        self.client.force_authenticate(user=user)

        self.assertEqual(self.client.get('/api/profiles/workers/me/').status_code, status.HTTP_403_FORBIDDEN)

        user.is_worker = True
        user.save(update_fields=('is_worker',))
        WorkerProfile.objects.create(user=user)
        self.assertEqual(self.client.get('/api/profiles/workers/me/').status_code, status.HTTP_200_OK)

    def test_customer_cannot_read_another_customers_private_addresses(self):
        self.register()
        first_user = User.objects.get(email=self.registration_data['email'])
        second_user = User.objects.create_user(
            email='second@example.com',
            username='second_user',
            phone='9876543212',
            full_name='Second User',
            password='Long-Unique-Password!4728',
        )
        address = Address.objects.create(
            user=second_user,
            address_line1='Private street',
            locality='Kukatpally',
            pincode='500072',
        )
        self.client.force_authenticate(user=first_user)

        response = self.client.get('/api/profiles/addresses/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(address.id, [item['id'] for item in response.data['results']])

    def test_profile_update_cannot_escalate_roles_or_admin_privileges(self):
        self.register()
        user = User.objects.get(email=self.registration_data['email'])
        self.client.force_authenticate(user=user)

        response = self.client.patch(
            '/api/accounts/profile/',
            {
                'is_customer': False,
                'is_worker': True,
                'is_staff': True,
                'is_superuser': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.is_customer)
        self.assertFalse(user.is_worker)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_password_confirmation_must_match(self):
        response = self.register(password2='Different-Password!5839')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)
        self.assertFalse(User.objects.filter(email=self.registration_data['email']).exists())

    def test_admin_and_owner_permissions(self):
        customer = User.objects.create_user(
            email='owner@example.com',
            username='owner_user',
            phone='9876543212',
            full_name='Owner User',
            password='Long-Unique-Password!4728',
        )
        other_customer = User.objects.create_user(
            email='other@example.com',
            username='other_user',
            phone='9876543213',
            full_name='Other User',
            password='Long-Unique-Password!4728',
        )
        worker = User.objects.create_user(
            email='owner-worker@example.com',
            username='owner_worker',
            phone='9876543214',
            full_name='Owner Worker',
            password='Long-Unique-Password!4728',
            is_worker=True,
        )
        admin = User.objects.create_superuser(
            email='admin@example.com',
            username='admin_user',
            phone='9876543215',
            full_name='Admin User',
            password='Long-Unique-Password!4728',
        )
        customer_profile = CustomerProfile.objects.create(user=customer)
        worker_profile = WorkerProfile.objects.create(user=worker)

        self.assertTrue(IsAdmin().has_permission(SimpleNamespace(user=admin), None))
        self.assertFalse(IsAdmin().has_permission(SimpleNamespace(user=customer), None))
        self.assertTrue(IsCustomerOwner().has_object_permission(
            SimpleNamespace(user=customer), None, customer_profile,
        ))
        self.assertFalse(IsCustomerOwner().has_object_permission(
            SimpleNamespace(user=other_customer), None, customer_profile,
        ))
        self.assertTrue(IsWorkerOwner().has_object_permission(
            SimpleNamespace(user=worker), None, worker_profile,
        ))
        self.assertFalse(IsWorkerOwner().has_object_permission(
            SimpleNamespace(user=customer), None, worker_profile,
        ))
