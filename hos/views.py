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
from datetime import datetime, timedelta
from django.utils import timezone
from .utils import HOSCalculator, calculate_trip_info, geocode_location
from .permissions import IsAdminOrSupervisor, IsDriver, IsTripDriver, IsTripDriverOrAdmin, TripPermission
from rest_framework.permissions import IsAuthenticated
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import polyline
import random

class TripCreateView(generics.CreateAPIView):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer
    permission_classes = [IsAuthenticated, TripPermission]

    def create(self, request, *args, **kwargs):
        try:
            # Get coordinates from request data
            pickup_coords = request.data.get('pickup_coordinates')
            dropoff_coords = request.data.get('dropoff_coordinates')
            
            if pickup_coords and dropoff_coords:
                directions_url = "https://api.openrouteservice.org/v2/directions/driving-car"
                headers = {
                    'Authorization': settings.OPENROUTESERVICE_API_KEY,
                    'Content-Type': 'application/json',
                }

                # Try with different search radii
                search_radii = [350, 1000, 2000, 5000]  # meters
                success = False

                for radius in search_radii:
                    body = {
                        "coordinates": [
                            [pickup_coords[1], pickup_coords[0]],  # [lng, lat]
                            [dropoff_coords[1], dropoff_coords[0]]
                        ],
                        "radiuses": [radius, radius],  # Search radius for each coordinate
                        "preference": "fastest",
                        "units": "mi",
                        "continue_straight": False,
                        "geometry_simplify": True
                    }

                    response = requests.post(directions_url, json=body, headers=headers)

                    if response.status_code == 200:
                        success = True
                        data = response.json()
                        
                        if 'routes' in data and data['routes']:
                            route = data['routes'][0]
                            route_summary = route['summary']
                            
                            # Calculate distances
                            total_distance_miles = route_summary['distance'] * 0.621371  # Convert meters to miles
                            total_duration_hours = route_summary['duration'] / 3600  # Convert seconds to hours
                            
                            # Add the calculated values to request data
                            request.data['total_distance'] = float(f"{total_distance_miles:.2f}")
                            request.data['estimated_driving_time'] = float(f"{total_duration_hours:.2f}")
                            
                            # Create and save the trip using the serializer
                            serializer = self.get_serializer(data=request.data)
                            serializer.is_valid(raise_exception=True)
                            self.perform_create(serializer)
                            headers = self.get_success_headers(serializer.data)
                            
                            return Response(
                                serializer.data,
                                status=status.HTTP_201_CREATED,
                                headers=headers
                            )
                        break

                if not success:
                    # Fallback to Haversine formula
                    R = 3959  # Earth's radius in miles
                    
                    # Convert decimal degrees to radians
                    lat1, lon1, lat2, lon2 = map(math.radians, [pickup_coords[0], pickup_coords[1], dropoff_coords[0], dropoff_coords[1]])
                    
                    # Haversine formula
                    dlat = lat2 - lat1
                    dlon = lon2 - lon1
                    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
                    c = 2 * math.asin(math.sqrt(a))
                    distance = R * c
                    
                    # Estimate duration (assuming average speed of 60 mph)
                    duration = distance / 60
                    
                    # Add the calculated values to request data
                    request.data['total_distance'] = float(f"{distance:.2f}")
                    request.data['estimated_driving_time'] = float(f"{duration:.2f}")
                    
                    # Create and save the trip using the serializer
                    serializer = self.get_serializer(data=request.data)
                    serializer.is_valid(raise_exception=True)
                    self.perform_create(serializer)
                    headers = self.get_success_headers(serializer.data)
                    
                    return Response(
                        serializer.data,
                        status=status.HTTP_201_CREATED,
                        headers=headers
                    )
            else:
                return Response(
                    {"error": "Missing pickup or dropoff coordinates"},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def perform_create(self, serializer):
        try:
            user = self.request.user
            auto_assign = self.request.data.get('auto_assign', False)
            
            # Get coordinates from request data
            pickup_coords = self.request.data.get('pickup_coordinates')
            dropoff_coords = self.request.data.get('dropoff_coordinates')
            
            # Check if user is a driver
            is_driver = user.groups.filter(name='drivers').exists()
            
            # Create trip with coordinates
            trip_data = {
                'driver': user if auto_assign and is_driver else None,
                'pickup_coordinates': pickup_coords,
                'dropoff_coordinates': dropoff_coords
            }
            
            trip = serializer.save(**trip_data)
            
            # Send WebSocket notification
            try:
                channel_layer = get_channel_layer()
                trip_data = TripSerializer(trip).data
                async_to_sync(channel_layer.group_send)(
                    'all_trips',
                    {
                        'type': 'trip_created',
                        'trip': trip_data
                    }
                )
            except Exception:
                pass

        except Exception as e:
            raise

class TripRouteView(APIView):
    permission_classes = [IsAuthenticated]

    # Dictionary of state names
    STATE_NAMES = {
        'AL': 'Alabama',
        'AK': 'Alaska',
        'AZ': 'Arizona',
        'AR': 'Arkansas',
        'CA': 'California',
        'CO': 'Colorado',
        'CT': 'Connecticut',
        'DE': 'Delaware',
        'FL': 'Florida',
        'GA': 'Georgia',
        'HI': 'Hawaii',
        'ID': 'Idaho',
        'IL': 'Illinois',
        'IN': 'Indiana',
        'IA': 'Iowa',
        'KS': 'Kansas',
        'KY': 'Kentucky',
        'LA': 'Louisiana',
        'ME': 'Maine',
        'MD': 'Maryland',
        'MA': 'Massachusetts',
        'MI': 'Michigan',
        'MN': 'Minnesota',
        'MS': 'Mississippi',
        'MO': 'Missouri',
        'MT': 'Montana',
        'NE': 'Nebraska',
        'NV': 'Nevada',
        'NH': 'New Hampshire',
        'NJ': 'New Jersey',
        'NM': 'New Mexico',
        'NY': 'New York',
        'NC': 'North Carolina',
        'ND': 'North Dakota',
        'OH': 'Ohio',
        'OK': 'Oklahoma',
        'OR': 'Oregon',
        'PA': 'Pennsylvania',
        'RI': 'Rhode Island',
        'SC': 'South Carolina',
        'SD': 'South Dakota',
        'TN': 'Tennessee',
        'TX': 'Texas',
        'UT': 'Utah',
        'VT': 'Vermont',
        'VA': 'Virginia',
        'WA': 'Washington',
        'WV': 'West Virginia',
        'WI': 'Wisconsin',
        'WY': 'Wyoming'
    }

    # Dictionary of major cities in each state (coordinates)
    STATE_CITIES = {
        'AL': [33.5207, -86.8025],  # Birmingham
        'AK': [61.2181, -149.9003],  # Anchorage
        'AZ': [33.4484, -112.0740],  # Phoenix
        'AR': [34.7465, -92.2896],  # Little Rock
        'CA': [34.0522, -118.2437],  # Los Angeles
        'CO': [39.7392, -104.9903],  # Denver
        'CT': [41.7637, -72.6851],  # Hartford
        'DE': [39.7391, -75.5398],  # Wilmington
        'FL': [25.7617, -80.1918],  # Miami
        'GA': [33.7490, -84.3880],  # Atlanta
        'HI': [21.3069, -157.8583],  # Honolulu
        'ID': [43.6150, -116.2023],  # Boise
        'IL': [41.8781, -87.6298],  # Chicago
        'IN': [39.7684, -86.1581],  # Indianapolis
        'IA': [41.5868, -93.6250],  # Des Moines
        'KS': [39.0997, -94.5786],  # Kansas City
        'KY': [38.2527, -85.7585],  # Louisville
        'LA': [29.9511, -90.0715],  # New Orleans
        'ME': [43.6591, -70.2568],  # Portland
        'MD': [39.2904, -76.6122],  # Baltimore
        'MA': [42.3601, -71.0589],  # Boston
        'MI': [42.3314, -83.0458],  # Detroit
        'MN': [44.9778, -93.2650],  # Minneapolis
        'MS': [32.2988, -90.1848],  # Jackson
        'MO': [38.6270, -90.1994],  # St. Louis
        'MT': [46.8797, -110.3626],  # Helena
        'NE': [41.2565, -95.9345],  # Omaha
        'NV': [36.1699, -115.1398],  # Las Vegas
        'NH': [43.1939, -71.5724],  # Manchester
        'NJ': [40.7128, -74.0060],  # Newark
        'NM': [35.0844, -106.6504],  # Albuquerque
        'NY': [40.7128, -74.0060],  # New York City
        'NC': [35.7796, -78.6382],  # Raleigh
        'ND': [46.8772, -96.7898],  # Fargo
        'OH': [39.9612, -82.9988],  # Columbus
        'OK': [35.4676, -97.5164],  # Oklahoma City
        'OR': [45.5155, -122.6789],  # Portland
        'PA': [39.9526, -75.1652],  # Philadelphia
        'RI': [41.8240, -71.4128],  # Providence
        'SC': [34.0007, -81.0348],  # Columbia
        'SD': [43.5460, -96.7313],  # Sioux Falls
        'TN': [36.1627, -86.7816],  # Nashville
        'TX': [29.7604, -95.3698],  # Houston
        'UT': [40.7608, -111.8910],  # Salt Lake City
        'VT': [44.4759, -73.2121],  # Burlington
        'VA': [37.5407, -77.4360],  # Richmond
        'WA': [47.6062, -122.3321],  # Seattle
        'WV': [38.3498, -81.6326],  # Charleston
        'WI': [43.0722, -89.4008],  # Madison
        'WY': [41.1399, -104.8202]  # Cheyenne
    }

    @staticmethod
    def get_state_from_coordinates(lat, lon):
        """Get the state code from coordinates using reverse geocoding"""
        try:
            # Use OpenStreetMap's Nominatim service for reverse geocoding
            url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=5"
            headers = {'User-Agent': 'HOS_App/1.0'}
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                address = data.get('address', {})
                state = address.get('state')
                
                if state:
                    # Convert state name to state code
                    for code, name in TripRouteView.STATE_NAMES.items():
                        if name.lower() == state.lower():
                            return code
                    
                    # If state name doesn't match exactly, try partial matching
                    for code, name in TripRouteView.STATE_NAMES.items():
                        if state.lower() in name.lower() or name.lower() in state.lower():
                            return code
            return None
        except Exception as e:
            print(f"Error in get_state_from_coordinates: {str(e)}")
            return None

    def calculate_distance(self, lat1, lon1, lat2, lon2):
        """Calculate distance between two points in miles using the Haversine formula"""
        R = 3959  # Earth's radius in miles
        
        # Convert decimal degrees to radians
        lat1, lon1, lat2, lon2 = map(math.radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
        
        # Haversine formula
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        
        # Calculate the distance
        distance = R * c
        
        return distance

    def get(self, request, pk):
        try:
            trip = Trip.objects.get(pk=pk)

            # Use stored coordinates directly
            pickup_coords = trip.pickup_coordinates
            dropoff_coords = trip.dropoff_coordinates

            if not pickup_coords or not dropoff_coords:
                return Response(
                    {"detail": "Trip coordinates not found"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Get states from coordinates
            pickup_state = self.get_state_from_coordinates(pickup_coords[0], pickup_coords[1])
            dropoff_state = self.get_state_from_coordinates(dropoff_coords[0], dropoff_coords[1])

            if not pickup_state or not dropoff_state:
                return Response(
                    {"detail": "Could not determine states from coordinates"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Get major city coordinates for routing
            pickup_city = self.STATE_CITIES.get(pickup_state)
            dropoff_city = self.STATE_CITIES.get(dropoff_state)

            if not pickup_city or not dropoff_city:
                return Response(
                    {"detail": "Invalid state codes"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # First try to get the route between major cities
            directions_url = "https://api.openrouteservice.org/v2/directions/driving-car"
            headers = {
                'Authorization': settings.OPENROUTESERVICE_API_KEY,
                'Content-Type': 'application/json',
            }

            body = {
                "coordinates": [
                    [pickup_city[1], pickup_city[0]],  # [lng, lat]
                    [dropoff_city[1], dropoff_city[0]]
                ],
                "preference": "fastest",
                "units": "mi",
                "continue_straight": False,
                "geometry_simplify": True,
                "instructions": True
            }

            response = requests.post(directions_url, json=body, headers=headers)

            if response.status_code != 200:
                return Response(
                    {"detail": "Could not find a valid route between the states"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            data = response.json()

            if 'routes' not in data or not data['routes']:
                return Response(
                    {"detail": "No routes found"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            route = data['routes'][0]
            
            # Calculate total distance using the route segments
            total_distance_meters = 0
            for segment in route['segments']:
                total_distance_meters += segment['distance']
            
            # Convert to miles
            total_distance_miles = round(total_distance_meters / 1609.34, 2)  # meters to miles
            
            # Calculate total duration
            total_duration_seconds = route['summary']['duration']
            total_duration_hours = round(total_duration_seconds / 3600, 2)

            # Add 1 hour for pickup and 1 hour for drop-off (ON Duty)
            total_duration_hours += 2

            # Decode the polyline geometry
            try:
                # The geometry is a polyline string
                decoded_coords = polyline.decode(route['geometry'])
                # Convert to [lat, lng] format (OpenRouteService uses [lng, lat])
                coordinates = [[coord[0], coord[1]] for coord in decoded_coords]
            except Exception as e:
                coordinates = []
                for segment in route['segments']:
                    for step in segment['steps']:
                        for way_point in step['way_points']:
                            if 'coordinates' in route['geometry']:
                                coord = route['geometry']['coordinates'][way_point]
                                coordinates.append([coord[1], coord[0]])
            
            # Remove duplicates while preserving order
            coordinates = list(dict.fromkeys(map(tuple, coordinates)))
            coordinates = [list(coord) for coord in coordinates]

            # Process steps with accurate distances
            steps = []
            for segment in route['segments']:
                for step in segment['steps']:
                    step_distance_miles = round(step['distance'] / 1609.34, 2)  # meters to miles
                    step_duration_hours = round(step['duration'] / 3600, 2)  # seconds to hours
                    steps.append({
                        "instruction": step['instruction'],
                        "distance_miles": step_distance_miles,
                        "estimated_time_hours": step_duration_hours
                    })

            # Calculate required breaks and fuel stops based on HOS rules
            MAX_DRIVING_HOURS = 11  # Maximum driving hours per day
            BREAK_TIME_MINUTES = 30  # Break time between driving sessions
            FUEL_STOP_DISTANCE = 1000  # Miles between fuel stops
            FUEL_STOP_TIME_MINUTES = 30  # Time for fuel stop

            # Calculate number of days needed
            driving_hours_per_day = min(MAX_DRIVING_HOURS, total_duration_hours)
            num_days = math.ceil(total_duration_hours / driving_hours_per_day)

            # Calculate number of breaks needed
            num_breaks = math.ceil(total_duration_hours / 4)  # Break every 4 hours
            total_break_time = num_breaks * (BREAK_TIME_MINUTES / 60)  # Convert to hours

            # Calculate number of fuel stops needed
            num_fuel_stops = math.ceil(total_distance_miles / FUEL_STOP_DISTANCE)
            total_fuel_stop_time = num_fuel_stops * (FUEL_STOP_TIME_MINUTES / 60)  # Convert to hours

            # Calculate fuel stops
            fuel_stops = []
            miles_so_far = 0
            
            # Pre-calculate cumulative distances for each coordinate
            cumulative_distances = [0]
            for i in range(len(coordinates) - 1):
                lat1, lon1 = coordinates[i]
                lat2, lon2 = coordinates[i + 1]
                segment_distance = self.calculate_distance(lat1, lon1, lat2, lon2)
                cumulative_distances.append(cumulative_distances[-1] + segment_distance)

                # Check if we need a fuel stop
                if cumulative_distances[-1] >= FUEL_STOP_DISTANCE * (len(fuel_stops) + 1):
                    fuel_stop_coord = coordinates[i]
                    gas_stations = self.find_nearby_gas_stations(fuel_stop_coord[0], fuel_stop_coord[1], radius=25)
                    
                    if not gas_stations:
                        # Look for stations within 50 miles
                        search_range = 50
                        search_coords = []
                        
                        # Add coordinates before and after
                        for j in range(max(0, i - 10), min(len(coordinates), i + 11)):
                            if abs(cumulative_distances[j] - cumulative_distances[i]) <= search_range:
                                search_coords.append(coordinates[j])
                        
                        # Search for gas stations
                        for coord in search_coords:
                            stations = self.find_nearby_gas_stations(coord[0], coord[1], radius=10)
                            if stations:
                                gas_stations = stations
                                fuel_stop_coord = coord
                                break
                    
                    fuel_stops.append({
                        "location": fuel_stop_coord,
                        "distance_from_start": round(cumulative_distances[i], 2),
                        "gas_stations": gas_stations,
                        "status": "OFF",  # Fuel stops are OFF duty
                        "duration_minutes": FUEL_STOP_TIME_MINUTES
                    })

            # Calculate daily schedule
            daily_schedule = []
            remaining_hours = total_duration_hours
            current_day = 1

            while remaining_hours > 0 and current_day <= num_days:
                day_schedule = {
                    "day": current_day,
                    "activities": []
                }

                # Add pickup time if it's day 1
                if current_day == 1:
                    day_schedule["activities"].append({
                        "type": "ON",
                        "description": "Pickup",
                        "duration_hours": 1
                    })

                # Add driving sessions with breaks
                driving_hours_today = min(MAX_DRIVING_HOURS, remaining_hours)
                sessions = math.ceil(driving_hours_today / 4)  # Break every 4 hours

                for session in range(sessions):
                    # Add driving session
                    session_hours = min(4, driving_hours_today - (session * 4))
                    day_schedule["activities"].append({
                        "type": "D",
                        "description": f"Driving Session {session + 1}",
                        "duration_hours": session_hours
                    })

                    # Add break if not the last session
                    if session < sessions - 1:
                        day_schedule["activities"].append({
                            "type": "OFF",
                            "description": "Break",
                            "duration_hours": BREAK_TIME_MINUTES / 60
                        })

                # Add dropoff time if it's the last day
                if current_day == num_days:
                    day_schedule["activities"].append({
                        "type": "ON",
                        "description": "Dropoff",
                        "duration_hours": 1
                    })

                # Add remaining time as sleeper berth
                total_activity_hours = sum(activity["duration_hours"] for activity in day_schedule["activities"])
                if total_activity_hours < 24:
                    day_schedule["activities"].append({
                        "type": "SB",
                        "description": "Sleeper Berth",
                        "duration_hours": 24 - total_activity_hours
                    })

                daily_schedule.append(day_schedule)
                remaining_hours -= driving_hours_today
                current_day += 1

            route_response = {
                "coordinates": coordinates,
                "steps": steps,
                "total_distance_miles": total_distance_miles,
                "estimated_total_time_hours": total_duration_hours,
                "fuel_stops": fuel_stops,
                "daily_schedule": daily_schedule,
                "hos_summary": {
                    "total_days": num_days,
                    "total_break_time_hours": total_break_time,
                    "total_fuel_stop_time_hours": total_fuel_stop_time,
                    "max_driving_hours_per_day": MAX_DRIVING_HOURS,
                    "break_duration_minutes": BREAK_TIME_MINUTES,
                    "fuel_stop_distance_miles": FUEL_STOP_DISTANCE
                },
                "states": {
                    "pickup_state": pickup_state,
                    "dropoff_state": dropoff_state,
                    "pickup_city": self.STATE_NAMES[pickup_state],
                    "dropoff_city": self.STATE_NAMES[dropoff_state]
                }
            }

            return Response(route_response, status=status.HTTP_200_OK)

        except Trip.DoesNotExist:
            return Response(
                {"detail": "Trip not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

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
            pass
        
        # Return empty list if no stations found or error occurred
        return []

class TripDetailView(generics.RetrieveAPIView):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer
    permission_classes = [IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        
        # Calculate trip info if coordinates exist and distance/time are not set
        if (instance.pickup_coordinates and instance.dropoff_coordinates and 
            (instance.total_distance is None or instance.estimated_driving_time is None)):
            
            directions_url = "https://api.openrouteservice.org/v2/directions/driving-car"
            headers = {
                'Authorization': settings.OPENROUTESERVICE_API_KEY,
                'Content-Type': 'application/json',
            }
            body = {
                "coordinates": [
                    [instance.pickup_coordinates[1], instance.pickup_coordinates[0]],  # [lng, lat]
                    [instance.dropoff_coordinates[1], instance.dropoff_coordinates[0]]
                ],
                "preference": "fastest",
                "units": "mi",
                "continue_straight": False,
                "geometry_simplify": True,
                "instructions": True
            }

            response = requests.post(directions_url, json=body, headers=headers)

            if response.status_code == 200:
                data = response.json()
                if 'routes' in data and data['routes']:
                    route = data['routes'][0]
                    
                    # Calculate total distance using the route segments
                    total_distance_meters = 0
                    for segment in route['segments']:
                        total_distance_meters += segment['distance']
                    
                    # Convert to miles
                    total_distance_miles = round(total_distance_meters / 1609.34, 2)  # meters to miles
                    
                    # Calculate total duration
                    total_duration_seconds = route['summary']['duration']
                    total_duration_hours = round(total_duration_seconds / 3600, 2)

                    # Add 1 hour for pickup and 1 hour for drop-off (ON Duty)
                    total_duration_hours += 2

                    # Update the trip fields
                    instance.total_distance = total_distance_miles
                    instance.estimated_driving_time = total_duration_hours
                    instance.save()

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

            # Add default remark if empty
            if not request.data.get('remarks'):
                request.data['remarks'] = f"{request.data.get('status', '')} status log"

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
                        'type': 'log_created',
                        'log': log_data
                    }
                )
                
                return Response(DrivingLogSerializer(log).data, status=status.HTTP_201_CREATED)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except Trip.DoesNotExist:
            return Response({"error": "Trip not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

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
        print(f"\n=== AssignTripView Debug ===")
        print(f"User: {request.user.username}")
        print(f"User groups: {list(request.user.groups.all())}")
        print(f"Trip ID: {pk}")
        
        try:
            trip = Trip.objects.get(pk=pk)
            print(f"Found trip: {trip.id}")
            print(f"Current status: {trip.status}")
            print(f"Current driver: {trip.driver}")
            
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
            print(f"Successfully assigned trip to {request.user.username}")
            
            # Send WebSocket notification
            try:
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
                print("WebSocket notifications sent successfully")
            except Exception as ws_error:
                print(f"WebSocket notification failed: {str(ws_error)}")
                # Don't fail the request if WebSocket fails
            
            return Response({
                "message": f"Trip successfully assigned to {request.user.username}",
                "trip_id": trip.id
            }, status=status.HTTP_200_OK)
            
        except Trip.DoesNotExist:
            print(f"Trip {pk} not found")
            return Response(
                {"error": "Trip not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
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

class GenerateTripLogsView(APIView):
    permission_classes = [IsAuthenticated, IsTripDriverOrAdmin]

    def get_route_info(self, trip):
        """Generate random route information"""
        print("\n=== Generating Random Route Info ===")
        if not (trip.pickup_coordinates and trip.dropoff_coordinates):
            raise ValueError("Trip must have pickup and dropoff coordinates")

        # Generate random distance between 100 and 2000 miles
        distance = random.uniform(100, 2000)
        print(f"Generated distance: {distance:.2f} miles")
        
        # Generate random duration based on distance (assuming 60 mph average)
        # Add some randomness to the speed (between 55-65 mph)
        speed = random.uniform(55, 65)
        duration = distance / speed
        print(f"Generated speed: {speed:.2f} mph")
        print(f"Calculated duration: {duration:.2f} hours")

        return {
            'total_distance': round(distance, 2),
            'base_driving_time': round(duration, 2)
        }

    def get_random_start_hour(self):
        """Generate a random start hour between 5 AM and 10 AM"""
        return random.randint(5, 10)

    def post(self, request, pk):
        try:
            print("\n=== Starting Trip Log Generation ===")
            trip = Trip.objects.get(pk=pk)
            print(f"Trip ID: {trip.id}")
            print(f"Current status: {trip.status}")
            
            if trip.status == 'COMPLETED':
                print("Error: Trip is already completed")
                return Response(
                    {"error": "Cannot generate logs for completed trips"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Get route information
            route_info = self.get_route_info(trip)
            print("\nRoute Information:")
            print(f"Total distance: {route_info['total_distance']} miles")
            print(f"Base driving time: {route_info['base_driving_time']} hours")
            
            # Constants for HOS regulations
            MAX_DRIVING_HOURS = 11  # Maximum driving hours per day
            DRIVING_SPEED = 60  # Average speed in mph
            BREAK_TIME_MINUTES = 30  # Required break time
            PRE_TRIP_MINUTES = 60  # Pre-trip inspection time
            POST_TRIP_MINUTES = 60  # Post-trip inspection time
            MORNING_OFF_DUTY_MINUTES = 30  # Morning routine time
            PARKING_OFF_DUTY_MINUTES = 30  # Parking and meal time

            # Calculate number of days needed
            total_driving_hours = route_info['base_driving_time']
            days_needed = min(5, max(1, math.ceil(total_driving_hours / MAX_DRIVING_HOURS)))
            print(f"\nTrip Duration:")
            print(f"Total driving hours needed: {total_driving_hours:.2f}")
            print(f"Number of days required: {days_needed}")
            
            # Get the current date in the local timezone
            local_tz = timezone.get_current_timezone()
            current_date = timezone.now().astimezone(local_tz).date()
            
            # Generate logs for each day
            remaining_miles = route_info['total_distance']
            start_hours = []  # Store start hours for each day
            
            for day in range(days_needed):
                # Generate random start hour for this day
                start_hour = self.get_random_start_hour()
                start_hours.append(start_hour)
                print(f"\n=== Generating Logs for Day {day + 1} ===")
                print(f"Start hour for day {day + 1}: {start_hour:02d}:00")
                
                day_start = current_date + timedelta(days=day)
                day_start_midnight = timezone.make_aware(
                    datetime.combine(day_start, datetime.min.time()),
                    timezone=local_tz
                )
                current_datetime = timezone.make_aware(
                    datetime.combine(day_start, datetime.min.time().replace(hour=start_hour)),
                    timezone=local_tz
                )
                day_end = timezone.make_aware(
                    datetime.combine(day_start, datetime.max.time()) - timedelta(microseconds=1),
                    timezone=local_tz
                )

                # 0. OFF duty from midnight until morning routine
                print("\nCreating OFF duty log from midnight")
                DrivingLog.objects.create(
                    trip=trip,
                    status='OFF',
                    location='Home' if day == 0 else 'Truck Stop',
                    remarks='Off duty rest period',
                    start_time=day_start_midnight,
                    end_time=current_datetime
                )

                # 1. Morning OFF Duty (getting ready)
                print("\nCreating morning OFF duty log")
                log_start = current_datetime
                log_end = current_datetime + timedelta(minutes=MORNING_OFF_DUTY_MINUTES)
                DrivingLog.objects.create(
                    trip=trip,
                    status='OFF',
                    location=trip.pickup_location if day == 0 else "En Route",
                    remarks='Morning routine / Breakfast',
                    start_time=log_start,
                    end_time=log_end
                )
                current_datetime = log_end

                # 2. Pre-trip inspection (ON duty)
                print("\nCreating pre-trip inspection log")
                log_start = current_datetime
                log_end = current_datetime + timedelta(minutes=PRE_TRIP_MINUTES)
                DrivingLog.objects.create(
                    trip=trip,
                    status='ON',
                    location=trip.pickup_location if day == 0 else "En Route",
                    remarks='Pre-trip inspection and safety checks',
                    start_time=log_start,
                    end_time=log_end
                )
                current_datetime = log_end

                # 3. First Driving Session (4 hours max)
                driving_hours = min(4, MAX_DRIVING_HOURS, remaining_miles / DRIVING_SPEED)
                print(f"\nCreating first driving session: {driving_hours:.2f} hours")
                log_start = current_datetime
                log_end = current_datetime + timedelta(hours=driving_hours)
                DrivingLog.objects.create(
                    trip=trip,
                    status='D',
                    location='Highway',
                    remarks='Driving session 1',
                    start_time=log_start,
                    end_time=log_end
                )
                current_datetime = log_end
                remaining_miles -= driving_hours * DRIVING_SPEED

                # 4. Break/Fuel Stop
                print(f"\nAdding break: {BREAK_TIME_MINUTES} minutes")
                log_start = current_datetime
                log_end = current_datetime + timedelta(minutes=BREAK_TIME_MINUTES)
                DrivingLog.objects.create(
                    trip=trip,
                    status='OFF',
                    location='Rest Area',
                    remarks='Fuel stop / Break',
                    start_time=log_start,
                    end_time=log_end
                )
                current_datetime = log_end

                # 5. Second Driving Session (remaining hours up to MAX_DRIVING_HOURS)
                driving_hours = min(6, MAX_DRIVING_HOURS - 4, remaining_miles / DRIVING_SPEED)
                if driving_hours > 0:
                    print(f"\nCreating second driving session: {driving_hours:.2f} hours")
                    log_start = current_datetime
                    log_end = current_datetime + timedelta(hours=driving_hours)
                    DrivingLog.objects.create(
                        trip=trip,
                        status='D',
                        location='Highway',
                        remarks='Driving session 2',
                        start_time=log_start,
                        end_time=log_end
                    )
                    current_datetime = log_end
                    remaining_miles -= driving_hours * DRIVING_SPEED

                # 6. Post-trip inspection if it's the last day
                if day == days_needed - 1:
                    print("\nCreating post-trip inspection log (last day)")
                    log_start = current_datetime
                    log_end = current_datetime + timedelta(minutes=POST_TRIP_MINUTES)
                    DrivingLog.objects.create(
                        trip=trip,
                        status='ON',
                        location=trip.dropoff_location,
                        remarks='Post-trip inspection and dropoff procedures',
                        start_time=log_start,
                        end_time=log_end
                    )
                    current_datetime = log_end

                # 7. Parking and meal time
                print(f"\nAdding parking/meal time: {PARKING_OFF_DUTY_MINUTES} minutes")
                log_start = current_datetime
                log_end = current_datetime + timedelta(minutes=PARKING_OFF_DUTY_MINUTES)
                DrivingLog.objects.create(
                    trip=trip,
                    status='OFF',
                    location='Truck Stop',
                    remarks='Parking, meal and rest',
                    start_time=log_start,
                    end_time=log_end
                )
                current_datetime = log_end

                # 8. Fill remaining time until midnight with Sleeper Berth
                if current_datetime < day_end:
                    print("\nCreating sleeper berth log for remaining time")
                    DrivingLog.objects.create(
                        trip=trip,
                        status='SB',
                        location='Truck Stop Sleeper',
                        remarks='Sleeper berth rest',
                        start_time=current_datetime,
                        end_time=day_end
                    )

                # Create daily log summary
                print("\nCreating daily log summary")
                day_logs = DrivingLog.objects.filter(trip=trip, start_time__date=day_start)
                driving_hours_total = sum((log.end_time - log.start_time).total_seconds() for log in day_logs if log.status == 'D') / 3600
                on_duty_hours_total = sum((log.end_time - log.start_time).total_seconds() for log in day_logs if log.status == 'ON') / 3600
                off_duty_hours_total = sum((log.end_time - log.start_time).total_seconds() for log in day_logs if log.status == 'OFF') / 3600
                sleeper_berth_hours_total = sum((log.end_time - log.start_time).total_seconds() for log in day_logs if log.status == 'SB') / 3600

                print(f"Day {day + 1} Summary:")
                print(f"Driving hours: {driving_hours_total:.2f}")
                print(f"On duty hours: {on_duty_hours_total:.2f}")
                print(f"Off duty hours: {off_duty_hours_total:.2f}")
                print(f"Sleeper berth hours: {sleeper_berth_hours_total:.2f}")

                DailyLogSheet.objects.create(
                    trip=trip,
                    date=day_start,
                    driving_hours=round(driving_hours_total, 2),
                    on_duty_hours=round(on_duty_hours_total, 2),
                    off_duty_hours=round(off_duty_hours_total, 2),
                    sleeper_berth_hours=round(sleeper_berth_hours_total, 2)
                )

            # Update trip status
            print("\nUpdating trip status to IN_PROGRESS")
            trip.status = 'IN_PROGRESS'
            trip.save()

            print("\n=== Trip Log Generation Complete ===")
            return Response({
                "message": "Trip logs generated successfully",
                "days_generated": days_needed,
                "total_distance": route_info['total_distance'],
                "total_driving_hours": route_info['base_driving_time'],
                "start_hours": start_hours
            }, status=status.HTTP_200_OK)

        except Trip.DoesNotExist:
            print("\nError: Trip not found")
            return Response(
                {"error": "Trip not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            print(f"\nUnexpected error: {str(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def calculate_distance(self, lat1, lon1, lat2, lon2):
        """Calculate distance between two points in miles using the Haversine formula"""
        R = 3959  # Earth's radius in miles
        
        # Convert decimal degrees to radians
        lat1, lon1, lat2, lon2 = map(math.radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
        
        # Haversine formula
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        
        # Calculate the distance
        distance = R * c
        
        return distance
