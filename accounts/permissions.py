from rest_framework.permissions import BasePermission


class IsCustomer(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_customer)

    def has_object_permission(self, request, view, obj):
        owner_id = getattr(obj, 'user_id', getattr(obj, 'customer_id', None))
        return bool(self.has_permission(request, view) and owner_id == request.user.pk)


class IsWorker(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_worker)

    def has_object_permission(self, request, view, obj):
        owner_id = getattr(obj, 'user_id', None)
        if owner_id is None:
            owner_id = getattr(getattr(obj, 'worker', None), 'user_id', None)
        return bool(self.has_permission(request, view) and owner_id == request.user.pk)


class IsCustomerOrWorker(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_customer or request.user.is_worker)
        )


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_admin)


class IsWorkerOwner(IsWorker):
    pass


class IsCustomerOwner(IsCustomer):
    pass
