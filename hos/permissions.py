from rest_framework import permissions

class IsAdminOrSupervisor(permissions.BasePermission):
    """
    Custom permission to only allow admins or supervisors to access the view.
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated and (
            request.user.is_staff or 
            request.user.groups.filter(name='supervisors').exists()
        )

class IsDriver(permissions.BasePermission):
    """
    Custom permission to only allow drivers to access the view.
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.groups.filter(name='drivers').exists()

class IsTripDriver(permissions.BasePermission):
    """
    Custom permission to only allow the driver assigned to a trip to access it.
    """
    def has_object_permission(self, request, view, obj):
        return request.user.is_authenticated and obj.driver == request.user

class IsTripDriverOrAdmin(permissions.BasePermission):
    """
    Custom permission to allow drivers to access their assigned trips or admins to access any trip.
    """
    def has_permission(self, request, view):
        # Check if user is authenticated
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Admin and supervisors can access any trip
        if request.user.is_staff or request.user.groups.filter(name='supervisors').exists():
            return True
        
        # Drivers can access the view
        return request.user.groups.filter(name='drivers').exists()
    
    def has_object_permission(self, request, view, obj):
        # Admin and supervisors can access any trip
        if request.user.is_staff or request.user.groups.filter(name='supervisors').exists():
            return True
        
        # Drivers can only access their own trips
        return obj.driver == request.user 

class TripPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
            
        if request.method == 'POST':
            # Check if user is in any of the allowed groups
            return (
                request.user.groups.filter(name='drivers').exists() or
                request.user.groups.filter(name='supervisors').exists() or
                request.user.is_staff
            )
            
        return True 