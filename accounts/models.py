import re

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, email, phone, password=None, **extra_fields):
        if not email:
            raise ValueError('Users must have an email address')
        if not phone:
            raise ValueError('Users must have a phone number')

        email = self.normalize_email(email)
        username = extra_fields.pop('username', None)
        if not username:
            base_username = re.sub(r'[^a-z0-9._-]', '', email.split('@', 1)[0].lower())[:140] or 'user'
            username = base_username
            suffix = 1
            while self.model.objects.filter(username__iexact=username).exists():
                username = f'{base_username[:140]}-{suffix}'
                suffix += 1

        user = self.model(email=email, phone=phone, username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, phone, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('is_customer', False)
        extra_fields.setdefault('is_worker', False)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, phone, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model for KaamConnect.
    One account can act as both Customer and Worker.
    """
    email = models.EmailField(unique=True, max_length=255)
    username = models.CharField(max_length=150, unique=True)
    phone = models.CharField(max_length=15, unique=True)
    full_name = models.CharField(max_length=150)
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True)

    # Role flags – a user can be both customer and worker
    is_customer = models.BooleanField(default=True)
    is_worker = models.BooleanField(default=False)

    # Status
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)
    is_phone_verified = models.BooleanField(default=False)

    # Timestamps
    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'phone', 'full_name']

    class Meta:
        verbose_name = 'user'
        verbose_name_plural = 'users'
        ordering = ['-date_joined']

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    @property
    def is_admin(self):
        return self.is_staff or self.is_superuser
