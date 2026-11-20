from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import IsCustomer
from favourites.models import Favourite
from profiles.api.serializers import WorkerProfileSerializer
from profiles.models import WorkerProfile


class FavouriteViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated, IsCustomer]

    def list(self, request):
        worker_ids = Favourite.objects.filter(customer=request.user).values_list('worker_id', flat=True)
        workers = WorkerProfile.objects.filter(id__in=worker_ids).select_related('user').prefetch_related(
            'skills', 'worker_services__category', 'service_areas'
        )
        serializer = WorkerProfileSerializer(workers, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'], url_path='toggle')
    def toggle(self, request):
        worker_id = request.data.get('worker_id')
        if not worker_id:
            return Response({'worker_id': 'This field is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            worker = WorkerProfile.objects.get(id=worker_id)
        except WorkerProfile.DoesNotExist:
            return Response({'detail': 'Worker not found.'}, status=status.HTTP_404_NOT_FOUND)

        fav = Favourite.objects.filter(customer=request.user, worker=worker).first()
        if fav:
            fav.delete()
            return Response({'favourited': False, 'message': 'Removed from saved professionals.'})
        else:
            Favourite.objects.create(customer=request.user, worker=worker)
            return Response({'favourited': True, 'message': 'Saved to your favourites.'})
