from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from profiles.models import (
    Address,
    Availability,
    CustomerProfile,
    Portfolio,
    WorkerProfile,
    WorkerService,
    WorkerServiceArea,
)
from profiles.api.serializers import (
    AddressSerializer,
    AvailabilityManagementSerializer,
    CustomerProfileSerializer,
    PortfolioManagementSerializer,
    WorkerProfileSerializer,
    WorkerServiceAreaManagementSerializer,
    WorkerServiceManagementSerializer,
)
from accounts.permissions import IsCustomer, IsWorker


class CustomerProfileView(APIView):
    permission_classes = [IsCustomer]
    serializer_class = CustomerProfileSerializer

    def get(self, request, *args, **kwargs):
        profile, _ = CustomerProfile.objects.get_or_create(user=request.user)
        serializer = CustomerProfileSerializer(profile)
        return Response(serializer.data)

    def patch(self, request, *args, **kwargs):
        profile, _ = CustomerProfile.objects.get_or_create(user=request.user)
        serializer = CustomerProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AddressViewSet(viewsets.ModelViewSet):
    permission_classes = [IsCustomer]
    serializer_class = AddressSerializer
    queryset = Address.objects.none()

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return self.queryset
        return Address.objects.filter(user=self.request.user).order_by('-is_default', '-created_at')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class WorkerProfileViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = WorkerProfile.objects.filter(user__is_active=True).select_related('user').prefetch_related(
        'skills', 'worker_services__category', 'worker_services__service',
        'service_areas', 'portfolio_items', 'availability_slots'
    ).order_by('user__full_name')
    serializer_class = WorkerProfileSerializer
    permission_classes = [permissions.AllowAny]

    @action(detail=False, methods=['get', 'patch'], permission_classes=[IsWorker])
    def me(self, request, *args, **kwargs):
        profile, _ = WorkerProfile.objects.get_or_create(user=request.user)

        if request.method == 'PATCH':
            serializer = WorkerProfileSerializer(profile, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response(WorkerProfileSerializer(profile).data)


class WorkerOwnedAPIView:
    permission_classes = [IsWorker]

    def get_worker_profile(self):
        profile, _ = WorkerProfile.objects.get_or_create(user=self.request.user)
        return profile

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.user.is_authenticated:
            context['worker_profile'] = self.get_worker_profile()
        return context


class WorkerServiceListCreateView(WorkerOwnedAPIView, generics.ListCreateAPIView):
    serializer_class = WorkerServiceManagementSerializer
    queryset = WorkerService.objects.none()

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return self.queryset
        return WorkerService.objects.filter(worker__user=self.request.user).select_related(
            'category', 'service'
        ).order_by('category__name', 'service__name')

    def perform_create(self, serializer):
        serializer.save(worker=self.get_worker_profile())


class WorkerServiceDetailView(WorkerOwnedAPIView, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = WorkerServiceManagementSerializer
    queryset = WorkerService.objects.none()

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return self.queryset
        return WorkerService.objects.filter(worker__user=self.request.user).select_related(
            'category', 'service'
        )


class WorkerServiceAreaListCreateView(WorkerOwnedAPIView, generics.ListCreateAPIView):
    serializer_class = WorkerServiceAreaManagementSerializer
    queryset = WorkerServiceArea.objects.none()

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return self.queryset
        return WorkerServiceArea.objects.filter(worker__user=self.request.user).order_by(
            'city', 'locality'
        )

    def perform_create(self, serializer):
        serializer.save(worker=self.get_worker_profile())


class WorkerServiceAreaDetailView(WorkerOwnedAPIView, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = WorkerServiceAreaManagementSerializer
    queryset = WorkerServiceArea.objects.none()

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return self.queryset
        return WorkerServiceArea.objects.filter(worker__user=self.request.user)


class WorkerAvailabilityListCreateView(WorkerOwnedAPIView, generics.ListCreateAPIView):
    serializer_class = AvailabilityManagementSerializer
    queryset = Availability.objects.none()

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return self.queryset
        return Availability.objects.filter(worker__user=self.request.user).order_by(
            'day_of_week', 'start_time'
        )

    def perform_create(self, serializer):
        serializer.save(worker=self.get_worker_profile())


class WorkerAvailabilityDetailView(WorkerOwnedAPIView, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = AvailabilityManagementSerializer
    queryset = Availability.objects.none()

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return self.queryset
        return Availability.objects.filter(worker__user=self.request.user)


class WorkerPortfolioListCreateView(WorkerOwnedAPIView, generics.ListCreateAPIView):
    serializer_class = PortfolioManagementSerializer
    queryset = Portfolio.objects.none()

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return self.queryset
        return Portfolio.objects.filter(worker__user=self.request.user).order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(worker=self.get_worker_profile())


class WorkerPortfolioDetailView(WorkerOwnedAPIView, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PortfolioManagementSerializer
    queryset = Portfolio.objects.none()

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return self.queryset
        return Portfolio.objects.filter(worker__user=self.request.user)
