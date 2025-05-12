from django.utils import timezone
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator

User = get_user_model()

class Trip(models.Model):
    TRIP_STATUS_CHOICES = [
        ('NOT_STARTED', 'Not Started'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
    ]
    
    driver = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='trips')
    current_location = models.CharField(max_length=255, null=True, blank=True)
    pickup_location = models.CharField(max_length=255)
    dropoff_location = models.CharField(max_length=255)
    pickup_coordinates = models.JSONField(null=True, blank=True)  # Store as [lat, lng]
    dropoff_coordinates = models.JSONField(null=True, blank=True)  # Store as [lat, lng]
    current_cycle_used = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(70)], 
        null=True, blank=True
    )
    total_distance = models.FloatField(null=True, blank=True)
    estimated_driving_time = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=TRIP_STATUS_CHOICES, default='NOT_STARTED')
    auto_assign = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.pickup_location} ➔ {self.dropoff_location} ({self.get_status_display()})"

class DrivingLog(models.Model):
    STATUS_CHOICES = [
        ('OFF', 'Off Duty'),
        ('SB', 'Sleeper Berth'),
        ('D', 'Driving'),
        ('ON', 'On Duty (Not Driving)'),
    ]
    
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='logs')
    status = models.CharField(max_length=3, choices=STATUS_CHOICES)
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=255)
    remarks = models.TextField()
    date = models.DateField(default=timezone.now)

    class Meta:
        ordering = ['date', 'start_time']  # <-- ADD THIS

    def __str__(self):
        return f"{self.get_status_display()} at {self.location} on {self.date}"

    def save(self, *args, **kwargs):
        if self.start_time:
            self.date = self.start_time.date()
        super().save(*args, **kwargs)

class DailyLogSheet(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='daily_logs')
    date = models.DateField()
    driving_hours = models.FloatField(default=0)
    on_duty_hours = models.FloatField(default=0)
    off_duty_hours = models.FloatField(default=0)
    sleeper_berth_hours = models.FloatField(default=0)

    def __str__(self):
        return f"Log for {self.date}"
