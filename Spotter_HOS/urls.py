from django.contrib import admin
from django.urls import path, re_path
from hos.views import (
    AddLogView, CompleteTripView, DailyLogView, TripCreateView, 
    TripDetailView, TripRouteView, TripDailyLogsView, DailyLogGenerator,
    AssignTripView, AvailableTripsView, DriverTripsView, AllTripsView,
    DriverAssignedTripsView
)
from hos.auth import UserRegistrationView, UserLoginView, UserProfileView
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Authentication endpoints
    path('api/auth/register/', UserRegistrationView.as_view(), name='user-register'),
    path('api/auth/login/', UserLoginView.as_view(), name='user-login'),
    path('api/auth/profile/', UserProfileView.as_view(), name='user-profile'),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    
    # Trip management endpoints
    re_path(r'^api/trips/?$', TripCreateView.as_view(), name='trip-create'),
    re_path(r'^api/trips/all/?$', AllTripsView.as_view(), name='all-trips'),
    re_path(r'^api/trips/available/?$', AvailableTripsView.as_view(), name='available-trips'),
    re_path(r'^api/trips/my-trips/?$', DriverAssignedTripsView.as_view(), name='driver-assigned-trips'),
    re_path(r'^api/trips/(?P<pk>\d+)/$', TripDetailView.as_view(), name='trip-detail'),
    re_path(r'^api/trips/(?P<pk>\d+)/route/$', TripRouteView.as_view(), name='trip-route'),
    re_path(r'^api/trips/(?P<pk>\d+)/complete/$', CompleteTripView.as_view(), name='trip-complete'),
    re_path(r'^api/trips/(?P<pk>\d+)/assign/$', AssignTripView.as_view(), name='assign-trip'),
    re_path(r'^api/trips/(?P<pk>\d+)/daily-logs/$', TripDailyLogsView.as_view(), name='trip-daily-logs'),
    re_path(r'^api/trips/(?P<pk>\d+)/add-log/$', AddLogView.as_view(), name='add-log'),
    re_path(r'^api/trips/(?P<pk>\d+)/daily-logs/(?P<date>\d{4}-\d{2}-\d{2})/$', 
            DailyLogView.as_view(), 
            name='daily-logs'),
    re_path(r'^api/trips/(?P<pk>\d+)/generate-daily-log/$', 
            DailyLogGenerator.as_view(), 
            name='generate-daily-log'),
]