# seed_trip.py

import os
import django
import math
from datetime import datetime, timedelta

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Spotter_HOS.settings')  # <-- change 'your_project_name'
django.setup()

from hos.models import Trip, DrivingLog, DailyLogSheet

# === CONFIGURATION ===
PICKUP = "New York, NY"
DROPOFF = "Los Angeles, CA"
TOTAL_MILES = 2800
DRIVING_SPEED = 60  # avg speed in miles/hour
MAX_DRIVING_HOURS = 11
BREAK_TIME_MINUTES = 30
PRE_TRIP_MINUTES = 30
POST_TRIP_MINUTES = 30
MORNING_OFF_DUTY_MINUTES = 30
PARKING_OFF_DUTY_MINUTES = 30

START_DATE = datetime(2025, 4, 26, 7, 0)  # Starting at 7 AM

# === Create Trip ===
trip = Trip.objects.create(
    pickup_location=PICKUP,
    dropoff_location=DROPOFF,
    current_location=PICKUP,
    current_cycle_used=0,
    status="IN_PROGRESS"
)

print(f"Created Trip ID: {trip.id}")

# === Generate Logs ===
remaining_miles = TOTAL_MILES
current_datetime = START_DATE
first_day = True

while remaining_miles > 0:
    day_start = current_datetime.date()

    # If first day, fill missing midnight to start time with OFF duty
    if first_day and current_datetime.time() != datetime.min.time():
        midnight = datetime.combine(current_datetime.date(), datetime.min.time())
        DrivingLog.objects.create(
            trip=trip,
            status='OFF',
            location=trip.current_location,
            remarks='Off duty before trip start',
            start_time=midnight,
            end_time=current_datetime
        )
        first_day = False

    # 1. Morning OFF Duty (getting ready)
    log_start = current_datetime
    log_end = current_datetime + timedelta(minutes=MORNING_OFF_DUTY_MINUTES)
    DrivingLog.objects.create(
        trip=trip,
        status='OFF',
        location=trip.current_location,
        remarks='Morning routine / Breakfast',
        start_time=log_start,
        end_time=log_end
    )
    current_datetime = log_end

    # 2. ON Duty (pre-trip inspection)
    log_start = current_datetime
    log_end = current_datetime + timedelta(minutes=PRE_TRIP_MINUTES)
    DrivingLog.objects.create(
        trip=trip,
        status='ON',
        location=trip.current_location,
        remarks='Pre-trip TIV Inspection',
        start_time=log_start,
        end_time=log_end
    )
    current_datetime = log_end

    # 3. Driving Session 1
    driving_hours = min(4, MAX_DRIVING_HOURS, remaining_miles / DRIVING_SPEED)
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

    # 4. OFF Duty (Break/Fuel)
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

    # 5. Driving Session 2
    driving_hours = min(6, MAX_DRIVING_HOURS, remaining_miles / DRIVING_SPEED)
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

    # 6. ON Duty (Post-trip inspection)
    log_start = current_datetime
    log_end = current_datetime + timedelta(minutes=POST_TRIP_MINUTES)
    DrivingLog.objects.create(
        trip=trip,
        status='ON',
        location='Truck Stop',
        remarks='Post-trip TIV Inspection',
        start_time=log_start,
        end_time=log_end
    )
    current_datetime = log_end

    # 7. OFF Duty (Parking and meal)
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

    # 8. Sleeper Berth (fill remaining time until midnight)
    end_of_day = datetime.combine(current_datetime.date(), datetime.min.time()) + timedelta(days=1)
    if current_datetime < end_of_day:
        DrivingLog.objects.create(
            trip=trip,
            status='SB',
            location='Truck Stop Sleeper',
            remarks='Sleeper berth rest',
            start_time=current_datetime,
            end_time=end_of_day
        )
        current_datetime = end_of_day

    # === Daily Log Summary ===
    day_logs = DrivingLog.objects.filter(trip=trip, date=day_start)

    driving_hours_total = sum((log.end_time - log.start_time).total_seconds() for log in day_logs if log.status == 'D') / 3600
    on_duty_hours_total = sum((log.end_time - log.start_time).total_seconds() for log in day_logs if log.status == 'ON') / 3600
    off_duty_hours_total = sum((log.end_time - log.start_time).total_seconds() for log in day_logs if log.status == 'OFF') / 3600
    sleeper_berth_hours_total = sum((log.end_time - log.start_time).total_seconds() for log in day_logs if log.status == 'SB') / 3600

    total_hours = driving_hours_total + on_duty_hours_total + off_duty_hours_total + sleeper_berth_hours_total

    if abs(total_hours - 24.0) > 0.05:
        raise Exception(f"Invalid total hours for {day_start}: {total_hours:.2f} hours (should be 24.00)")

    DailyLogSheet.objects.create(
        trip=trip,
        date=day_start,
        driving_hours=round(driving_hours_total, 2),
        on_duty_hours=round(on_duty_hours_total, 2),
        off_duty_hours=round(off_duty_hours_total, 2),
        sleeper_berth_hours=round(sleeper_berth_hours_total, 2)
    )

# === Mark Trip as Completed ===
trip.current_location = DROPOFF
trip.status = 'COMPLETED'
trip.save()

print(f"Trip {trip.id} completed and logs generated.")
