from django.urls import path

from locations.api.views import NearbyWorkerView

urlpatterns = [
    path('nearby-workers/', NearbyWorkerView.as_view(), name='nearby-workers'),
]
