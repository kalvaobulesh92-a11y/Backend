from rest_framework import serializers

from bookings.api.serializers import BookingServiceSummarySerializer, BookingWorkerSummarySerializer
from categories.models import ServiceCategory
from enquiries.models import Enquiry
from profiles.api.serializers import AddressSerializer, UserSummarySerializer
from profiles.models import Address, WorkerProfile
from services.models import Service


class EnquirySerializer(serializers.ModelSerializer):
    customer = UserSummarySerializer(read_only=True)
    worker = BookingWorkerSummarySerializer(read_only=True)
    service = BookingServiceSummarySerializer(read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    address = AddressSerializer(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    contact_preference_display = serializers.CharField(source='get_contact_preference_display', read_only=True)

    class Meta:
        model = Enquiry
        fields = (
            'id', 'customer', 'worker', 'category', 'category_name', 'service',
            'address', 'subject', 'message', 'preferred_date',
            'contact_preference', 'contact_preference_display',
            'status', 'status_display', 'created_at', 'updated_at',
        )
        read_only_fields = fields


class EnquiryCreateSerializer(serializers.ModelSerializer):
    worker_id = serializers.PrimaryKeyRelatedField(
        queryset=WorkerProfile.objects.filter(user__is_active=True),
        source='worker',
        write_only=True,
    )
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=ServiceCategory.objects.all(),
        source='category',
        write_only=True,
        required=False,
    )
    service_id = serializers.PrimaryKeyRelatedField(
        queryset=Service.objects.all(),
        source='service',
        write_only=True,
        required=False,
        allow_null=True,
    )
    address_id = serializers.PrimaryKeyRelatedField(
        queryset=Address.objects.all(),
        source='address',
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Enquiry
        fields = (
            'id', 'worker_id', 'category_id', 'service_id', 'address_id',
            'subject', 'message', 'preferred_date', 'contact_preference',
        )
        read_only_fields = ('id',)

    def validate(self, attrs):
        service = attrs.get('service')
        category = attrs.get('category')
        if service and not category:
            attrs['category'] = service.category
        elif service and category and service.category_id != category.id:
            raise serializers.ValidationError({'service_id': 'Selected service does not belong to the selected category.'})

        if not attrs.get('category'):
            # If neither service nor category provided, check if worker has a primary service/category
            worker = attrs.get('worker')
            ws = worker.worker_services.first() if worker else None
            if ws:
                attrs['category'] = ws.category
                if not attrs.get('service'):
                    attrs['service'] = ws.service
            else:
                raise serializers.ValidationError({'category_id': 'Category is required for enquiries.'})

        request = self.context.get('request')
        user = request.user if request else None
        worker = attrs.get('worker')
        if worker and user and worker.user_id == user.id:
            raise serializers.ValidationError({'worker_id': 'You cannot send an enquiry to your own profile.'})

        return attrs


class EnquiryStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Enquiry.Status.choices)
