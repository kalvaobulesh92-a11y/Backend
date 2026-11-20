from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'username', 'full_name', 'phone', 'is_customer', 'is_worker', 'is_staff', 'is_active', 'date_joined')
    list_filter = ('is_customer', 'is_worker', 'is_staff', 'is_active', 'is_email_verified')
    search_fields = ('email', 'username', 'full_name', 'phone')
    ordering = ('-date_joined',)
    fieldsets = (
        (None, {'fields': ('email', 'username', 'password')}),
        ('Personal info', {'fields': ('full_name', 'phone', 'profile_picture')}),
        ('Roles', {'fields': ('is_customer', 'is_worker')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Verification', {'fields': ('is_email_verified', 'is_phone_verified')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'phone', 'full_name', 'password1', 'password2', 'is_customer', 'is_worker'),
        }),
    )
