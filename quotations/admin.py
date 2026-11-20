from django.contrib import admin
from .models import JobRequest, Quotation, QuotationRevision, WorkAgreement


@admin.register(JobRequest)
class JobRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'customer', 'category', 'status', 'created_at')
    list_filter = ('status', 'category', 'created_at')
    search_fields = ('title', 'description', 'customer__email', 'customer__full_name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = ('id', 'job_request', 'worker', 'amount', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('job_request__title', 'worker__user__email', 'worker__user__full_name')
    readonly_fields = ('accepted_at', 'created_at', 'updated_at')


@admin.register(QuotationRevision)
class QuotationRevisionAdmin(admin.ModelAdmin):
    list_display = ('id', 'quotation', 'proposed_by', 'amount', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    readonly_fields = tuple(field.name for field in QuotationRevision._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WorkAgreement)
class WorkAgreementAdmin(admin.ModelAdmin):
    list_display = ('id', 'job_request', 'quotation', 'customer', 'worker', 'accepted_at')
    readonly_fields = tuple(field.name for field in WorkAgreement._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_staff

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
