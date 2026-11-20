from django.conf import settings
from django.db import models


class Review(models.Model):
    booking = models.OneToOneField(
        'bookings.Booking',
        on_delete=models.PROTECT,
        related_name='review',
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='reviews',
    )
    worker = models.ForeignKey(
        'profiles.WorkerProfile',
        on_delete=models.PROTECT,
        related_name='reviews',
    )
    rating = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=120, blank=True)
    comment = models.TextField(blank=True)
    is_public = models.BooleanField(default=True)
    worker_reply = models.TextField(blank=True)
    worker_replied_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['worker', 'is_public', 'created_at'])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=1) & models.Q(rating__lte=5),
                name='review_rating_between_1_and_5',
            ),
        ]

    def __str__(self):
        return f'{self.rating}/5 review for {self.worker}'
