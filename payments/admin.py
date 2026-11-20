from django.contrib import admin

from .models import (
    Payment,
    PaymentLedgerEntry,
    PaymentProviderEvent,
    Payout,
    PayoutProviderEvent,
)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'booking', 'agreement', 'amount', 'currency', 'status', 'method')
    list_filter = ('status', 'method', 'currency')
    search_fields = ('provider_order_id', 'provider_payment_id', 'receipt', 'customer__email')
    readonly_fields = (
        'booking', 'agreement', 'customer', 'amount', 'currency', 'method', 'status',
        'provider_order_id', 'provider_payment_id', 'idempotency_key', 'receipt',
        'refunded_amount', 'failure_reason', 'paid_at', 'refunded_at', 'created_at', 'updated_at',
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PaymentProviderEvent)
class PaymentProviderEventAdmin(admin.ModelAdmin):
    list_display = ('event_id', 'event_type', 'payment', 'provider_payment_id', 'created_at')
    readonly_fields = ('event_id', 'payment', 'event_type', 'provider_payment_id', 'payload_sha256', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PaymentLedgerEntry)
class PaymentLedgerEntryAdmin(admin.ModelAdmin):
    list_display = ('payment', 'entry_type', 'amount', 'provider_reference', 'created_at')
    readonly_fields = ('payment', 'entry_type', 'amount', 'provider_reference', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'worker', 'payment', 'amount', 'currency', 'status',
        'provider_status', 'requested_at',
    )
    list_filter = ('status', 'provider_status', 'currency')
    search_fields = (
        'worker__user__email', 'provider_payout_id', 'reference_id', 'utr',
    )
    readonly_fields = [field.name for field in Payout._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PayoutProviderEvent)
class PayoutProviderEventAdmin(admin.ModelAdmin):
    list_display = ('event_id', 'event_type', 'payout', 'created_at')
    readonly_fields = ('event_id', 'payout', 'event_type', 'payload_sha256', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
