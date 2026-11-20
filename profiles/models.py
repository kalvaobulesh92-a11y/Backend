from django.conf import settings
from django.db import models
from categories.models import ServiceCategory
from services.models import Service


class CustomerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='customer_profile')
    gender = models.CharField(max_length=20, blank=True, choices=[
        ('male', 'Male'), ('female', 'Female'), ('other', 'Other'), ('prefer_not', 'Prefer not to say')
    ])
    date_of_birth = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Customer: {self.user.full_name}"


class Address(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='addresses')
    label = models.CharField(max_length=50, default='Home')  # Home, Work, Other
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True)
    locality = models.CharField(max_length=100)  # Kukatpally, etc.
    city = models.CharField(max_length=100, default='Hyderabad')
    state = models.CharField(max_length=100, default='Telangana')
    pincode = models.CharField(max_length=10)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'addresses'
        ordering = ['-is_default', '-created_at']

    def __str__(self):
        return f"{self.label} - {self.locality}, {self.city}"


class WorkerProfile(models.Model):
    VERIFICATION_STATUS = [
        ('unverified', 'Unverified'),
        ('pending', 'Pending Review'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
    ]
    PRICING_TYPE = [
        ('fixed', 'Fixed'),
        ('hourly', 'Hourly'),
        ('starting_from', 'Starting From'),
        ('negotiable', 'Negotiable'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='worker_profile')
    bio = models.TextField(blank=True)
    experience_years = models.PositiveIntegerField(default=0)
    starting_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    pricing_type = models.CharField(max_length=20, choices=PRICING_TYPE, default='starting_from')
    gender = models.CharField(max_length=20, blank=True)
    is_available = models.BooleanField(default=True)
    verification_status = models.CharField(max_length=20, choices=VERIFICATION_STATUS, default='unverified')
    razorpayx_fund_account_id = models.CharField(max_length=100, blank=True)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.00)
    total_reviews = models.PositiveIntegerField(default=0)
    total_bookings = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Worker: {self.user.full_name}"


class WorkerSkill(models.Model):
    worker = models.ForeignKey(WorkerProfile, on_delete=models.CASCADE, related_name='skills')
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('worker', 'name')

    def __str__(self):
        return self.name


class WorkerService(models.Model):
    worker = models.ForeignKey(WorkerProfile, on_delete=models.CASCADE, related_name='worker_services')
    category = models.ForeignKey(ServiceCategory, on_delete=models.CASCADE)
    service = models.ForeignKey(Service, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('worker', 'category', 'service')

    def __str__(self):
        return f"{self.worker.user.full_name} - {self.category.name}"


class WorkerServiceArea(models.Model):
    worker = models.ForeignKey(WorkerProfile, on_delete=models.CASCADE, related_name='service_areas')
    locality = models.CharField(max_length=100)
    city = models.CharField(max_length=100, default='Hyderabad')
    state = models.CharField(max_length=100, default='Telangana')
    pincode = models.CharField(max_length=10, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    radius_km = models.PositiveIntegerField(default=5, help_text="Service radius in km")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('worker', 'locality', 'city')

    def __str__(self):
        return f"{self.worker.user.full_name} serves {self.locality}"


class Portfolio(models.Model):
    worker = models.ForeignKey(WorkerProfile, on_delete=models.CASCADE, related_name='portfolio_items')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='portfolio/')
    is_before_after = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class Availability(models.Model):
    DAYS = [
        (0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'),
        (3, 'Thursday'), (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday'),
    ]
    worker = models.ForeignKey(WorkerProfile, on_delete=models.CASCADE, related_name='availability_slots')
    day_of_week = models.IntegerField(choices=DAYS)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_available = models.BooleanField(default=True)

    class Meta:
        unique_together = ('worker', 'day_of_week', 'start_time')
        verbose_name_plural = 'availabilities'

    def __str__(self):
        return f"{self.worker.user.full_name} - {self.get_day_of_week_display()}"
