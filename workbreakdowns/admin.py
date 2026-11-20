from django.contrib import admin

from .models import TaskTemplate, WorkBreakdown, WorkBreakdownRevision, WorkBreakdownTask


class WorkBreakdownTaskInline(admin.TabularInline):
    model = WorkBreakdownTask
    extra = 0
    readonly_fields = ('title', 'description', 'sort_order', 'estimated_days', 'created_at', 'updated_at')

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TaskTemplate)
class TaskTemplateAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'service', 'sort_order', 'is_active')
    list_filter = ('category', 'service', 'is_active')
    search_fields = ('title', 'description')
    ordering = ('category', 'sort_order', 'id')


@admin.register(WorkBreakdown)
class WorkBreakdownAdmin(admin.ModelAdmin):
    list_display = ('job_request', 'customer', 'status', 'revision_number', 'approved_revision')
    list_filter = ('status',)
    search_fields = ('job_request__title', 'customer__email', 'customer__full_name')
    readonly_fields = (
        'job_request', 'customer', 'status', 'revision_number', 'approved_revision',
        'approved_at', 'created_at', 'updated_at',
    )
    inlines = (WorkBreakdownTaskInline,)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WorkBreakdownRevision)
class WorkBreakdownRevisionAdmin(admin.ModelAdmin):
    list_display = ('breakdown', 'revision_number', 'is_approved', 'created_by', 'created_at')
    list_filter = ('is_approved',)
    readonly_fields = ('breakdown', 'revision_number', 'snapshot', 'created_by', 'is_approved', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
