import math
import requests
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView
from Spotter_HOS import settings
from .models import Trip, DrivingLog, DailyLogSheet
from .serializers import DailyLogSheetSerializer, DrivingLogSerializer, TripSerializer
from rest_framework import status
from datetime import datetime
from django.utils import timezone
from .utils import HOSCalculator

class TripCreateView(generics.CreateAPIView):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer
    permission_classes = []

    def perform_create(self, serializer):
        trip = serializer.save()
        _calculate_trip_info(trip)
        
    def geocode_location(self, address):
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
                return (lat, lon)  # return (lat, lon)
        return None

class TripRouteView(APIView):
    permission_classes = []

    def get(self, request, pk):
        try:
            trip = Trip.objects.get(pk=pk)

            pickup_coords = self.geocode_location(trip.pickup_location)
            dropoff_coords = self.geocode_location(trip.dropoff_location)

            if not pickup_coords or not dropoff_coords:
                return Response({"error": "Could not geocode locations"}, status=400)

            directions_url = "https://api.openrouteservice.org/v2/directions/driving-car"
            headers = {
                'Authorization': settings.OPENROUTESERVICE_API_KEY,
                'Content-Type': 'application/json',
            }
            body = {
                "coordinates": [
                    [pickup_coords[1], pickup_coords[0]],  # [lng, lat]
                    [dropoff_coords[1], dropoff_coords[0]]
                ]
            }

            response = requests.post(directions_url, json=body, headers=headers)

            if response.status_code != 200:
                return Response({"error": "Error fetching route"}, status=400)

            data = response.json()

            if 'routes' not in data or not data['routes']:
                return Response({"error": "No routes found"}, status=400)

            route_info = data['routes'][0]
            summary = route_info['summary']
            steps = route_info['segments'][0]['steps']

            total_distance_miles = summary['distance'] / 1000 * 0.621371  # meters ➔ miles
            total_duration_hours = summary['duration'] / 3600  # seconds ➔ hours

            # Add 1 hour pickup and 1 hour drop-off
            total_duration_hours += 2

            # Fuel stops every 1000 miles
            fuel_stops = math.floor(total_distance_miles / 1000)

            route_steps = []
            miles_counter = 0

            for step in steps:
                miles = step['distance'] / 1000 * 0.621371
                duration_hours = step['duration'] / 3600

                route_steps.append({
                    'instruction': step['instruction'],
                    'distance_miles': f"{miles:.2f}",
                    'estimated_time_hours': f"{duration_hours:.2f}",
                })

                miles_counter += miles
                if miles_counter >= 1000:
                    # Add fuel stop
                    route_steps.append({
                        'instruction': 'Recommended fuel stop',
                        'distance_miles': '0.00',
                        'estimated_time_hours': '1.00',  # Assume 1 hour fuel stop
                    })
                    miles_counter = 0  # reset counter after fuel stop

            route_response = {
                'trip_id': trip.id,
                'pickup_location': trip.pickup_location,
                'dropoff_location': trip.dropoff_location,
                'total_distance_miles': f"{total_distance_miles:.2f}",
                'estimated_total_time_hours': f"{total_duration_hours:.2f}",
                'fuel_stops': fuel_stops,
                'steps': route_steps,
            }

            return Response(route_response, status=200)

        except Trip.DoesNotExist:
            return Response({"error": "Trip not found"}, status=404)

    def geocode_location(self, address):
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
    
class TripDetailView(generics.RetrieveAPIView):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer
    permission_classes = []

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        _calculate_trip_info(instance)  # Recalculate when fetching, keep consistent
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

class CompleteTripView(APIView):
    permission_classes = []

    def post(self, request, pk):
        try:
            trip = Trip.objects.get(pk=pk)

            if trip.status == 'COMPLETED':
                return Response({"message": "Trip already completed."}, status=status.HTTP_200_OK)

            trip.status = 'COMPLETED'
            trip.save()
            return Response({"message": "Trip marked as completed."}, status=status.HTTP_200_OK)

        except Trip.DoesNotExist:
            return Response({"error": "Trip not found."}, status=status.HTTP_404_NOT_FOUND)

class TripDailyLogsView(APIView):
    permission_classes = []
    
    def get(self, request, pk):
        trip = Trip.objects.get(pk=pk)
        daily_logs = trip.daily_logs.all()
        logs_data = DailyLogSheetSerializer(daily_logs, many=True).data
        return Response({
            "trip_id": trip.id,
            "logs": logs_data
        })

class AddLogView(APIView):
    permission_classes = []

    def post(self, request, pk):
        try:
            trip = Trip.objects.get(pk=pk)

            if trip.status == 'COMPLETED':
                return Response({"error": "Cannot add logs to completed trips"}, status=status.HTTP_400_BAD_REQUEST)

            serializer = DrivingLogSerializer(data=request.data)
            if serializer.is_valid():
                log = serializer.save(trip=trip)  # attach trip directly here

                if 'location' in request.data:
                    trip.current_location = request.data['location']
                    if trip.status == 'NOT_STARTED':
                        trip.status = 'IN_PROGRESS'
                    trip.save()

                return Response(serializer.data, status=status.HTTP_201_CREATED)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except Trip.DoesNotExist:
            return Response({"error": "Trip not found"}, status=status.HTTP_404_NOT_FOUND)

    permission_classes = []
    
    def post(self, request, pk):
        try:
            trip = Trip.objects.get(pk=pk)
            
            # Check if trip is completed
            if trip.status == 'COMPLETED':
                return Response(
                    {"error": "Cannot add logs to completed trips"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Update trip status to in progress if it's the first log
            if trip.status == 'NOT_STARTED':
                trip.status = 'IN_PROGRESS'
                trip.save()
            
            serializer = DrivingLogSerializer(data=request.data)
            if serializer.is_valid():
                log = serializer.save(trip=trip)
                
                # Update current location if provided
                if 'location' in request.data:
                    trip.current_location = request.data['location']
                    trip.save()
                
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        except Trip.DoesNotExist:
            return Response(
                {"error": "Trip not found"},
                status=status.HTTP_404_NOT_FOUND
            )

class DailyLogView(APIView):
    permission_classes = []
    
    def get(self, request, pk, date):
        try:
            date_obj = datetime.strptime(date, '%Y-%m-%d').date()
            logs = DrivingLog.objects.filter(trip_id=pk, date=date_obj)
            
            if not logs.exists():
                return Response(
                    {"error": "No logs found for this date"},
                    status=status.HTTP_404_NOT_FOUND
                )
                
            driving_hours = sum((log.end_time - log.start_time).total_seconds() / 3600 for log in logs if log.status == 'D')
            on_duty_hours = sum((log.end_time - log.start_time).total_seconds() / 3600 for log in logs if log.status == 'ON')
            off_duty_hours = sum((log.end_time - log.start_time).total_seconds() / 3600 for log in logs if log.status == 'OFF')
            sleeper_berth_hours = sum((log.end_time - log.start_time).total_seconds() / 3600 for log in logs if log.status == 'SB')

            
            # Calculate totals for the day
            totals = {
                'driving_hours': driving_hours,
                'on_duty_hours': on_duty_hours,
                'off_duty_hours': off_duty_hours,
                'sleeper_berth_hours': sleeper_berth_hours,
            }
            
            response = {
                'date': date,
                'trip_id': pk,
                'logs': DrivingLogSerializer(logs, many=True).data,
                'totals': totals
            }
            
            return Response(response)
            
        except ValueError:
            return Response(
                {"error": "Invalid date format. Use YYYY-MM-DD"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
class DailyLogGenerator(APIView):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer
    permission_classes = []

    def perform_create(self, serializer):
        trip = serializer.save()
        self.calculate_route_info(trip)

    def calculate_route_info(self, trip):
        pickup_coords = self.geocode_location(trip.pickup_location)
        dropoff_coords = self.geocode_location(trip.dropoff_location)

        if pickup_coords and dropoff_coords:
            directions_url = "https://api.openrouteservice.org/v2/directions/driving-car"
            headers = {
                'Authorization': settings.OPENROUTESERVICE_API_KEY,
                'Content-Type': 'application/json',
            }
            body = {
                "coordinates": [
                    [pickup_coords[1], pickup_coords[0]],  # [lng, lat]
                    [dropoff_coords[1], dropoff_coords[0]]
                ]
            }

            response = requests.post(directions_url, json=body, headers=headers)

            if response.status_code == 200:
                data = response.json()
                route = data['features'][0]['properties']['summary']
                trip.total_distance = route['distance'] / 1000 * 0.621371  # meters ➔ km ➔ miles
                trip.estimated_driving_time = route['duration'] / 3600  # seconds ➔ hours
                trip.save()

    def geocode_location(self, address):
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
                return (lat, lon)  # return (lat, lon)
        return None

    permission_classes = []
    
    def post(self, request, pk):
        trip = Trip.objects.get(pk=pk)
        date = request.data.get('date', timezone.now().date())
        
        logs = DrivingLog.objects.filter(
            trip=trip,
            start_time__date=date
        )
        
        driving_hours = sum(
            (log.end_time - log.start_time).total_seconds() / 3600
            for log in logs if log.status == 'D'
        )

        on_duty_hours = sum(
            (log.end_time - log.start_time).total_seconds() / 3600
            for log in logs if log.status == 'ON'
        )

        off_duty_hours = sum(
            (log.end_time - log.start_time).total_seconds() / 3600
            for log in logs if log.status == 'OFF'
        )

        sleeper_berth_hours = sum(
            (log.end_time - log.start_time).total_seconds() / 3600
            for log in logs if log.status == 'SB'
        )

        
        daily_log = DailyLogSheet.objects.create(
            trip=trip,
            date=date,
            driving_hours=driving_hours,
            on_duty_hours=on_duty_hours,
            off_duty_hours=off_duty_hours,
            sleeper_berth_hours=sleeper_berth_hours
        )
        
        return Response(DailyLogSheetSerializer(daily_log).data)
     
def _calculate_trip_info(trip):
    import math

    pickup_coords = TripRouteView().geocode_location(trip.pickup_location)
    dropoff_coords = TripRouteView().geocode_location(trip.dropoff_location)

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
