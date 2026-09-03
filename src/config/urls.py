"""
URL configuration for the ComplyChat project.

    /           the page a visitor lands on
    /healthz    liveness probe — deliberately touches nothing but the process
    /api/       the question-answering endpoint

The DRF DefaultRouter that used to sit here had no viewsets registered, but a
DefaultRouter always claims '^$' for its api-root view. Since it came first in
urlpatterns it would have shadowed the '' route below, and the landing page
would have silently served an empty API root instead.
"""
from django.urls import path, include

from app.views import healthz, index

urlpatterns = [
    path('', index, name='index'),
    path('healthz', healthz, name='healthz'),
    path('api/', include('app.urls')),
]
