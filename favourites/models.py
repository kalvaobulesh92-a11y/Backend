from django.conf import settings
from django.db import models


class Favourite(models.Model):
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='favourites',
    )
    worker = models.ForeignKey(
        'profiles.WorkerProfile',
        on_delete=models.CASCADE,
        related_name='favourited_by',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['customer', 'worker'], name='unique_customer_favourite_worker'),
        ]

    def __str__(self):
        return f'{self.customer} favourites {self.worker}'
