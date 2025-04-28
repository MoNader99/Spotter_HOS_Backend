from django.urls import re_path
from . import consumers
 
websocket_urlpatterns = [
    re_path(r'ws/trips/(?P<trip_id>\d+)/$', consumers.TripConsumer.as_asgi()),
    re_path(r'ws/trips/$', consumers.TripsConsumer.as_asgi()),
] 