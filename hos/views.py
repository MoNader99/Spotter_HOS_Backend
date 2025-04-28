import math
import requests
import json
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView
from Spotter_HOS import settings
from .models import Trip, DrivingLog, DailyLogSheet
from .serializers import DailyLogSheetSerializer, DrivingLogSerializer, TripSerializer, SimplifiedTripSerializer
from rest_framework import status
from datetime import datetime
from django.utils import timezone
from .utils import HOSCalculator
from .permissions import IsAdminOrSupervisor, IsDriver, IsTripDriver, IsTripDriverOrAdmin
from rest_framework.permissions import IsAuthenticated
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import polyline

class TripCreateView(generics.CreateAPIView):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer
    permission_classes = [IsAuthenticated, IsAdminOrSupervisor]

    def perform_create(self, serializer):
        trip = serializer.save()
        _calculate_trip_info(trip)
        
        # Send WebSocket notification
        channel_layer = get_channel_layer()
        trip_data = TripSerializer(trip).data
        async_to_sync(channel_layer.group_send)(
            'all_trips',
            {
                'type': 'trip_created',
                'trip': trip_data
            }
        )
        
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
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            trip = Trip.objects.get(pk=pk)

            pickup_coords = self.geocode_location(trip.pickup_location)
            dropoff_coords = self.geocode_location(trip.dropoff_location)

            if not pickup_coords or not dropoff_coords:
                return Response(
                    {"detail": "Could not geocode locations"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

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
                return Response(
                    {"detail": "Error fetching route"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            data = response.json()

            if 'routes' not in data or not data['routes']:
                return Response(
                    {"detail": "No routes found"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            route = data['routes'][0]
            
            # Decode the polyline geometry
            try:
                # The geometry is a polyline string
                decoded_coords = polyline.decode(route['geometry'])
                # Convert to [lat, lng] format (OpenRouteService uses [lng, lat])
                coordinates = [[coord[0], coord[1]] for coord in decoded_coords]
            except Exception as e:
                # Fallback to using waypoints if polyline decoding fails
                coordinates = []
                for segment in route['segments']:
                    for step in segment['steps']:
                        for way_point in step['way_points']:
                            # Get the actual coordinate from the geometry
                            if 'coordinates' in route['geometry']:
                                coord = route['geometry']['coordinates'][way_point]
                                coordinates.append([coord[1], coord[0]])
            
            # Remove duplicates while preserving order
            coordinates = list(dict.fromkeys(map(tuple, coordinates)))
            coordinates = [list(coord) for coord in coordinates]

            # Process steps
            steps = []
            for segment in route['segments']:
                for step in segment['steps']:
                    steps.append({
                        "instruction": step['instruction'],
                        "distance_miles": round(step['distance'] / 1000 * 0.621371, 2),  # meters to miles
                        "estimated_time_hours": round(step['duration'] / 3600, 2)  # seconds to hours
                    })

            # Calculate totals
            total_distance_miles = round(route['summary']['distance'] / 1000 * 0.621371, 2)
            total_time_hours = round(route['summary']['duration'] / 3600, 2)

            # Add 1 hour for pickup and 1 hour for drop-off
            total_time_hours += 2

            # Calculate fuel stops (every 500 miles)
            fuel_stops = []
            miles_so_far = 0
            fuel_stop_distance = 500  # miles between fuel stops
            
            # Pre-calculate cumulative distances for each coordinate
            cumulative_distances = [0]
            for i in range(len(coordinates) - 1):
                lat1, lon1 = coordinates[i]
                lat2, lon2 = coordinates[i + 1]
                segment_distance = self.calculate_distance(lat1, lon1, lat2, lon2)
                cumulative_distances.append(cumulative_distances[-1] + segment_distance)
            
            # Find coordinates for fuel stops
            for i in range(len(coordinates) - 1):
                # If we've reached a fuel stop distance
                if cumulative_distances[i] >= fuel_stop_distance * (len(fuel_stops) + 1):
                    # Use the current coordinate as the fuel stop location
                    fuel_stop_coord = coordinates[i]
                    
                    # Find gas stations in a single batch search with a larger radius
                    gas_stations = self.find_nearby_gas_stations(fuel_stop_coord[0], fuel_stop_coord[1], radius=25)
                    
                    # If no gas stations found at the exact location, try nearby coordinates
                    if not gas_stations:
                        # Look for stations within 50 miles (both before and after)
                        search_range = 50  # miles
                        search_coords = []
                        
                        # Add coordinates before the fuel stop
                        for j in range(i, max(0, i - 10), -1):
                            if cumulative_distances[i] - cumulative_distances[j] <= search_range:
                                search_coords.append(coordinates[j])
                        
                        # Add coordinates after the fuel stop
                        for j in range(i + 1, min(len(coordinates), i + 11)):
                            if cumulative_distances[j] - cumulative_distances[i] <= search_range:
                                search_coords.append(coordinates[j])
                        
                        # Search for gas stations in all coordinates in parallel
                        for coord in search_coords:
                            stations = self.find_nearby_gas_stations(coord[0], coord[1], radius=10)
                            if stations:
                                gas_stations = stations
                                fuel_stop_coord = coord
                                break
                    
                    # Add fuel stop with gas stations
                    fuel_stops.append({
                        "location": fuel_stop_coord,
                        "distance_from_start": round(cumulative_distances[i], 2),
                        "gas_stations": gas_stations
                    })
            
            route_response = {
                "coordinates": coordinates,
                "steps": steps,
                "total_distance_miles": total_distance_miles,
                "estimated_total_time_hours": total_time_hours,
                "fuel_stops": fuel_stops
            }

            return Response(route_response, status=status.HTTP_200_OK)

        except Trip.DoesNotExist:
            return Response(
                {"detail": "Trip not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )

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
        
    def calculate_distance(self, lat1, lon1, lat2, lon2):
        """Calculate distance between two points in miles using the Haversine formula"""
        R = 3959  # Earth's radius in miles
        
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        
        return R * c
        
    def find_nearby_gas_stations(self, lat, lon, radius=5):
        """Find gas stations near the given coordinates"""
        # Use OpenStreetMap's Overpass API to find gas stations
        overpass_url = "https://overpass-api.de/api/interpreter"
        query = f"""
        [out:json][timeout:25];
        (
          node["amenity"="fuel"](around:{radius*1000},{lat},{lon});
          way["amenity"="fuel"](around:{radius*1000},{lat},{lon});
          relation["amenity"="fuel"](around:{radius*1000},{lat},{lon});
        );
        out body;
        >;
        out skel qt;
        """
        
        try:
            response = requests.post(overpass_url, data=query)
            if response.status_code == 200:
                data = response.json()
                gas_stations = []
                
                for element in data.get('elements', []):
                    if 'lat' in element and 'lon' in element:
                        gas_stations.append({
                            "name": element.get('tags', {}).get('name', 'Unknown Gas Station'),
                            "brand": element.get('tags', {}).get('brand', 'Unknown Brand'),
                            "location": [element['lat'], element['lon']],
                            "distance": round(self.calculate_distance(lat, lon, element['lat'], element['lon']), 2)
                        })
                
                # Sort by distance
                gas_stations.sort(key=lambda x: x['distance'])
                
                # Return top 5 closest stations
                return gas_stations[:5]
        except Exception as e:
            print(f"Error finding gas stations: {e}")
        
        # Return empty list if no stations found or error occurred
        return []

class TripDetailView(generics.RetrieveAPIView):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer
    permission_classes = [IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        _calculate_trip_info(instance)  # Recalculate when fetching, keep consistent
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

class CompleteTripView(APIView):
    permission_classes = [IsAuthenticated, IsTripDriver]

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
    permission_classes = [IsAuthenticated, IsTripDriver]
    
    def get(self, request, pk):
        trip = Trip.objects.get(pk=pk)
        daily_logs = trip.daily_logs.all()
        logs_data = DailyLogSheetSerializer(daily_logs, many=True).data
        return Response({
            "trip_id": trip.id,
            "logs": logs_data
        })

class AddLogView(APIView):
    permission_classes = [IsAuthenticated, IsTripDriver]

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
                    
                    # Check if driver has arrived at the drop-off location
                    if trip.current_location.lower() == trip.dropoff_location.lower():
                        trip.status = 'COMPLETED'
                    
                    trip.save()
                    
                    # Send WebSocket notification for trip update
                    channel_layer = get_channel_layer()
                    trip_data = TripSerializer(trip).data
                    async_to_sync(channel_layer.group_send)(
                        f'trip_{trip.id}',
                        {
                            'type': 'trip_update',
                            'trip': trip_data
                        }
                    )
                    
                    # Also notify the all_trips group
                    async_to_sync(channel_layer.group_send)(
                        'all_trips',
                        {
                            'type': 'trip_updated',
                            'trip': trip_data
                        }
                    )
                
                # Send WebSocket notification for log update
                channel_layer = get_channel_layer()
                log_data = DrivingLogSerializer(log).data
                async_to_sync(channel_layer.group_send)(
                    f'trip_{trip.id}',
                    {
                        'type': 'log_update',
                        'log': log_data
                    }
                )

                return Response(serializer.data, status=status.HTTP_201_CREATED)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except Trip.DoesNotExist:
            return Response({"error": "Trip not found"}, status=status.HTTP_404_NOT_FOUND)

class DailyLogView(APIView):
    permission_classes = [IsAuthenticated, IsTripDriver]
    
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
    permission_classes = [IsAuthenticated, IsTripDriver]

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

# New view for drivers to assign trips to themselves
class AssignTripView(APIView):
    permission_classes = [IsAuthenticated, IsDriver]
    
    def post(self, request, pk):
        try:
            trip = Trip.objects.get(pk=pk)
            
            # Check if trip is already assigned
            if trip.driver:
                return Response(
                    {"error": "Trip is already assigned to a driver"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Check if trip is completed
            if trip.status == 'COMPLETED':
                return Response(
                    {"error": "Cannot assign completed trips"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Assign trip to the current user
            trip.driver = request.user
            trip.save()
            
            # Send WebSocket notification
            channel_layer = get_channel_layer()
            trip_data = TripSerializer(trip).data
            async_to_sync(channel_layer.group_send)(
                f'trip_{trip.id}',
                {
                    'type': 'trip_update',
                    'trip': trip_data
                }
            )
            
            # Also notify the all_trips group
            async_to_sync(channel_layer.group_send)(
                'all_trips',
                {
                    'type': 'trip_updated',
                    'trip': trip_data
                }
            )
            
            return Response({
                "message": f"Trip successfully assigned to {request.user.username}",
                "trip_id": trip.id
            }, status=status.HTTP_200_OK)
            
        except Trip.DoesNotExist:
            return Response(
                {"error": "Trip not found"},
                status=status.HTTP_404_NOT_FOUND
            )

# New view for listing available trips (unassigned trips)
class AvailableTripsView(generics.ListAPIView):
    serializer_class = TripSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Trip.objects.filter(driver__isnull=True, status='NOT_STARTED')

# New view for listing driver's assigned trips
class DriverTripsView(generics.ListAPIView):
    serializer_class = TripSerializer
    permission_classes = [IsAuthenticated, IsDriver]
    
    def get_queryset(self):
        return Trip.objects.filter(driver=self.request.user)

# New view for admins/supervisors to list all trips
class AllTripsView(generics.ListAPIView):
    serializer_class = TripSerializer
    permission_classes = [IsAuthenticated, IsAdminOrSupervisor]
    
    def get_queryset(self):
        return Trip.objects.all()

class DriverAssignedTripsView(generics.ListAPIView):
    serializer_class = TripSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Trip.objects.filter(driver=self.request.user)

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
