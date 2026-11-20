from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/accounts/', include('accounts.api.urls')),
    path('api/categories/', include('categories.api.urls')),
    path('api/services/', include('services.api.urls')),
    path('api/profiles/', include('profiles.api.urls')),
    path('api/locations/', include('locations.api.urls')),
    path('api/bookings/', include('bookings.api.urls')),
    path('api/quotations/', include('quotations.api.urls')),
    path('api/workbreakdowns/', include('workbreakdowns.api.urls')),
    path('api/pricing/', include('pricing.api.urls')),
    path('api/payments/', include('payments.api.urls')),
    path('api/projects/', include('projects.api.urls')),
    path('api/enquiries/', include('enquiries.api.urls')),
    path('api/reviews/', include('reviews.api.urls')),
    path('api/analytics/', include('analytics.api.urls')),
    path('api/favourites/', include('favourites.api.urls')),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
