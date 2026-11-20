from datetime import time, timedelta
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Avg, Count
from django.utils import timezone
from django.utils.text import slugify
from PIL import Image, ImageDraw

from accounts.models import User
from bookings.models import Booking, BookingStatusHistory
from categories.models import ServiceCategory
from complaints.models import Complaint
from enquiries.models import Enquiry
from favourites.models import Favourite
from messaging.models import Conversation, Message
from notifications.models import Notification
from payments.models import Payment
from profiles.models import (
    Address,
    Availability,
    CustomerProfile,
    Portfolio,
    WorkerProfile,
    WorkerService,
    WorkerServiceArea,
    WorkerSkill,
)
from quotations.models import JobRequest, Quotation
from reviews.models import Review
from services.models import Service
from verification.models import VerificationDocument


CUSTOMER_DATA = {
    'email': 'demo.customer@example.invalid',
    'username': 'demo-customer',
    'phone': '9849012340',
    'full_name': 'Demo Customer - Hyderabad',
}

CATEGORY_DATA = (
    {
        'name': 'Electrical',
        'icon': 'bi-lightning-charge',
        'description': 'Electrical installation, repairs and safety checks.',
        'services': (
            ('Home wiring', 'Household wiring repairs and installation.'),
            ('Fan installation', 'Ceiling fan installation and repair.'),
        ),
    },
    {
        'name': 'Plumbing',
        'icon': 'bi-droplet',
        'description': 'Plumbing repair and maintenance for homes.',
        'services': (
            ('Tap and pipe repair', 'Repair leaking taps and household pipes.'),
            ('Bathroom plumbing', 'Bathroom fixture installation and repair.'),
        ),
    },
    {
        'name': 'AC Repair',
        'icon': 'bi-thermometer-snow',
        'description': 'Air conditioner servicing, installation and repair.',
        'services': (
            ('AC servicing', 'Routine split and window AC servicing.'),
            ('AC installation', 'Air conditioner installation and uninstallation.'),
        ),
    },
    {
        'name': 'Painting',
        'icon': 'bi-brush',
        'description': 'Interior and exterior residential painting.',
        'services': (
            ('Interior painting', 'Interior wall painting and touch-ups.'),
            ('Exterior painting', 'Exterior home painting and maintenance.'),
        ),
    },
    {
        'name': 'Cleaning',
        'icon': 'bi-stars',
        'description': 'Home and bathroom cleaning services.',
        'services': (
            ('Home deep cleaning', 'One-time deep cleaning for homes.'),
            ('Bathroom cleaning', 'Bathroom and tile cleaning.'),
        ),
    },
    {
        'name': 'Carpentry',
        'icon': 'bi-hammer',
        'description': 'Furniture, door and fixture carpentry.',
        'services': (
            ('Furniture repair', 'Repair and assembly of household furniture.'),
            ('Door repair', 'Door fitting, hinges and lock adjustments.'),
        ),
    },
)

WORKER_DATA = (
    {
        'key': 'electrician-kukatpally',
        'full_name': 'Demo Electrician - Kukatpally',
        'phone': '9849012341',
        'bio': 'Experienced certified electrician providing residential and commercial wiring, appliance installation, and switchboard repairs in Kukatpally.',
        'experience_years': 8,
        'starting_price': '250.00',
        'category': 'Electrical',
        'service': 'Home wiring',
        'locality': 'Kukatpally',
        'pincode': '500072',
        'latitude': 17.4933,
        'longitude': 78.3996,
        'radius_km': 5,
    },
    {
        'key': 'plumber-kphb',
        'full_name': 'Demo Plumber - KPHB',
        'phone': '9849012342',
        'bio': 'Reliable plumbing expert specializing in leak repairs, pipe fitting, sanitary installations, and bathroom fittings in KPHB Colony.',
        'experience_years': 6,
        'starting_price': '200.00',
        'category': 'Plumbing',
        'service': 'Tap and pipe repair',
        'locality': 'KPHB',
        'pincode': '500085',
        'latitude': 17.4938,
        'longitude': 78.4010,
        'radius_km': 5,
    },
    {
        'key': 'ac-technician-miyapur',
        'full_name': 'Demo AC Technician - Miyapur',
        'phone': '9849012343',
        'bio': 'Specialist AC technician offering split and inverter AC servicing, gas filling, cooling repairs, and deep maintenance in Miyapur.',
        'experience_years': 7,
        'starting_price': '499.00',
        'category': 'AC Repair',
        'service': 'AC servicing',
        'locality': 'Miyapur',
        'pincode': '500049',
        'latitude': 17.4968,
        'longitude': 78.3564,
        'radius_km': 8,
    },
    {
        'key': 'painter-madhapur',
        'full_name': 'Demo Painter - Madhapur',
        'phone': '9849012344',
        'bio': 'Professional home and commercial painting services, wall touch-ups, waterproof coatings, and texture finishes in Madhapur.',
        'experience_years': 10,
        'starting_price': '1500.00',
        'category': 'Painting',
        'service': 'Interior painting',
        'locality': 'Madhapur',
        'pincode': '500081',
        'latitude': 17.4483,
        'longitude': 78.3915,
        'radius_km': 10,
    },
    {
        'key': 'cleaner-kondapur',
        'full_name': 'Demo Cleaner - Kondapur',
        'phone': '9849012345',
        'bio': 'Trained deep cleaning team for apartments, deep bathroom sanitation, kitchen degreasing, and sofa shampooing in Kondapur.',
        'experience_years': 4,
        'starting_price': '999.00',
        'category': 'Cleaning',
        'service': 'Home deep cleaning',
        'locality': 'Kondapur',
        'pincode': '500084',
        'latitude': 17.4614,
        'longitude': 78.3669,
        'radius_km': 8,
    },
)

BOOKING_STATUSES = ('completed', 'confirmed', 'pending', 'cancelled', 'in_progress')


class Command(BaseCommand):
    help = 'Add idempotent Hyderabad catalog and linked demo marketplace records.'

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Sample data can only be loaded while DEBUG=True.')

        services_by_category_and_name = {}
        workers_by_key = {}
        categories_created = 0
        services_created = 0
        workers_created = 0

        for sort_order, category_data in enumerate(CATEGORY_DATA, start=1):
            category, created = ServiceCategory.objects.get_or_create(
                name=category_data['name'],
                defaults={
                    'slug': slugify(category_data['name']),
                    'icon': category_data['icon'],
                    'description': category_data['description'],
                    'sort_order': sort_order,
                },
            )
            categories_created += int(created)
            for service_name, description in category_data['services']:
                service, created = Service.objects.get_or_create(
                    category=category,
                    name=service_name,
                    defaults={
                        'slug': slugify(service_name),
                        'description': description,
                    },
                )
                services_created += int(created)
                services_by_category_and_name[(category.name, service.name)] = service

        for index, worker_data in enumerate(WORKER_DATA):
            email = f"demo.{worker_data['key']}@example.invalid"
            username = f"demo-{worker_data['key']}"
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    'username': username,
                    'phone': worker_data['phone'],
                    'full_name': worker_data['full_name'],
                    'is_customer': False,
                    'is_worker': True,
                },
            )
            if created:
                user.set_unusable_password()
                user.save(update_fields=('password',))
                workers_created += 1
            elif (
                not user.is_worker
                or user.is_staff
                or user.is_superuser
                or user.full_name != worker_data['full_name']
            ):
                raise CommandError(f'{email} is not the expected demo account; refusing to alter it.')

            avatar_path = self._ensure_file(
                f"profiles/demo/{worker_data['key']}.png",
                self._avatar_bytes(index),
            )
            if not user.profile_picture:
                user.profile_picture = avatar_path
                user.save(update_fields=('profile_picture', 'updated_at'))

            profile, _ = WorkerProfile.objects.get_or_create(
                user=user,
                defaults={
                    'bio': worker_data['bio'],
                    'experience_years': worker_data['experience_years'],
                    'starting_price': Decimal(worker_data['starting_price']),
                    'pricing_type': 'starting_from',
                    'is_available': True,
                    'verification_status': 'unverified',
                },
            )
            workers_by_key[worker_data['key']] = (user, profile)
            category = ServiceCategory.objects.get(name=worker_data['category'])
            service = services_by_category_and_name[(category.name, worker_data['service'])]
            WorkerService.objects.get_or_create(
                worker=profile,
                category=category,
                service=service,
                defaults={
                    'description': worker_data['bio'],
                    'price': Decimal(worker_data['starting_price']),
                    'is_primary': True,
                },
            )
            WorkerSkill.objects.get_or_create(worker=profile, name=category.name)
            WorkerServiceArea.objects.get_or_create(
                worker=profile,
                locality=worker_data['locality'],
                city='Hyderabad',
                defaults={
                    'state': 'Telangana',
                    'pincode': worker_data['pincode'],
                    'latitude': worker_data['latitude'],
                    'longitude': worker_data['longitude'],
                    'radius_km': worker_data['radius_km'],
                },
            )
            Availability.objects.get_or_create(
                worker=profile,
                day_of_week=0,
                start_time=time(9, 0),
                defaults={'end_time': time(17, 0), 'is_available': True},
            )

        self._seed_marketplace_records(services_by_category_and_name, workers_by_key)
        self.stdout.write(self.style.SUCCESS(
            'Hyderabad seed complete: '
            f'{categories_created} categories, {services_created} services, '
            f'{workers_created} demo workers created, plus linked sample records for all marketplace models. '
            'Existing matching records were kept.'
        ))
        self.stdout.write(
            'Demo accounts cannot log in. Listings, addresses, reviews, messages, documents, complaints, and payments '
            'are synthetic; payment records are not settled and verification files are not valid evidence.'
        )

    def _seed_marketplace_records(self, services, workers):
        customer, created = User.objects.get_or_create(
            email=CUSTOMER_DATA['email'],
            defaults={
                'username': CUSTOMER_DATA['username'],
                'phone': CUSTOMER_DATA['phone'],
                'full_name': CUSTOMER_DATA['full_name'],
                'is_customer': True,
                'is_worker': False,
            },
        )
        if created:
            customer.set_unusable_password()
            customer.save(update_fields=('password',))
        elif (
            not customer.is_customer
            or customer.is_staff
            or customer.is_superuser
        ):
            raise CommandError('The expected demo customer identity is already used by another account.')

        CustomerProfile.objects.get_or_create(user=customer)
        address, _ = Address.objects.get_or_create(
            user=customer,
            label='Demo service location',
            defaults={
                'address_line1': 'DEMO DATA - Sample address, not a real residence',
                'locality': 'Kukatpally',
                'city': 'Hyderabad',
                'state': 'Telangana',
                'pincode': '500072',
                'latitude': Decimal('17.484000'),
                'longitude': Decimal('78.392000'),
                'is_default': True,
            },
        )

        image_buffer = BytesIO()
        Image.new('RGB', (1, 1), (255, 122, 36)).save(image_buffer, format='PNG')
        portfolio_file = self._ensure_file('portfolio/demo/sample-work.png', image_buffer.getvalue())
        verification_file = self._ensure_file(
            'verification/demo/sample-document.txt',
            b'DEMO DATA ONLY. This is not identity, address, skill, or business evidence.\n',
        )

        today = timezone.localdate()
        completed_booking = None
        completed_enquiry = None
        for index, (worker_data, status_value) in enumerate(zip(WORKER_DATA, BOOKING_STATUSES)):
            user, worker = workers[worker_data['key']]
            category = ServiceCategory.objects.get(name=worker_data['category'])
            service = services[(category.name, worker_data['service'])]
            enquiry = None
            if index == 0:
                enquiry, _ = Enquiry.objects.get_or_create(
                    customer=customer,
                    worker=worker,
                    subject='DEMO DATA - Home wiring service',
                    defaults={
                        'category': category,
                        'service': service,
                        'address': address,
                        'message': 'DEMO DATA only - sample enquiry for local development.',
                        'contact_preference': Enquiry.ContactPreference.CHAT,
                        'status': Enquiry.Status.CONVERTED,
                    },
                )
                completed_enquiry = enquiry
            elif index == 1:
                Enquiry.objects.get_or_create(
                    customer=customer,
                    worker=worker,
                    subject='DEMO DATA - Tap repair question',
                    defaults={
                        'category': category,
                        'service': service,
                        'address': address,
                        'message': 'DEMO DATA only - sample enquiry for local development.',
                        'contact_preference': Enquiry.ContactPreference.CHAT,
                        'status': Enquiry.Status.PENDING,
                    },
                )

            marker = f"DEMO DATA - sample booking for {worker_data['key']}"
            scheduled_date = (
                today - timedelta(days=7 + index)
                if status_value == Booking.Status.COMPLETED
                else today + timedelta(days=index + 1)
            )
            booking, booking_created = Booking.objects.get_or_create(
                customer=customer,
                worker=worker,
                customer_notes=marker,
                defaults={
                    'service': service,
                    'enquiry': enquiry,
                    'address': address,
                    'scheduled_date': scheduled_date,
                    'scheduled_time': time(10, 0),
                    'estimated_amount': Decimal(worker_data['starting_price']),
                    'final_amount': (
                        Decimal(worker_data['starting_price'])
                        if status_value == Booking.Status.COMPLETED else None
                    ),
                    'status': status_value,
                    'completed_at': (
                        timezone.now() if status_value == Booking.Status.COMPLETED else None
                    ),
                    'cancelled_at': (
                        timezone.now() if status_value == Booking.Status.CANCELLED else None
                    ),
                    'cancellation_reason': (
                        'DEMO DATA - sample cancellation.' if status_value == Booking.Status.CANCELLED else ''
                    ),
                },
            )
            if booking_created:
                status_sequences = {
                    Booking.Status.PENDING: (Booking.Status.PENDING,),
                    Booking.Status.CONFIRMED: (Booking.Status.PENDING, Booking.Status.CONFIRMED),
                    Booking.Status.IN_PROGRESS: (
                        Booking.Status.PENDING, Booking.Status.CONFIRMED, Booking.Status.IN_PROGRESS,
                    ),
                    Booking.Status.COMPLETED: (
                        Booking.Status.PENDING, Booking.Status.CONFIRMED,
                        Booking.Status.IN_PROGRESS, Booking.Status.COMPLETED,
                    ),
                    Booking.Status.CANCELLED: (Booking.Status.PENDING, Booking.Status.CANCELLED),
                }
                previous_status = ''
                for history_status in status_sequences[status_value]:
                    BookingStatusHistory.objects.get_or_create(
                        booking=booking,
                        new_status=history_status,
                        defaults={
                            'changed_by': customer if not previous_status else user,
                            'previous_status': previous_status,
                            'note': f'DEMO DATA - status changed to {history_status}.',
                        },
                    )
                    previous_status = history_status
            if status_value == Booking.Status.COMPLETED:
                completed_booking = booking
                if enquiry and enquiry.status != Enquiry.Status.CONVERTED:
                    enquiry.status = Enquiry.Status.CONVERTED
                    enquiry.save(update_fields=('status', 'updated_at'))

            Portfolio.objects.get_or_create(
                worker=worker,
                title=f"DEMO DATA - Sample {worker_data['category']} work",
                defaults={
                    'description': 'Synthetic portfolio item for local development only.',
                    'image': portfolio_file,
                },
            )
            VerificationDocument.objects.get_or_create(
                worker=worker,
                document_type=VerificationDocument.DocumentType.OTHER,
                document=verification_file,
                defaults={
                    'status': VerificationDocument.Status.PENDING,
                },
            )

            self._create_notification(
                recipient=user,
                notification_type=Notification.NotificationType.BOOKING,
                title=f"DEMO DATA - Sample {status_value.replace('_', ' ')} booking",
                body='Synthetic notification for local development only.',
                data={'booking_id': booking.pk},
            )

        if completed_booking is None:
            raise CommandError('The Hyderabad demo booking scenario requires a completed booking.')

        Review.objects.get_or_create(
            booking=completed_booking,
            defaults={
                'customer': customer,
                'worker': completed_booking.worker,
                'rating': 5,
                'title': 'DEMO DATA - Sample review',
                'comment': 'Synthetic review for local development only.',
                'is_public': True,
            },
        )
        for _, worker in workers.values():
            review_totals = Review.objects.filter(worker=worker, is_public=True).aggregate(
                average=Avg('rating'),
                total=Count('id'),
            )
            WorkerProfile.objects.filter(pk=worker.pk).update(
                average_rating=review_totals['average'] or Decimal('0.00'),
                total_reviews=review_totals['total'],
                total_bookings=Booking.objects.filter(
                    worker=worker,
                    status=Booking.Status.COMPLETED,
                ).count(),
            )

        Favourite.objects.get_or_create(customer=customer, worker=completed_booking.worker)
        JobRequest.objects.get_or_create(
            customer=customer,
            title='DEMO DATA - Small electrical repair job',
            defaults={
                'category': completed_booking.service.category,
                'service': completed_booking.service,
                'address': address,
                'description': 'Synthetic job request for local development only.',
                'budget_min': Decimal('200.00'),
                'budget_max': Decimal('1000.00'),
                'preferred_date': today + timedelta(days=5),
                'status': JobRequest.Status.OPEN,
            },
        )
        job_request = JobRequest.objects.get(
            customer=customer,
            title='DEMO DATA - Small electrical repair job',
        )
        quotation_worker = completed_booking.worker
        Quotation.objects.get_or_create(
            job_request=job_request,
            worker=quotation_worker,
            defaults={
                'amount': Decimal('500.00'),
                'message': 'DEMO DATA only - synthetic quotation.',
                'estimated_days': 1,
                'status': Quotation.Status.PENDING,
                'valid_until': timezone.now() + timedelta(days=7),
            },
        )

        conversation, _ = Conversation.objects.get_or_create(
            customer=customer,
            worker=completed_booking.worker,
            enquiry=completed_enquiry,
            defaults={'is_active': True},
        )
        Message.objects.get_or_create(
            conversation=conversation,
            sender=customer,
            body='DEMO DATA only - sample customer message.',
        )
        Message.objects.get_or_create(
            conversation=conversation,
            sender=completed_booking.worker.user,
            body='DEMO DATA only - sample worker reply.',
        )
        self._create_notification(
            recipient=customer,
            notification_type=Notification.NotificationType.REVIEW,
            title='DEMO DATA - Sample review notification',
            body='Synthetic notification for local development only.',
            data={'booking_id': completed_booking.pk},
        )

        Complaint.objects.get_or_create(
            booking=completed_booking,
            raised_by=customer,
            against_user=completed_booking.worker.user,
            subject='DEMO DATA - Sample service complaint',
            defaults={
                'category': Complaint.Category.OTHER,
                'description': 'Synthetic complaint for local development only.',
                'status': Complaint.Status.OPEN,
            },
        )
        Payment.objects.get_or_create(
            booking=completed_booking,
            customer=customer,
            receipt='DEMO-LOCAL-NOT-A-REAL-PAYMENT',
            defaults={
                'amount': completed_booking.final_amount or Decimal('0.00'),
                'currency': 'INR',
                'method': Payment.Method.CASH,
                'status': Payment.Status.CREATED,
            },
        )

    @staticmethod
    def _ensure_file(path, content):
        if default_storage.exists(path):
            with default_storage.open(path, 'rb') as existing_file:
                if existing_file.read() == content:
                    return path
            default_storage.delete(path)
        return default_storage.save(path, ContentFile(content))

    @staticmethod
    def _avatar_bytes(index):
        palettes = (
            ((230, 241, 250), (36, 91, 133), (179, 118, 79), (43, 48, 61)),
            ((236, 245, 239), (53, 117, 91), (133, 87, 61), (55, 42, 37)),
            ((255, 239, 222), (207, 105, 48), (198, 143, 101), (47, 42, 39)),
            ((241, 235, 250), (112, 82, 147), (153, 101, 69), (42, 38, 45)),
            ((232, 244, 246), (45, 122, 132), (189, 132, 91), (52, 45, 41)),
        )
        background, clothing, skin, hair = palettes[index % len(palettes)]
        image = Image.new('RGB', (320, 320), background)
        draw = ImageDraw.Draw(image)
        draw.ellipse((28, 28, 292, 292), fill=(255, 255, 255))
        draw.ellipse((91, 68, 229, 206), fill=skin)
        draw.pieslice((87, 53, 233, 202), 180, 360, fill=hair)
        draw.rounded_rectangle((143, 185, 177, 229), radius=12, fill=skin)
        draw.ellipse((61, 190, 259, 365), fill=clothing)
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        return buffer.getvalue()

    @staticmethod
    def _create_notification(recipient, notification_type, title, body, data):
        Notification.objects.get_or_create(
            recipient=recipient,
            notification_type=notification_type,
            title=title,
            defaults={'body': body, 'data': data},
        )
