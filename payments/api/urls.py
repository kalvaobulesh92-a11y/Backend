from django.urls import path

from .views import (
    PaymentCheckoutView,
    PaymentDetailView,
    PaymentListView,
    PaymentVerifyView,
    PayoutEligibleView,
    PayoutListView,
    PayoutReconcileView,
    PayoutRequestView,
    PayoutReviewView,
    RazorpayWebhookView,
    RazorpayXPayoutWebhookView,
)

urlpatterns = [
    path('', PaymentListView.as_view(), name='payment-list'),
    path('checkout/', PaymentCheckoutView.as_view(), name='payment-checkout'),
    path('verify/', PaymentVerifyView.as_view(), name='payment-verify'),
    path('payouts/', PayoutListView.as_view(), name='payout-list'),
    path('payouts/eligible/', PayoutEligibleView.as_view(), name='payout-eligible'),
    path('payouts/request/', PayoutRequestView.as_view(), name='payout-request'),
    path('payouts/<int:pk>/review/', PayoutReviewView.as_view(), name='payout-review'),
    path('payouts/<int:pk>/reconcile/', PayoutReconcileView.as_view(), name='payout-reconcile'),
    path('<int:pk>/', PaymentDetailView.as_view(), name='payment-detail'),
    path('webhooks/razorpay/', RazorpayWebhookView.as_view(), name='razorpay-webhook'),
    path('webhooks/razorpayx/', RazorpayXPayoutWebhookView.as_view(), name='razorpayx-payout-webhook'),
]
