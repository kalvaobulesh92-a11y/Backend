import hashlib
import hmac
import json
import logging
import uuid
from decimal import Decimal, InvalidOperation

import razorpay
import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import Booking
from payments.models import (
    Payment,
    PaymentLedgerEntry,
    PaymentProviderEvent,
    Payout,
    PayoutProviderEvent,
)
from projects.models import Project
from quotations.models import WorkAgreement
from .serializers import (
    PaymentCheckoutSerializer,
    PaymentSerializer,
    PaymentVerifySerializer,
    PayoutRequestSerializer,
    PayoutReviewSerializer,
    PayoutSerializer,
)

logger = logging.getLogger(__name__)


def _client_credentials_available():
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def _checkout_data(payment):
    return {
        'payment': PaymentSerializer(payment).data,
        'key_id': settings.RAZORPAY_KEY_ID,
        'order': {
            'id': payment.provider_order_id,
            'amount': int(payment.amount * 100),
            'currency': payment.currency,
        },
    }


def _payout_credentials_available():
    return bool(
        settings.RAZORPAYX_KEY_ID
        and settings.RAZORPAYX_KEY_SECRET
        and settings.RAZORPAYX_ACCOUNT_NUMBER
    )


def _worker_for_payment(payment):
    if payment.booking_id:
        return payment.booking.worker
    return payment.agreement.worker


def _work_is_customer_approved(payment):
    if payment.booking_id:
        return bool(
            payment.booking.status == Booking.Status.COMPLETED
            and payment.booking.customer_approved_completed_at
        )
    try:
        return payment.agreement.project.status == Project.Status.COMPLETED
    except Project.DoesNotExist:
        return False


def _payout_amount_available(payment, exclude_payout_id=None):
    captured = payment.ledger_entries.filter(
        entry_type=PaymentLedgerEntry.EntryType.CAPTURE
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    refunded = payment.ledger_entries.filter(
        entry_type=PaymentLedgerEntry.EntryType.REFUND
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    reserved_payouts = payment.payouts.filter(
        status__in=[
            Payout.Status.REQUESTED,
            Payout.Status.PROCESSING,
            Payout.Status.PAID,
        ]
    )
    if exclude_payout_id:
        reserved_payouts = reserved_payouts.exclude(pk=exclude_payout_id)
    reserved = reserved_payouts.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    return (captured - refunded - reserved).quantize(Decimal('0.01'))


def _payout_status_for_provider(provider_status):
    if provider_status == 'processed':
        return Payout.Status.PAID
    if provider_status in ('failed', 'rejected', 'reversed', 'cancelled'):
        return Payout.Status.FAILED
    return Payout.Status.PROCESSING


def _apply_provider_payout_data(payout, provider_data):
    if not isinstance(provider_data, dict):
        raise ValidationError('RazorpayX returned an invalid payout response.')
    provider_id = provider_data.get('id')
    incoming_status = str(provider_data.get('status', '')).lower()
    status_details = provider_data.get('status_details') or {}
    if (
        not provider_id
        or not incoming_status
        or not isinstance(status_details, dict)
        or str(provider_data.get('amount')) != str(int(payout.amount * 100))
        or provider_data.get('currency') != payout.currency
        or provider_data.get('fund_account_id') != payout.provider_fund_account_id
        or (
            provider_data.get('reference_id')
            and provider_data['reference_id'] != payout.reference_id
        )
    ):
        raise ValidationError('RazorpayX payout details do not match the approved request.')
    if Payout.objects.exclude(pk=payout.pk).filter(provider_payout_id=provider_id).exists():
        raise ValidationError('RazorpayX payout ID is already assigned to another request.')

    provider_status = incoming_status
    next_status = _payout_status_for_provider(incoming_status)
    if payout.status == Payout.Status.PAID and incoming_status != 'reversed':
        provider_status = payout.provider_status or 'processed'
        next_status = Payout.Status.PAID
    elif (
        payout.status == Payout.Status.FAILED
        and payout.provider_status in ('failed', 'rejected', 'cancelled', 'reversed')
        and next_status == Payout.Status.PROCESSING
    ):
        provider_status = payout.provider_status
        next_status = Payout.Status.FAILED

    payout.provider_payout_id = provider_id
    payout.provider_status = provider_status
    payout.status = next_status
    payout.utr = str(provider_data.get('utr') or '')[:100]
    if payout.status == Payout.Status.FAILED:
        payout.failure_reason = str(
            status_details.get('description')
            or status_details.get('reason')
            or f'RazorpayX payout {provider_status}.'
        )[:500]
        payout.completed_at = timezone.now()
    elif payout.status == Payout.Status.PAID:
        payout.failure_reason = ''
        payout.completed_at = timezone.now()
    payout.save(update_fields=[
        'provider_payout_id', 'provider_status', 'status', 'utr',
        'failure_reason', 'completed_at', 'updated_at',
    ])
    if payout.status == Payout.Status.PAID or provider_status == 'reversed':
        PaymentLedgerEntry.objects.get_or_create(
            provider_reference=f'payout:{provider_id}',
            defaults={
                'payment': payout.payment,
                'entry_type': PaymentLedgerEntry.EntryType.PAYOUT,
                'amount': payout.amount,
            },
        )
    if provider_status == 'reversed':
        PaymentLedgerEntry.objects.get_or_create(
            provider_reference=f'payout-reversal:{provider_id}',
            defaults={
                'payment': payout.payment,
                'entry_type': PaymentLedgerEntry.EntryType.PAYOUT_REVERSAL,
                'amount': payout.amount,
            },
        )


def _razorpayx_payout_request_data(payout):
    return {
        'account_number': settings.RAZORPAYX_ACCOUNT_NUMBER,
        'fund_account_id': payout.provider_fund_account_id,
        'amount': int(payout.amount * 100),
        'currency': payout.currency,
        'mode': 'IMPS',
        'purpose': 'payout',
        'queue_if_low_balance': True,
        'reference_id': payout.reference_id,
        'narration': 'KaamConnect payout',
    }


def _submit_razorpayx_payout(payout):
    try:
        response = requests.post(
            'https://api.razorpay.com/v1/payouts',
            json=_razorpayx_payout_request_data(payout),
            auth=(settings.RAZORPAYX_KEY_ID, settings.RAZORPAYX_KEY_SECRET),
            headers={'X-Payout-Idempotency': str(payout.idempotency_key)},
            timeout=(5, 25),
        )
        response.raise_for_status()
        provider_data = response.json()
    except (requests.exceptions.RequestException, ValueError):
        logger.exception('RazorpayX payout submission failed for payout %s', payout.pk)
        return Response(
            {'detail': 'RazorpayX could not confirm the payout request. It remains on hold; retry or reconcile it.'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    try:
        with transaction.atomic():
            payout = Payout.objects.select_for_update().select_related('payment').get(pk=payout.pk)
            _apply_provider_payout_data(payout, provider_data)
    except ValidationError:
        logger.exception('RazorpayX returned inconsistent details for payout %s', payout.pk)
        return Response(
            {'detail': 'RazorpayX returned inconsistent payout details. The payout remains on hold for reconciliation.'},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    return Response({'payout': PayoutSerializer(payout).data})


def _fetch_razorpayx_payout(payout):
    try:
        response = requests.get(
            f'https://api.razorpay.com/v1/payouts/{payout.provider_payout_id}',
            auth=(settings.RAZORPAYX_KEY_ID, settings.RAZORPAYX_KEY_SECRET),
            timeout=(5, 25),
        )
        response.raise_for_status()
        provider_data = response.json()
    except (requests.exceptions.RequestException, ValueError):
        logger.exception('RazorpayX payout reconciliation failed for payout %s', payout.pk)
        return Response(
            {'detail': 'RazorpayX could not confirm the payout status. No local status was changed.'},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    try:
        with transaction.atomic():
            payout = Payout.objects.select_for_update().select_related('payment').get(pk=payout.pk)
            _apply_provider_payout_data(payout, provider_data)
    except ValidationError:
        logger.exception('RazorpayX returned inconsistent details for payout %s', payout.pk)
        return Response(
            {'detail': 'RazorpayX returned inconsistent payout details. The payout remains unchanged.'},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    return Response({'payout': PayoutSerializer(payout).data})


class PaymentListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PaymentSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return Payment.objects.all().select_related('booking', 'agreement')
        return Payment.objects.filter(
            Q(customer=user)
            | Q(booking__worker__user=user)
            | Q(agreement__worker__user=user)
        ).select_related('booking', 'agreement').order_by('-created_at')


class PaymentDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PaymentSerializer
    queryset = Payment.objects.none()

    def get_queryset(self):
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return Payment.objects.all().select_related('booking', 'agreement')
        return Payment.objects.filter(
            Q(customer=user)
            | Q(booking__worker__user=user)
            | Q(agreement__worker__user=user)
        ).select_related('booking', 'agreement')


class PaymentCheckoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not request.user.is_customer:
            raise PermissionDenied('Customer access is required to start a payment.')
        idempotency_key = request.headers.get('Idempotency-Key', '').strip()
        if not idempotency_key or len(idempotency_key) > 128:
            raise ValidationError({
                'Idempotency-Key': 'Provide a key between 1 and 128 characters.'
            })
        serializer = PaymentCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        if not _client_credentials_available():
            return Response(
                {'detail': 'Razorpay checkout is not configured.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        with transaction.atomic():
            if 'booking' in values:
                booking = get_object_or_404(
                    Booking.objects.select_for_update(),
                    pk=values['booking'].pk,
                    customer=request.user,
                )
                if booking.status not in (Booking.Status.CONFIRMED, Booking.Status.COMPLETED):
                    raise ValidationError('A booking must be confirmed before payment.')
                amount = booking.final_amount if booking.final_amount is not None else booking.estimated_amount
                agreement = None
            else:
                agreement = get_object_or_404(
                    WorkAgreement.objects.select_for_update(),
                    pk=values['agreement'].pk,
                    customer=request.user,
                )
                booking = None
                amount = Decimal(str(agreement.terms_snapshot.get('amount', '0')))

            if amount is None or amount <= 0:
                raise ValidationError('The payable amount must be greater than zero.')
            if amount.quantize(Decimal('0.01')) != amount:
                raise ValidationError('The payable amount must use at most two decimal places.')

            existing = Payment.objects.select_for_update().filter(
                idempotency_key=idempotency_key
            ).first()
            if existing:
                same_payable = (
                    existing.customer_id == request.user.id
                    and existing.booking_id == (booking.pk if booking else None)
                    and existing.agreement_id == (agreement.pk if agreement else None)
                    and existing.amount == amount
                )
                if not same_payable:
                    raise ValidationError('This idempotency key was already used for a different payment.')
                if existing.provider_order_id:
                    return Response(_checkout_data(existing))
                raise ValidationError('This idempotent request has no checkout order; use a new key.')

            active_payments = Payment.objects.filter(
                status__in=[Payment.Status.CREATED, Payment.Status.PENDING]
            )
            if booking:
                active_payments = active_payments.filter(booking=booking)
            else:
                active_payments = active_payments.filter(agreement=agreement)
            if active_payments.exists():
                active_payment = active_payments.order_by('-created_at').first()
                if active_payment.provider_order_id:
                    return Response(_checkout_data(active_payment))
                raise ValidationError('A payment order is already being created for this work.')

            payment = Payment.objects.create(
                booking=booking,
                agreement=agreement,
                customer=request.user,
                amount=amount,
                currency='INR',
                method=Payment.Method.RAZORPAY,
                status=Payment.Status.CREATED,
                idempotency_key=idempotency_key,
                receipt=uuid.uuid4().hex,
            )

        try:
            order = razorpay.Client(
                auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
            ).order.create({
                'amount': int(amount * 100),
                'currency': 'INR',
                'receipt': payment.receipt,
            })
        except (razorpay.errors.GatewayError, requests.exceptions.RequestException):
            logger.exception('Razorpay order creation failed for payment %s', payment.pk)
            Payment.objects.filter(pk=payment.pk).update(
                status=Payment.Status.FAILED,
                failure_reason='The payment provider could not create an order.',
                updated_at=timezone.now(),
            )
            return Response(
                {'detail': 'The payment provider could not create an order. Retry with a new idempotency key.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        order_id = order.get('id')
        order_amount = order.get('amount')
        if (
            not order_id
            or str(order.get('currency', '')).upper() != 'INR'
            or str(order_amount) != str(int(amount * 100))
        ):
            Payment.objects.filter(pk=payment.pk).update(
                status=Payment.Status.FAILED,
                failure_reason='The payment provider returned inconsistent order details.',
                updated_at=timezone.now(),
            )
            return Response(
                {'detail': 'The payment provider returned inconsistent order details.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=payment.pk)
            payment.provider_order_id = order_id
            payment.status = Payment.Status.PENDING
            payment.save(update_fields=['provider_order_id', 'status', 'updated_at'])
        return Response(_checkout_data(payment), status=status.HTTP_201_CREATED)


class RazorpayWebhookView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        secret = settings.RAZORPAY_WEBHOOK_SECRET
        if not secret:
            return Response(
                {'detail': 'Razorpay webhook verification is not configured.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        signature = request.headers.get('X-Razorpay-Signature', '')
        if not signature:
            raise ValidationError('A Razorpay webhook signature is required.')
        expected = hmac.new(
            secret.encode('utf-8'),
            request.body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise PermissionDenied('Razorpay webhook signature is invalid.')
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValidationError('Webhook body must be valid JSON.')
        if not isinstance(body, dict):
            raise ValidationError('Webhook body must be a JSON object.')

        event_type = body.get('event')
        payload = body.get('payload') or {}
        if not isinstance(payload, dict):
            raise ValidationError('Webhook payload must be a JSON object.')
        payment_payload = payload.get('payment') or {}
        refund_payload = payload.get('refund') or {}
        if not isinstance(payment_payload, dict) or not isinstance(refund_payload, dict):
            raise ValidationError('Webhook payment and refund data must be JSON objects.')
        payment_entity = payment_payload.get('entity') or {}
        refund_entity = refund_payload.get('entity') or {}
        if not isinstance(payment_entity, dict) or not isinstance(refund_entity, dict):
            raise ValidationError('Webhook payment and refund entities must be JSON objects.')
        if event_type in ('payment.captured', 'payment.failed'):
            order_id = payment_entity.get('order_id')
            provider_payment_id = payment_entity.get('id')
            provider_amount = payment_entity.get('amount')
            provider_currency = payment_entity.get('currency')
            if not order_id or not provider_payment_id:
                raise ValidationError('Payment webhook is missing provider references.')
            payment = Payment.objects.filter(provider_order_id=order_id).first()
            if not payment:
                raise ValidationError('No local payment matches this provider order.')
        elif event_type == 'refund.processed':
            provider_payment_id = refund_entity.get('payment_id')
            if not provider_payment_id or not refund_entity.get('id'):
                raise ValidationError('Refund webhook is missing provider references.')
            payment = Payment.objects.filter(provider_payment_id=provider_payment_id).first()
            if not payment:
                raise ValidationError('No local payment matches this provider refund.')
            provider_amount = refund_entity.get('amount')
            provider_currency = refund_entity.get('currency', payment.currency)
        else:
            return Response({'received': True, 'ignored': True})

        try:
            amount = Decimal(str(provider_amount)) / Decimal('100')
        except (InvalidOperation, ValueError):
            raise ValidationError('Provider event amount is invalid.')
        if provider_currency != payment.currency or amount <= 0:
            raise ValidationError('Provider event amount or currency is invalid.')

        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=payment.pk)
            payload_hash = hashlib.sha256(request.body).hexdigest()
            if PaymentProviderEvent.objects.filter(event_id=payload_hash).exists():
                return Response({'received': True, 'duplicate': True})
            PaymentProviderEvent.objects.create(
                event_id=payload_hash,
                payment=payment,
                event_type=event_type,
                provider_payment_id=provider_payment_id,
                payload_sha256=payload_hash,
            )

            if event_type == 'payment.captured':
                if amount != payment.amount:
                    raise ValidationError('Captured amount does not match the checkout order.')
                if Payment.objects.exclude(pk=payment.pk).filter(
                    provider_payment_id=provider_payment_id
                ).exists():
                    raise ValidationError('Provider payment ID is already assigned to another payment.')
                if (
                    payment.provider_payment_id
                    and payment.provider_payment_id != provider_payment_id
                ):
                    raise ValidationError('This order is already associated with another provider payment.')
                if payment.status in (
                    Payment.Status.REFUNDED,
                    Payment.Status.PARTIALLY_REFUNDED,
                ):
                    if payment.provider_payment_id != provider_payment_id:
                        raise ValidationError('Refunded payment does not match the provider payment.')
                elif payment.status != Payment.Status.SUCCEEDED:
                    payment.status = Payment.Status.SUCCEEDED
                    payment.provider_payment_id = provider_payment_id
                    payment.paid_at = timezone.now()
                    payment.save(update_fields=[
                        'status', 'provider_payment_id', 'paid_at', 'updated_at',
                    ])
                    PaymentLedgerEntry.objects.get_or_create(
                        provider_reference=f'capture:{provider_payment_id}',
                        defaults={
                            'payment': payment,
                            'entry_type': PaymentLedgerEntry.EntryType.CAPTURE,
                            'amount': amount,
                        },
                    )
            elif event_type == 'payment.failed':
                if payment.status not in (
                    Payment.Status.SUCCEEDED,
                    Payment.Status.REFUNDED,
                    Payment.Status.PARTIALLY_REFUNDED,
                ):
                    payment.status = Payment.Status.FAILED
                    payment.failure_reason = str(
                        payment_entity.get('error_description', 'Payment was not captured.')
                    )[:1000]
                    payment.save(update_fields=['status', 'failure_reason', 'updated_at'])
            else:
                refund_reference = f"refund:{refund_entity['id']}"
                if not PaymentLedgerEntry.objects.filter(
                    provider_reference=refund_reference
                ).exists():
                    if amount + payment.refunded_amount > payment.amount:
                        raise ValidationError('Refund amount exceeds the captured payment.')
                    PaymentLedgerEntry.objects.create(
                        payment=payment,
                        entry_type=PaymentLedgerEntry.EntryType.REFUND,
                        amount=amount,
                        provider_reference=refund_reference,
                    )
                    payment.refunded_amount += amount
                    payment.status = (
                        Payment.Status.REFUNDED
                        if payment.refunded_amount == payment.amount
                        else Payment.Status.PARTIALLY_REFUNDED
                    )
                    payment.refunded_at = timezone.now()
                    payment.save(update_fields=[
                        'refunded_amount', 'status', 'refunded_at', 'updated_at',
                    ])

        return Response({'received': True})


class PaymentVerifyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not request.user.is_customer:
            raise PermissionDenied('Customer access is required to verify a payment.')
        serializer = PaymentVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        if not _client_credentials_available():
            return Response(
                {'detail': 'Razorpay payment verification is not configured.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        payment = get_object_or_404(
            Payment,
            provider_order_id=values['razorpay_order_id'],
            customer=request.user,
        )
        client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )
        try:
            client.utility.verify_payment_signature(values)
        except razorpay.errors.SignatureVerificationError:
            raise PermissionDenied('Razorpay payment signature is invalid.')
        try:
            provider_payment = client.payment.fetch(values['razorpay_payment_id'])
        except (razorpay.errors.GatewayError, requests.exceptions.RequestException):
            logger.exception('Razorpay payment verification failed for payment %s', payment.pk)
            return Response(
                {'detail': 'The payment provider could not verify this payment.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if (
            provider_payment.get('id') != values['razorpay_payment_id']
            or provider_payment.get('order_id') != payment.provider_order_id
            or provider_payment.get('currency') != payment.currency
            or str(provider_payment.get('amount')) != str(int(payment.amount * 100))
        ):
            raise ValidationError('Razorpay payment details do not match the checkout order.')

        if provider_payment.get('status') != 'captured':
            return Response(
                {'payment': PaymentSerializer(payment).data, 'provider_status': provider_payment.get('status')},
                status=status.HTTP_202_ACCEPTED,
            )
        if (
            payment.status == Payment.Status.SUCCEEDED
            and payment.provider_payment_id == values['razorpay_payment_id']
        ):
            return Response({'payment': PaymentSerializer(payment).data})
        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=payment.pk)
            if Payment.objects.exclude(pk=payment.pk).filter(
                provider_payment_id=values['razorpay_payment_id']
            ).exists():
                raise ValidationError('Provider payment ID is already assigned to another payment.')
            if (
                payment.provider_payment_id
                and payment.provider_payment_id != values['razorpay_payment_id']
            ):
                raise ValidationError('This order is already associated with another provider payment.')
            if payment.status in (Payment.Status.REFUNDED, Payment.Status.PARTIALLY_REFUNDED):
                if payment.provider_payment_id == values['razorpay_payment_id']:
                    return Response({'payment': PaymentSerializer(payment).data})
                raise ValidationError('A refunded payment cannot be replaced by another provider payment.')
            if (
                payment.status == Payment.Status.SUCCEEDED
                and payment.provider_payment_id == values['razorpay_payment_id']
            ):
                return Response({'payment': PaymentSerializer(payment).data})
            payment.status = Payment.Status.SUCCEEDED
            payment.provider_payment_id = values['razorpay_payment_id']
            payment.paid_at = timezone.now()
            payment.save(update_fields=[
                'status', 'provider_payment_id', 'paid_at', 'updated_at',
            ])
            PaymentLedgerEntry.objects.get_or_create(
                provider_reference=f"capture:{values['razorpay_payment_id']}",
                defaults={
                    'payment': payment,
                    'entry_type': PaymentLedgerEntry.EntryType.CAPTURE,
                    'amount': payment.amount,
                },
            )
        return Response({'payment': PaymentSerializer(payment).data})


class PayoutListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PayoutSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = Payout.objects.select_related('worker__user', 'payment')
        if user.is_staff or user.is_superuser:
            return queryset
        if not user.is_worker:
            raise PermissionDenied('Worker access is required to view payouts.')
        return queryset.filter(worker__user=user)


class PayoutEligibleView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.is_worker or request.user.is_staff or request.user.is_superuser:
            raise PermissionDenied('Worker access is required to view payout eligibility.')
        payments = Payment.objects.filter(
            Q(booking__worker__user=request.user) | Q(agreement__worker__user=request.user),
            status__in=[Payment.Status.SUCCEEDED, Payment.Status.PARTIALLY_REFUNDED],
        ).select_related(
            'booking__worker__user',
            'booking__service',
            'agreement__worker__user',
            'agreement__project',
        )
        results = []
        for payment in payments:
            worker = _worker_for_payment(payment)
            if worker.user_id != request.user.id or not _work_is_customer_approved(payment):
                continue
            available = _payout_amount_available(payment)
            if available < Decimal('1.00'):
                continue
            if payment.booking_id and payment.booking.service_id:
                work_title = payment.booking.service.name
            elif payment.agreement_id and hasattr(payment.agreement, 'project'):
                work_title = payment.agreement.project.title
            else:
                work_title = f'Payment #{payment.pk}'
            results.append({
                'payment_id': payment.pk,
                'work_title': work_title,
                'amount': str(available),
                'currency': payment.currency,
                'can_request': bool(worker.razorpayx_fund_account_id),
            })
        return Response(results)


class PayoutRequestView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not request.user.is_worker or request.user.is_staff or request.user.is_superuser:
            raise PermissionDenied('Worker access is required to request a payout.')
        serializer = PayoutRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment_id = serializer.validated_data['payment_id'].pk

        with transaction.atomic():
            payment = get_object_or_404(
                Payment.objects.select_for_update().select_related(
                    'booking__worker__user',
                    'agreement__worker__user',
                    'agreement__project',
                ),
                pk=payment_id,
            )
            worker = _worker_for_payment(payment)
            if worker.user_id != request.user.id:
                raise PermissionDenied('You can only request a payout for your own completed work.')
            if payment.status not in (
                Payment.Status.SUCCEEDED,
                Payment.Status.PARTIALLY_REFUNDED,
            ):
                raise ValidationError('Only captured payments can be paid out.')
            if not _work_is_customer_approved(payment):
                raise ValidationError('Customer approval of completed work is required before requesting a payout.')
            if not worker.razorpayx_fund_account_id:
                raise ValidationError('Your payout account is not configured. Contact support.')

            amount = _payout_amount_available(payment)
            if amount < Decimal('1.00'):
                raise ValidationError('There is no eligible payout balance for this payment.')
            payout = Payout.objects.create(
                payment=payment,
                worker=worker,
                amount=amount,
                currency=payment.currency,
                provider_fund_account_id=worker.razorpayx_fund_account_id,
            )
        return Response(
            {'payout': PayoutSerializer(payout).data},
            status=status.HTTP_201_CREATED,
        )


class PayoutReviewView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied('Staff access is required to review payouts.')
        serializer = PayoutReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decision = serializer.validated_data['decision']
        reason = serializer.validated_data.get('reason', '').strip()
        if decision == 'reject':
            if not reason:
                raise ValidationError({'reason': 'Provide a reason when rejecting a payout.'})
            with transaction.atomic():
                payout = get_object_or_404(Payout.objects.select_for_update(), pk=pk)
                if payout.status != Payout.Status.REQUESTED:
                    raise ValidationError('Only requested payouts can be rejected.')
                payout.status = Payout.Status.REJECTED
                payout.failure_reason = reason
                payout.reviewed_by = request.user
                payout.reviewed_at = timezone.now()
                payout.save(update_fields=[
                    'status', 'failure_reason', 'reviewed_by', 'reviewed_at', 'updated_at',
                ])
            return Response({'payout': PayoutSerializer(payout).data})

        if not _payout_credentials_available():
            return Response(
                {'detail': 'RazorpayX payout credentials and account number are not configured.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        with transaction.atomic():
            payout = get_object_or_404(
                Payout.objects.select_for_update().select_related('payment'),
                pk=pk,
            )
            if payout.status not in (Payout.Status.REQUESTED, Payout.Status.PROCESSING):
                raise ValidationError('Only pending or approved payouts can be submitted.')
            if payout.status == Payout.Status.PROCESSING and payout.provider_payout_id:
                raise ValidationError('This payout was already submitted; reconcile its provider status instead.')
            if _payout_amount_available(payout.payment, exclude_payout_id=payout.pk) < payout.amount:
                raise ValidationError('The available payment balance changed; this payout cannot be approved.')
            if payout.status == Payout.Status.REQUESTED:
                payout.status = Payout.Status.PROCESSING
                payout.reviewed_by = request.user
                payout.reviewed_at = timezone.now()
                payout.save(update_fields=[
                    'status', 'reviewed_by', 'reviewed_at', 'updated_at',
                ])
        return _submit_razorpayx_payout(payout)


class PayoutReconcileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied('Staff access is required to reconcile payouts.')
        if not (settings.RAZORPAYX_KEY_ID and settings.RAZORPAYX_KEY_SECRET):
            return Response(
                {'detail': 'RazorpayX API credentials are not configured.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        payout = get_object_or_404(
            Payout.objects.select_related('payment'),
            pk=pk,
        )
        if payout.provider_payout_id:
            return _fetch_razorpayx_payout(payout)
        if payout.status != Payout.Status.PROCESSING or not payout.reviewed_by_id:
            raise ValidationError('Only approved, unconfirmed payouts can be safely resubmitted.')
        if not _payout_credentials_available():
            return Response(
                {'detail': 'RazorpayX payout credentials and account number are not configured.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if _payout_amount_available(payout.payment, exclude_payout_id=payout.pk) < payout.amount:
            raise ValidationError('The available payment balance changed; this payout cannot be resubmitted.')
        return _submit_razorpayx_payout(payout)


class RazorpayXPayoutWebhookView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        secret = settings.RAZORPAYX_WEBHOOK_SECRET
        if not secret:
            return Response(
                {'detail': 'RazorpayX webhook verification is not configured.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        signature = request.headers.get('X-Razorpay-Signature', '')
        if not signature:
            raise ValidationError('A RazorpayX webhook signature is required.')
        expected = hmac.new(secret.encode('utf-8'), request.body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise PermissionDenied('RazorpayX webhook signature is invalid.')
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValidationError('Webhook body must be valid JSON.')
        if not isinstance(body, dict):
            raise ValidationError('Webhook body must be a JSON object.')
        event_type = body.get('event')
        if not isinstance(event_type, str) or not event_type.startswith('payout.'):
            return Response({'received': True, 'ignored': True})
        payload = body.get('payload') or {}
        if not isinstance(payload, dict):
            raise ValidationError('Webhook payload must be a JSON object.')
        payout_payload = payload.get('payout') or {}
        if not isinstance(payout_payload, dict):
            raise ValidationError('Webhook payout data must be a JSON object.')
        provider_data = payout_payload.get('entity') or {}
        if not isinstance(provider_data, dict):
            raise ValidationError('Webhook payout entity must be a JSON object.')
        provider_id = provider_data.get('id')
        reference_id = provider_data.get('reference_id')
        if not provider_id and not reference_id:
            raise ValidationError('Payout webhook is missing provider references.')
        payout = Payout.objects.filter(provider_payout_id=provider_id).first() if provider_id else None
        if not payout and reference_id:
            payout = Payout.objects.filter(reference_id=reference_id).first()
        if not payout:
            raise ValidationError('No local payout matches this provider event.')

        payload_hash = hashlib.sha256(request.body).hexdigest()
        with transaction.atomic():
            payout = Payout.objects.select_for_update().select_related('payment').get(pk=payout.pk)
            if PayoutProviderEvent.objects.filter(event_id=payload_hash).exists():
                return Response({'received': True, 'duplicate': True})
            _apply_provider_payout_data(payout, provider_data)
            PayoutProviderEvent.objects.create(
                event_id=payload_hash,
                payout=payout,
                event_type=event_type,
                payload_sha256=payload_hash,
            )
        return Response({'received': True})
