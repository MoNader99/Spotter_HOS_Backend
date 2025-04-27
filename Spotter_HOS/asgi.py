"""
ASGI config for Spotter_HOS project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.urls import re_path
from hos.consumers import TripConsumer, LogConsumer

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Spotter_HOS.settings')

websocket_urlpatterns = [
    re_path(r'ws/trips/$', TripConsumer.as_asgi()),
    re_path(r'ws/trips/(?P<trip_id>\w+)/$', TripConsumer.as_asgi()),
    re_path(r'ws/trips/(?P<trip_id>\w+)/logs/$', LogConsumer.as_asgi()),
]

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            websocket_urlpatterns
        )
    ),
})
