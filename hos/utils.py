from datetime import timedelta
from django.utils import timezone
from hos.models import Trip

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