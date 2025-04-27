from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from hos.models import Trip, DrivingLog, DailyLogSheet

class Command(BaseCommand):
    help = 'Sets up the initial user groups for the HOS application'

    def handle(self, *args, **options):
        # Create groups
        supervisors_group, created = Group.objects.get_or_create(name='supervisors')
        drivers_group, created = Group.objects.get_or_create(name='drivers')
        
        # Get content types
        trip_ct = ContentType.objects.get_for_model(Trip)
        driving_log_ct = ContentType.objects.get_for_model(DrivingLog)
        daily_log_ct = ContentType.objects.get_for_model(DailyLogSheet)
        
        # Get permissions
        trip_permissions = Permission.objects.filter(content_type=trip_ct)
        driving_log_permissions = Permission.objects.filter(content_type=driving_log_ct)
        daily_log_permissions = Permission.objects.filter(content_type=daily_log_ct)
        
        # Assign permissions to supervisors group
        for perm in trip_permissions:
            supervisors_group.permissions.add(perm)
        
        for perm in driving_log_permissions:
            supervisors_group.permissions.add(perm)
            
        for perm in daily_log_permissions:
            supervisors_group.permissions.add(perm)
        
        # Assign limited permissions to drivers group
        # Drivers can only view and change their own trips
        view_trip = Permission.objects.get(content_type=trip_ct, codename='view_trip')
        change_trip = Permission.objects.get(content_type=trip_ct, codename='change_trip')
        add_driving_log = Permission.objects.get(content_type=driving_log_ct, codename='add_drivinglog')
        view_driving_log = Permission.objects.get(content_type=driving_log_ct, codename='view_drivinglog')
        view_daily_log = Permission.objects.get(content_type=daily_log_ct, codename='view_dailylogsheet')
        
        drivers_group.permissions.add(view_trip, change_trip, add_driving_log, view_driving_log, view_daily_log)
        
        self.stdout.write(self.style.SUCCESS('Successfully set up user groups')) 