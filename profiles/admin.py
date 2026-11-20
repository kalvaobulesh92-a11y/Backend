from django.contrib import admin
from .models import CustomerProfile, WorkerProfile


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'gender', 'date_of_birth', 'created_at')
    list_filter = ('gender',)
    search_fields = ('user__email', 'user__username', 'user__full_name', 'user__phone')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(WorkerProfile)
class WorkerProfileAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'experience_years', 'is_available', 'verification_status',
        'average_rating', 'total_bookings',
    )
    list_filter = ('verification_status', 'is_available', 'pricing_type')
    search_fields = ('user__email', 'user__username', 'user__full_name', 'user__phone', 'bio')
    readonly_fields = (
        'average_rating', 'total_reviews', 'total_bookings', 'created_at', 'updated_at',
    )
