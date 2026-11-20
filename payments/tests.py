import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from requests.exceptions import Timeout
from rest_framework.test import APIClient

from bookings.models import Booking
from categories.models import ServiceCategory
from payments.models import (
    Payment,
    PaymentLedgerEntry,
    PaymentProviderEvent,
    Payout,
    PayoutProviderEvent,
)
from profiles.models import Address, WorkerProfile
from projects.models import Project
from quotations.models import JobRequest, Quotation, WorkAgreement
from services.models import Service

User = get_user_model()
WEBHOOK_SECRET = 'test-webhook-secret'


class PaymentWorkflowTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            email='payments-customer@example.com',
            phone='9400000001',
            full_name='Payments Customer',
            password='SecurePass123!',
            is_customer=True,
        )
        self.worker_user = User.objects.create_user(
            email='payments-worker@example.com',
            phone='9400000002',
            full_name='Payments Worker',
            password='SecurePass123!',
            is_customer=False,
            is_worker=True,
        )
        self.worker, _ = WorkerProfile.objects.get_or_create(user=self.worker_user)
        self.outsider = User.objects.create_user(
            email='payments-outsider@example.com',
            phone='9400000003',
            full_name='Payments Outsider',
            password='SecurePass123!',
            is_customer=True,
        )
        self.admin = User.objects.create_user(
            email='payments-admin@example.com',
            phone='9400000004',
            full_name='Payments Admin',
            password='SecurePass123!',
            is_staff=True,
        )
        self.category = ServiceCategory.objects.create(
            name='Payments Plumbing',
            slug='payments-plumbing',
        )
        self.service = Service.objects.create(
            category=self.category,
            name='Payments Pipe Repair',
            slug='payments-pipe-repair',
        )
        self.address = Address.objects.create(
            user=self.customer,
            label='Home',
            address_line1='1 Payments Street',
            locality='Kukatpally',
            city='Hyderabad',
            state='Telangana',
            pincode='500072',
        )
        self.booking = Booking.objects.create(
            customer=self.customer,
            worker=self.worker,
            service=self.service,
            address=self.address,
            scheduled_date=timezone.localdate(),
            estimated_amount=Decimal('345.67'),
            status=Booking.Status.CONFIRMED,
        )
        self.job = JobRequest.objects.create(
            customer=self.customer,
            category=self.category,
            service=self.service,
            title='Repair a pipe',
            description='Repair the leaking kitchen pipe.',
            status=JobRequest.Status.AWARDED,
        )
        self.quotation = Quotation.objects.create(
            job_request=self.job,
            worker=self.worker,
            amount=Decimal('875.50'),
            status=Quotation.Status.ACCEPTED,
            accepted_at=timezone.now(),
        )
        self.agreement = WorkAgreement.objects.create(
            job_request=self.job,
            quotation=self.quotation,
            customer=self.customer,
            worker=self.worker,
            scope_snapshot={'title': self.job.title, 'description': self.job.description},
            terms_snapshot={'amount': '875.50', 'currency': 'INR'},
            accepted_at=timezone.now(),
        )
        self.client = APIClient()

    def _create_order_response(self, order_id='order_test_1', amount=34567):
        return {'id': order_id, 'amount': amount, 'currency': 'INR'}

    def _checkout(self, key, payload, user=None):
        self.client.force_authenticate(user or self.customer)
        return self.client.post(
            '/api/payments/checkout/',
            payload,
            format='json',
            HTTP_IDEMPOTENCY_KEY=key,
        )

    def _signed_webhook(self, event_type, event_payload, event_id='event_test_1'):
        body = json.dumps({
            'event': event_type,
            'payload': event_payload,
        }, separators=(',', ':')).encode('utf-8')
        signature = hmac.new(
            WEBHOOK_SECRET.encode('utf-8'),
            body,
            hashlib.sha256,
        ).hexdigest()
        return self.client.generic(
            'POST',
            '/api/payments/webhooks/razorpay/',
            body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=signature,
            HTTP_X_RAZORPAY_EVENT_ID=event_id,
        )

    def _pending_payment(self, payable='booking'):
        values = {
            'customer': self.customer,
            'amount': Decimal('345.67') if payable == 'booking' else Decimal('875.50'),
            'status': Payment.Status.PENDING,
            'idempotency_key': f'initial-{payable}-key',
            'provider_order_id': f'order-{payable}',
        }
        values['booking' if payable == 'booking' else 'agreement'] = (
            self.booking if payable == 'booking' else self.agreement
        )
        return Payment.objects.create(**values)

    def _captured_payment(self, payable='booking', customer_approved=True):
        payment = self._pending_payment(payable)
        payment.provider_payment_id = f'pay-captured-{payable}'
        payment.status = Payment.Status.SUCCEEDED
        payment.save(update_fields=['provider_payment_id', 'status', 'updated_at'])
        PaymentLedgerEntry.objects.create(
            payment=payment,
            entry_type=PaymentLedgerEntry.EntryType.CAPTURE,
            amount=payment.amount,
            provider_reference=f'capture:{payment.provider_payment_id}',
        )
        self.worker.razorpayx_fund_account_id = 'fa_test_worker'
        self.worker.save(update_fields=['razorpayx_fund_account_id'])
        if payable == 'booking':
            self.booking.status = Booking.Status.COMPLETED
            self.booking.completed_at = timezone.now()
            self.booking.customer_approved_completed_at = (
                timezone.now() if customer_approved else None
            )
            self.booking.save(update_fields=[
                'status', 'completed_at', 'customer_approved_completed_at', 'updated_at',
            ])
        elif customer_approved:
            Project.objects.create(
                agreement=self.agreement,
                title='Approved plumbing project',
                description='Complete plumbing repair',
                status=Project.Status.COMPLETED,
                completed_at=timezone.now(),
            )
        return payment

    def _request_payout(self, payment, user=None):
        self.client.force_authenticate(user or self.worker_user)
        return self.client.post(
            '/api/payments/payouts/request/',
            {'payment_id': payment.pk},
            format='json',
        )

    def _signed_payout_webhook(self, event_type, payout_data):
        body = json.dumps({
            'event': event_type,
            'payload': {'payout': {'entity': payout_data}},
        }, separators=(',', ':')).encode('utf-8')
        signature = hmac.new(
            WEBHOOK_SECRET.encode('utf-8'),
            body,
            hashlib.sha256,
        ).hexdigest()
        return self.client.generic(
            'POST',
            '/api/payments/webhooks/razorpayx/',
            body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=signature,
        )

    @override_settings(RAZORPAY_KEY_ID='rzp_test_key', RAZORPAY_KEY_SECRET='rzp_test_secret')
    @patch('payments.api.views.razorpay.Client')
    def test_booking_checkout_uses_server_amount_and_reuses_idempotent_order(self, client_class):
        client_class.return_value.order.create.return_value = self._create_order_response()

        first = self._checkout(
            'booking-payment-1',
            {'booking_id': self.booking.id, 'amount': '1.00'},
        )

        self.assertEqual(first.status_code, 201, first.data)
        payment = Payment.objects.get(pk=first.data['payment']['id'])
        self.assertEqual(payment.amount, Decimal('345.67'))
        self.assertEqual(first.data['order']['amount'], 34567)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(client_class.return_value.order.create.call_count, 1)

        repeated = self._checkout(
            'booking-payment-1',
            {'booking_id': self.booking.id},
        )
        self.assertEqual(repeated.status_code, 200, repeated.data)
        self.assertEqual(repeated.data['payment']['id'], payment.id)
        same_work = self._checkout(
            'booking-payment-retry',
            {'booking_id': self.booking.id},
        )
        self.assertEqual(same_work.status_code, 200, same_work.data)
        self.assertEqual(same_work.data['payment']['id'], payment.id)
        self.assertEqual(client_class.return_value.order.create.call_count, 1)

    @override_settings(RAZORPAY_KEY_ID='rzp_test_key', RAZORPAY_KEY_SECRET='rzp_test_secret')
    @patch('payments.api.views.razorpay.Client')
    def test_agreement_checkout_uses_immutable_agreement_amount(self, client_class):
        client_class.return_value.order.create.return_value = self._create_order_response(
            'order_agreement',
            87550,
        )

        response = self._checkout(
            'agreement-payment-1',
            {'agreement_id': self.agreement.id, 'amount': '0.01'},
        )

        self.assertEqual(response.status_code, 201, response.data)
        payment = Payment.objects.get(pk=response.data['payment']['id'])
        self.assertEqual(payment.agreement, self.agreement)
        self.assertIsNone(payment.booking)
        self.assertEqual(payment.amount, Decimal('875.50'))

    def test_checkout_rejects_missing_idempotency_key_and_non_customer(self):
        self.client.force_authenticate(self.customer)
        missing_key = self.client.post(
            '/api/payments/checkout/',
            {'booking_id': self.booking.id},
            format='json',
        )
        self.assertEqual(missing_key.status_code, 400)

        worker_response = self._checkout(
            'worker-payment-key',
            {'booking_id': self.booking.id},
            user=self.worker_user,
        )
        self.assertEqual(worker_response.status_code, 403)
        self.assertEqual(Payment.objects.count(), 0)

    @override_settings(RAZORPAY_KEY_ID='', RAZORPAY_KEY_SECRET='')
    def test_checkout_fails_explicitly_when_gateway_credentials_are_missing(self):
        response = self._checkout(
            'unconfigured-payment-key',
            {'booking_id': self.booking.id},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(Payment.objects.count(), 0)

    @override_settings(RAZORPAY_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_signed_capture_is_idempotent_and_creates_immutable_ledger_entry(self):
        payment = self._pending_payment()
        event_payload = {
            'payment': {
                'entity': {
                    'id': 'pay_test_1',
                    'order_id': payment.provider_order_id,
                    'amount': 34567,
                    'currency': 'INR',
                },
            },
        }

        response = self._signed_webhook('payment.captured', event_payload)

        self.assertEqual(response.status_code, 200, response.data)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(payment.provider_payment_id, 'pay_test_1')
        self.assertEqual(PaymentLedgerEntry.objects.filter(payment=payment).count(), 1)
        self.assertEqual(PaymentProviderEvent.objects.filter(payment=payment).count(), 1)
        duplicate = self._signed_webhook(
            'payment.captured',
            event_payload,
            'different-untrusted-event-header',
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.data['duplicate'])
        self.assertEqual(PaymentLedgerEntry.objects.filter(payment=payment).count(), 1)
        conflicting_capture = self._signed_webhook(
            'payment.captured',
            {'payment': {'entity': {
                'id': 'pay_different_capture',
                'order_id': payment.provider_order_id,
                'amount': 34567,
                'currency': 'INR',
            }}},
            'different-capture-event',
        )
        self.assertEqual(conflicting_capture.status_code, 400)
        payment.refresh_from_db()
        self.assertEqual(payment.provider_payment_id, 'pay_test_1')
        self.assertEqual(PaymentLedgerEntry.objects.filter(payment=payment).count(), 1)
        entry = PaymentLedgerEntry.objects.get(payment=payment)
        with self.assertRaises(DjangoValidationError):
            entry.delete()
        provider_event = PaymentProviderEvent.objects.get(payment=payment)
        with self.assertRaises(DjangoValidationError):
            provider_event.delete()

    @override_settings(RAZORPAY_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_invalid_signature_and_mismatched_amount_do_not_settle_payment(self):
        payment = self._pending_payment()
        self.client.force_authenticate(None)
        invalid = self.client.generic(
            'POST',
            '/api/payments/webhooks/razorpay/',
            b'{"event":"payment.captured"}',
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE='invalid',
            HTTP_X_RAZORPAY_EVENT_ID='bad-signature-event',
        )
        self.assertEqual(invalid.status_code, 403)

        mismatch = self._signed_webhook(
            'payment.captured',
            {'payment': {'entity': {
                'id': 'pay_wrong_amount',
                'order_id': payment.provider_order_id,
                'amount': 100,
                'currency': 'INR',
            }}},
            'wrong-amount-event',
        )
        self.assertEqual(mismatch.status_code, 400)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(PaymentProviderEvent.objects.count(), 0)

    @override_settings(RAZORPAY_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_refund_events_reconcile_partial_refunds_without_replaying_ledger(self):
        payment = self._pending_payment('agreement')
        payment.provider_payment_id = 'pay_refund_test'
        payment.status = Payment.Status.SUCCEEDED
        payment.save(update_fields=['provider_payment_id', 'status', 'updated_at'])
        PaymentLedgerEntry.objects.create(
            payment=payment,
            entry_type=PaymentLedgerEntry.EntryType.CAPTURE,
            amount=payment.amount,
            provider_reference='capture:pay_refund_test',
        )
        refund_payload = {'refund': {'entity': {
            'id': 'rf_test_1',
            'payment_id': 'pay_refund_test',
            'amount': 12500,
            'currency': 'INR',
        }}}

        first = self._signed_webhook('refund.processed', refund_payload, 'refund-event-1')
        repeated_body = self._signed_webhook('refund.processed', refund_payload, 'refund-event-2')

        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(repeated_body.status_code, 200, repeated_body.data)
        payment.refresh_from_db()
        self.assertEqual(payment.refunded_amount, Decimal('125.00'))
        self.assertEqual(payment.status, Payment.Status.PARTIALLY_REFUNDED)
        self.assertEqual(
            PaymentLedgerEntry.objects.filter(
                payment=payment,
                entry_type=PaymentLedgerEntry.EntryType.REFUND,
            ).count(),
            1,
        )
        late_capture = self._signed_webhook(
            'payment.captured',
            {'payment': {'entity': {
                'id': 'pay_refund_test',
                'order_id': payment.provider_order_id,
                'amount': 87550,
                'currency': 'INR',
            }}},
            'late-capture-event',
        )
        self.assertEqual(late_capture.status_code, 200, late_capture.data)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PARTIALLY_REFUNDED)

    def test_payment_records_are_visible_only_to_their_parties(self):
        payment = self._pending_payment()
        self.client.force_authenticate(self.customer)
        self.assertEqual(self.client.get(f'/api/payments/{payment.id}/').status_code, 200)
        self.client.force_authenticate(self.worker_user)
        self.assertEqual(self.client.get(f'/api/payments/{payment.id}/').status_code, 200)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(f'/api/payments/{payment.id}/').status_code, 404)

    @override_settings(RAZORPAY_KEY_ID='rzp_test_key', RAZORPAY_KEY_SECRET='rzp_test_secret')
    @patch('payments.api.views.razorpay.Client')
    def test_customer_verification_fetches_provider_state_before_recording_capture(self, client_class):
        payment = self._pending_payment()
        client_class.return_value.payment.fetch.return_value = {
            'id': 'pay_verified',
            'order_id': payment.provider_order_id,
            'amount': 34567,
            'currency': 'INR',
            'status': 'captured',
        }
        payload = {
            'razorpay_order_id': payment.provider_order_id,
            'razorpay_payment_id': 'pay_verified',
            'razorpay_signature': 'valid-signature',
        }
        self.client.force_authenticate(self.customer)

        response = self.client.post('/api/payments/verify/', payload, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(payment.provider_payment_id, 'pay_verified')
        self.assertEqual(PaymentLedgerEntry.objects.filter(payment=payment).count(), 1)
        client_class.return_value.utility.verify_payment_signature.assert_called_once_with(payload)

    @override_settings(RAZORPAY_KEY_ID='rzp_test_key', RAZORPAY_KEY_SECRET='rzp_test_secret')
    @patch('payments.api.views.razorpay.Client')
    def test_customer_verification_does_not_settle_an_authorized_payment(self, client_class):
        payment = self._pending_payment()
        client_class.return_value.payment.fetch.return_value = {
            'id': 'pay_authorized',
            'order_id': payment.provider_order_id,
            'amount': 34567,
            'currency': 'INR',
            'status': 'authorized',
        }
        self.client.force_authenticate(self.customer)

        response = self.client.post(
            '/api/payments/verify/',
            {
                'razorpay_order_id': payment.provider_order_id,
                'razorpay_payment_id': 'pay_authorized',
                'razorpay_signature': 'valid-signature',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 202, response.data)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertFalse(PaymentLedgerEntry.objects.filter(payment=payment).exists())

    def test_customer_approval_is_required_before_worker_can_request_payout(self):
        payment = self._captured_payment(customer_approved=False)
        denied = self._request_payout(payment)
        self.assertEqual(denied.status_code, 400, denied.data)
        self.assertFalse(Payout.objects.exists())

        self.client.force_authenticate(self.worker_user)
        worker_approval = self.client.post(
            f'/api/bookings/{self.booking.pk}/approve-completion/',
            {},
            format='json',
        )
        self.assertEqual(worker_approval.status_code, 403, worker_approval.data)

        self.client.force_authenticate(self.customer)
        approved = self.client.post(
            f'/api/bookings/{self.booking.pk}/approve-completion/',
            {},
            format='json',
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertIsNotNone(approved.data['customer_approved_completed_at'])
        self.assertEqual(
            self.client.post(
                f'/api/bookings/{self.booking.pk}/approve-completion/',
                {},
                format='json',
            ).status_code,
            200,
        )

        created = self._request_payout(payment)
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data['payout']['amount'], '345.67')
        self.assertNotIn('provider_fund_account_id', created.data['payout'])

    def test_agreement_payout_requires_completed_customer_approved_project(self):
        payment = self._captured_payment('agreement', customer_approved=False)
        denied = self._request_payout(payment)
        self.assertEqual(denied.status_code, 400, denied.data)

        Project.objects.create(
            agreement=self.agreement,
            title='Approved plumbing project',
            description='Complete plumbing repair',
            status=Project.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        approved = self._request_payout(payment)
        self.assertEqual(approved.status_code, 201, approved.data)
        self.assertEqual(approved.data['payout']['amount'], '875.50')

    def test_payout_amount_excludes_refunded_and_reserved_funds(self):
        payment = self._captured_payment()
        payment.refunded_amount = Decimal('45.67')
        payment.status = Payment.Status.PARTIALLY_REFUNDED
        payment.save(update_fields=['refunded_amount', 'status', 'updated_at'])
        PaymentLedgerEntry.objects.create(
            payment=payment,
            entry_type=PaymentLedgerEntry.EntryType.REFUND,
            amount=Decimal('45.67'),
            provider_reference='refund:rf_test_net',
        )
        response = self._request_payout(payment)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['payout']['amount'], '300.00')
        self.assertEqual(
            self._request_payout(payment).status_code,
            400,
        )

    @override_settings(
        RAZORPAYX_KEY_ID='',
        RAZORPAYX_KEY_SECRET='',
        RAZORPAYX_ACCOUNT_NUMBER='',
    )
    def test_admin_cannot_submit_payout_without_provider_configuration(self):
        payment = self._captured_payment()
        requested = self._request_payout(payment)
        payout_id = requested.data['payout']['id']
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            f'/api/payments/payouts/{payout_id}/review/',
            {'decision': 'approve'},
            format='json',
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(Payout.objects.get(pk=payout_id).status, Payout.Status.REQUESTED)

    @override_settings(
        RAZORPAYX_KEY_ID='rzpx_test_key',
        RAZORPAYX_KEY_SECRET='rzpx_test_secret',
        RAZORPAYX_ACCOUNT_NUMBER='test_account_number',
    )
    @patch('payments.api.views.requests.post')
    def test_admin_approval_submits_idempotent_provider_payout(self, post_request):
        payment = self._captured_payment()
        requested = self._request_payout(payment)
        payout_id = requested.data['payout']['id']
        self.client.force_authenticate(self.admin)

        def provider_response(*args, **kwargs):
            payload = kwargs['json']
            response = Mock()
            response.raise_for_status.return_value = None
            response.json.return_value = {
                'id': 'pout_test_1',
                'amount': payload['amount'],
                'currency': payload['currency'],
                'fund_account_id': payload['fund_account_id'],
                'reference_id': payload['reference_id'],
                'status': 'queued',
            }
            return response

        post_request.side_effect = Timeout('provider response timed out')
        uncertain = self.client.post(
            f'/api/payments/payouts/{payout_id}/review/',
            {'decision': 'approve'},
            format='json',
        )
        self.assertEqual(uncertain.status_code, 502)
        payout = Payout.objects.get(pk=payout_id)
        self.assertEqual(payout.status, Payout.Status.PROCESSING)
        self.assertFalse(payout.provider_payout_id)
        idempotency_key = post_request.call_args.kwargs['headers']['X-Payout-Idempotency']
        post_request.side_effect = provider_response
        response = self.client.post(
            f'/api/payments/payouts/{payout_id}/review/',
            {'decision': 'approve'},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        payout = Payout.objects.get(pk=payout_id)
        self.assertEqual(payout.status, Payout.Status.PROCESSING)
        self.assertEqual(payout.provider_payout_id, 'pout_test_1')
        self.assertEqual(idempotency_key, str(payout.idempotency_key))
        self.assertEqual(
            post_request.call_args.kwargs['headers']['X-Payout-Idempotency'],
            idempotency_key,
        )
        self.assertEqual(post_request.call_args.kwargs['json']['amount'], 34567)
        self.assertEqual(post_request.call_args.kwargs['json']['account_number'], 'test_account_number')

    @override_settings(
        RAZORPAYX_KEY_ID='rzpx_test_key',
        RAZORPAYX_KEY_SECRET='rzpx_test_secret',
        RAZORPAYX_ACCOUNT_NUMBER='test_account_number',
        RAZORPAYX_WEBHOOK_SECRET=WEBHOOK_SECRET,
    )
    @patch('payments.api.views.requests.post')
    def test_signed_payout_webhook_records_processed_state_and_immutable_ledger(self, post_request):
        payment = self._captured_payment()
        requested = self._request_payout(payment)
        payout_id = requested.data['payout']['id']
        self.client.force_authenticate(self.admin)
        post_request.return_value.raise_for_status.return_value = None
        post_request.return_value.json.return_value = {
            'id': 'pout_test_processed',
            'amount': 34567,
            'currency': 'INR',
            'fund_account_id': 'fa_test_worker',
            'reference_id': Payout.objects.get(pk=payout_id).reference_id,
            'status': 'queued',
        }
        submitted = self.client.post(
            f'/api/payments/payouts/{payout_id}/review/',
            {'decision': 'approve'},
            format='json',
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)

        provider_data = {
            'id': 'pout_test_processed',
            'amount': 34567,
            'currency': 'INR',
            'fund_account_id': 'fa_test_worker',
            'reference_id': Payout.objects.get(pk=payout_id).reference_id,
            'status': 'processed',
            'utr': 'UTR-TEST-1',
        }
        self.client.force_authenticate(None)
        captured = self._signed_payout_webhook('payout.processed', provider_data)
        repeated = self._signed_payout_webhook('payout.processed', provider_data)

        self.assertEqual(captured.status_code, 200, captured.data)
        self.assertEqual(repeated.status_code, 200, repeated.data)
        self.assertTrue(repeated.data['duplicate'])
        payout = Payout.objects.get(pk=payout_id)
        self.assertEqual(payout.status, Payout.Status.PAID)
        self.assertEqual(payout.utr, 'UTR-TEST-1')
        payout_entry = PaymentLedgerEntry.objects.get(
            payment=payment,
            entry_type=PaymentLedgerEntry.EntryType.PAYOUT,
        )
        self.assertEqual(payout_entry.amount, Decimal('345.67'))
        self.assertEqual(PayoutProviderEvent.objects.filter(payout=payout).count(), 1)
        with self.assertRaises(DjangoValidationError):
            payout_entry.delete()
        with self.assertRaises(DjangoValidationError):
            PayoutProviderEvent.objects.get(payout=payout).delete()
        stale_event = self._signed_payout_webhook(
            'payout.queued',
            {**provider_data, 'status': 'queued'},
        )
        self.assertEqual(stale_event.status_code, 200, stale_event.data)
        payout.refresh_from_db()
        self.assertEqual(payout.status, Payout.Status.PAID)
        self.assertEqual(payout.provider_status, 'processed')
        reversed_event = self._signed_payout_webhook(
            'payout.reversed',
            {**provider_data, 'status': 'reversed'},
        )
        self.assertEqual(reversed_event.status_code, 200, reversed_event.data)
        payout.refresh_from_db()
        self.assertEqual(payout.status, Payout.Status.FAILED)
        self.assertTrue(PaymentLedgerEntry.objects.filter(
            payment=payment,
            entry_type=PaymentLedgerEntry.EntryType.PAYOUT_REVERSAL,
        ).exists())
        retry = self._request_payout(payment)
        self.assertEqual(retry.status_code, 201, retry.data)

    def test_payout_review_is_staff_only_and_rejection_releases_reserved_balance(self):
        payment = self._captured_payment()
        requested = self._request_payout(payment)
        payout_id = requested.data['payout']['id']
        self.client.force_authenticate(self.worker_user)
        forbidden = self.client.post(
            f'/api/payments/payouts/{payout_id}/review/',
            {'decision': 'reject', 'reason': 'Not approved'},
            format='json',
        )
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_authenticate(self.admin)
        rejected = self.client.post(
            f'/api/payments/payouts/{payout_id}/review/',
            {'decision': 'reject', 'reason': 'Verify the worker payout account.'},
            format='json',
        )
        self.assertEqual(rejected.status_code, 200, rejected.data)
        self.assertEqual(Payout.objects.get(pk=payout_id).status, Payout.Status.REJECTED)
        retry = self._request_payout(payment)
        self.assertEqual(retry.status_code, 201, retry.data)
        self.assertEqual(retry.data['payout']['amount'], '345.67')
