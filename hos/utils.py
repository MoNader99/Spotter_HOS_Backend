from datetime import timedelta
from django.utils import timezone
from hos.models import Trip
import math
import requests
from Spotter_HOS import settings

class HOSCalculator:
    MAX_DRIVING_HOURS = 11
    MAX_DUTY_HOURS = 14
    MAX_CYCLE_HOURS = 70
    CYCLE_DAYS = 8
    MIN_BREAK_DURATION = timedelta(minutes=30)
    MIN_OFF_DUTY = timedelta(hours=10)
    
    @classmethod
    def calculate_available_hours(cls, driver=None):
        """Calculate remaining available hours"""
        if not driver:
            return {
                'remaining_driving_hours': cls.MAX_DRIVING_HOURS,
                'remaining_duty_hours': cls.MAX_DUTY_HOURS,
                'remaining_cycle_hours': cls.MAX_CYCLE_HOURS,
                'cycle_reset_hours': 0
            }
    
    @classmethod
    def check_break_requirement(cls, logs):
        """Check if 30-minute break is needed"""
        driving_hours = sum(
            (log.end_time - log.start_time).total_seconds() / 3600
            for log in logs
            if log.status == 'D'
        )
        return driving_hours >= 8

def calculate_trip_info(trip):
    pickup_coords = geocode_location(trip.pickup_location)
    dropoff_coords = geocode_location(trip.dropoff_location)

    if pickup_coords and dropoff_coords:
        directions_url = "https://api.openrouteservice.org/v2/directions/driving-car"
        headers = {
            'Authorization': settings.OPENROUTESERVICE_API_KEY,
            'Content-Type': 'application/json',
        }
        body = {
            "coordinates": [
                [pickup_coords[1], pickup_coords[0]],
                [dropoff_coords[1], dropoff_coords[0]]
            ]
        }

        response = requests.post(directions_url, json=body, headers=headers)

        if response.status_code == 200:
            data = response.json()
            if 'routes' in data and data['routes']:
                route_summary = data['routes'][0]['summary']
                total_distance_miles = route_summary['distance'] / 1000 * 0.621371
                total_duration_hours = route_summary['duration'] / 3600

                # Add 1 hour pickup + 1 hour drop-off
                total_duration_hours += 2

                # Fuel stops every 1000 miles
                fuel_stops = math.floor(total_distance_miles / 1000)

                # Update the trip fields
                trip.total_distance = float(f"{total_distance_miles:.2f}")
                trip.estimated_driving_time = float(f"{total_duration_hours:.2f}")
                trip.save()

                return {
                    'total_distance_miles': f"{total_distance_miles:.2f}",
                    'estimated_total_time_hours': f"{total_duration_hours:.2f}",
                    'fuel_stops': fuel_stops,
                }
    return None

def geocode_location(address):
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        'q': address,
        'format': 'json',
        'limit': 1
    }
    response = requests.get(url, params=params, headers={'User-Agent': 'your-app-name'})

    if response.status_code == 200:
        data = response.json()
        if data:
            lat = float(data[0]['lat'])
            lon = float(data[0]['lon'])
            return (lat, lon)
    return None