from django.contrib import admin
from django.urls import path, re_path
from hos.views import AddLogView, CompleteTripView, DailyLogView, TripCreateView, TripDetailView, TripRouteView, TripDailyLogsView, DailyLogGenerator

urlpatterns = [
    path('admin/', admin.site.urls),
    re_path(r'^api/trips/?$', TripCreateView.as_view(), name='trip-create'),
    re_path(r'^api/trips/(?P<pk>\d+)/$', TripDetailView.as_view(), name='trip-detail'),
    re_path(r'^api/trips/(?P<pk>\d+)/route/$', TripRouteView.as_view(), name='trip-route'),
    re_path(r'^api/trips/(?P<pk>\d+)/complete/$', CompleteTripView.as_view(), name='trip-complete'),
    re_path(r'^api/trips/(?P<pk>\d+)/daily-logs/$', TripDailyLogsView.as_view(), name='trip-daily-logs'),
    re_path(r'^api/trips/(?P<pk>\d+)/add-log/$', AddLogView.as_view(), name='add-log'),
    re_path(r'^api/trips/(?P<pk>\d+)/daily-logs/(?P<date>\d{4}-\d{2}-\d{2})/$', 
            DailyLogView.as_view(), 
            name='daily-logs'),
    re_path(r'^api/trips/(?P<pk>\d+)/generate-daily-log/$', 
            DailyLogGenerator.as_view(), 
            name='generate-daily-log'),
]