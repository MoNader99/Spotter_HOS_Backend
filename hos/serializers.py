from rest_framework import serializers
from .models import Trip, DrivingLog, DailyLogSheet
from django.contrib.auth import get_user_model

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']

class DrivingLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = DrivingLog
        fields = '__all__'

class DailyLogSheetSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyLogSheet
        fields = '__all__'

class TripSerializer(serializers.ModelSerializer):
    logs = DrivingLogSerializer(many=True, read_only=True)
    daily_logs = DailyLogSheetSerializer(many=True, read_only=True)
    driver = UserSerializer(read_only=True)

    class Meta:
        model = Trip
        fields = '__all__'
        extra_kwargs = {
            'driver': {'required': False},  # Make driver optional
            'current_cycle_used': {'required': False}  # Also optional
        }

class SimplifiedTripSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trip
        fields = ['id', 'status', 'pickup_location', 'dropoff_location', 'created_at']