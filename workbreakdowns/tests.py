from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from categories.models import ServiceCategory
from profiles.models import WorkerProfile
from projects.models import Project
from quotations.models import JobRequest, Quotation, WorkAgreement
from services.models import Service
from workbreakdowns.models import (
    TaskTemplate,
    WorkBreakdown,
    WorkBreakdownRevision,
    WorkBreakdownTask,
)

User = get_user_model()


class WorkBreakdownWorkflowTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            email='breakdown-customer@example.com',
            phone='9200000001',
            full_name='Breakdown Customer',
            password='SecurePass123!',
            is_customer=True,
        )
        self.worker_user = User.objects.create_user(
            email='breakdown-worker@example.com',
            phone='9200000002',
            full_name='Breakdown Worker',
            password='SecurePass123!',
            is_customer=False,
            is_worker=True,
        )
        self.worker, _ = WorkerProfile.objects.get_or_create(user=self.worker_user)
        self.outsider = User.objects.create_user(
            email='breakdown-outsider@example.com',
            phone='9200000003',
            full_name='Breakdown Outsider',
            password='SecurePass123!',
            is_customer=True,
        )
        self.category = ServiceCategory.objects.create(
            name='Breakdown Electrical',
            slug='breakdown-electrical',
        )
        self.service = Service.objects.create(
            category=self.category,
            name='Breakdown Wiring',
            slug='breakdown-wiring',
        )
        self.client = APIClient()
        self.job = self.create_job()

    def create_job(self):
        self.client.force_authenticate(self.customer)
        response = self.client.post(
            '/api/quotations/jobs/',
            {
                'category_id': self.category.id,
                'service_id': self.service.id,
                'title': 'Repair a damaged circuit',
                'description': 'Inspect the circuit and replace damaged wiring.',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        return JobRequest.objects.get(pk=response.data['id'])

    def suggest(self):
        self.client.force_authenticate(self.customer)
        response = self.client.post(f'/api/workbreakdowns/jobs/{self.job.id}/suggest/')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def quote(self):
        self.client.force_authenticate(self.worker_user)
        response = self.client.post(
            '/api/quotations/',
            {
                'job_request_id': self.job.id,
                'amount': '1200.00',
                'message': 'Repair and testing.',
                'estimated_days': 2,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        return Quotation.objects.get(pk=response.data['id'])

    def test_suggestions_are_deterministic_and_use_service_specific_templates_first(self):
        generic_late = TaskTemplate.objects.create(
            category=self.category,
            title='Generic finish',
            sort_order=20,
        )
        service_late = TaskTemplate.objects.create(
            category=self.category,
            service=self.service,
            title='Service test',
            sort_order=10,
        )
        service_early = TaskTemplate.objects.create(
            category=self.category,
            service=self.service,
            title='Service inspect',
            sort_order=1,
        )
        generic_early = TaskTemplate.objects.create(
            category=self.category,
            title='Generic prepare',
            sort_order=2,
        )

        breakdown = self.suggest()

        self.assertEqual(
            [task['title'] for task in breakdown['tasks']],
            [
                service_early.title,
                service_late.title,
                generic_early.title,
                generic_late.title,
            ],
        )
        self.assertEqual(breakdown['revision_number'], 1)
        self.assertEqual(WorkBreakdownRevision.objects.filter(breakdown_id=breakdown['id']).count(), 1)
        repeated = self.client.post(f'/api/workbreakdowns/jobs/{self.job.id}/suggest/')
        self.assertEqual(repeated.status_code, 200, repeated.data)
        self.assertEqual(repeated.data['revision_number'], 1)
        self.assertEqual(WorkBreakdownTask.objects.filter(breakdown_id=breakdown['id']).count(), 4)

    def test_empty_template_catalog_falls_back_to_job_derived_editable_task(self):
        breakdown = self.suggest()
        self.assertEqual(len(breakdown['tasks']), 1)
        self.assertEqual(breakdown['tasks'][0]['title'], self.job.title)
        self.assertEqual(breakdown['tasks'][0]['description'], self.job.description)

    def test_customer_can_edit_delete_and_approve_with_immutable_revision_snapshots(self):
        breakdown = self.suggest()
        task = breakdown['tasks'][0]
        self.client.force_authenticate(self.customer)
        added = self.client.post(
            '/api/workbreakdowns/tasks/',
            {
                'breakdown_id': breakdown['id'],
                'title': 'Test the completed repair',
                'description': 'Verify the circuit under normal load.',
                'estimated_days': 1,
            },
            format='json',
        )
        self.assertEqual(added.status_code, 201, added.data)
        patched = self.client.patch(
            f"/api/workbreakdowns/tasks/{task['id']}/",
            {'title': 'Inspect all affected wiring'},
            format='json',
        )
        self.assertEqual(patched.status_code, 200, patched.data)
        self.assertEqual(patched.data['title'], 'Inspect all affected wiring')

        workspace = self.client.get(f'/api/workbreakdowns/jobs/{self.job.id}/')
        self.assertEqual(workspace.status_code, 200, workspace.data)
        self.assertEqual(workspace.data['revision_number'], 3)
        self.assertEqual(len(workspace.data['revisions']), 3)
        self.assertEqual(workspace.data['revisions'][-1]['snapshot'][0]['title'], self.job.title)

        deleted = self.client.delete(f"/api/workbreakdowns/tasks/{added.data['id']}/")
        self.assertEqual(deleted.status_code, 204)
        approved = self.client.post(f'/api/workbreakdowns/jobs/{self.job.id}/approve/')
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data['status'], WorkBreakdown.Status.APPROVED)
        self.assertEqual(approved.data['approved_revision'], 5)
        approved_revision = WorkBreakdownRevision.objects.get(
            breakdown_id=breakdown['id'],
            revision_number=5,
        )
        self.assertTrue(approved_revision.is_approved)
        self.assertEqual(len(approved_revision.snapshot), 1)
        with self.assertRaises(DjangoValidationError):
            approved_revision.save()
        with self.assertRaises(DjangoValidationError):
            approved_revision.delete()

        locked_edit = self.client.patch(
            f"/api/workbreakdowns/tasks/{task['id']}/",
            {'title': 'Attempt to change approved scope'},
            format='json',
        )
        self.assertEqual(locked_edit.status_code, 400)

    def test_owner_checks_and_quotation_lock_prevent_scope_changes(self):
        breakdown = self.suggest()
        task_id = breakdown['tasks'][0]['id']
        self.client.force_authenticate(self.outsider)
        self.assertEqual(
            self.client.get(f'/api/workbreakdowns/jobs/{self.job.id}/').status_code,
            404,
        )
        self.assertEqual(
            self.client.patch(
                f'/api/workbreakdowns/tasks/{task_id}/',
                {'title': 'Unauthorized edit'},
                format='json',
            ).status_code,
            404,
        )

        self.quote()
        self.client.force_authenticate(self.customer)
        locked = self.client.patch(
            f'/api/workbreakdowns/tasks/{task_id}/',
            {'title': 'Edit after quotation'},
            format='json',
        )
        self.assertEqual(locked.status_code, 400)
        self.assertEqual(
            self.client.post(f'/api/workbreakdowns/jobs/{self.job.id}/approve/').status_code,
            400,
        )

    def test_only_approved_snapshot_is_shared_and_used_for_agreement_project(self):
        breakdown = self.suggest()
        self.client.force_authenticate(self.customer)
        added = self.client.post(
            '/api/workbreakdowns/tasks/',
            {
                'breakdown_id': breakdown['id'],
                'title': 'Final electrical safety check',
                'description': 'Confirm the repair is safe.',
            },
            format='json',
        )
        self.assertEqual(added.status_code, 201, added.data)

        self.client.force_authenticate(self.worker_user)
        jobs = self.client.get('/api/quotations/jobs/?role=worker')
        job_data = jobs.data['results'][0]
        self.assertIsNone(job_data['work_breakdown'])
        self.assertNotIn('private', str(job_data).lower())

        self.client.force_authenticate(self.customer)
        approved = self.client.post(f'/api/workbreakdowns/jobs/{self.job.id}/approve/')
        self.assertEqual(approved.status_code, 200, approved.data)
        approved_titles = [task['title'] for task in approved.data['revisions'][0]['snapshot']]

        self.client.force_authenticate(self.worker_user)
        jobs = self.client.get('/api/quotations/jobs/?role=worker')
        worker_breakdown = jobs.data['results'][0]['work_breakdown']
        self.assertEqual(worker_breakdown['status'], WorkBreakdown.Status.APPROVED)
        self.assertEqual(
            [task['title'] for task in worker_breakdown['tasks']],
            approved_titles,
        )

        quotation = self.quote()
        self.client.force_authenticate(self.customer)
        accepted = self.client.post(f'/api/quotations/{quotation.id}/accept/')
        self.assertEqual(accepted.status_code, 201, accepted.data)
        agreement = WorkAgreement.objects.get(job_request=self.job)
        self.assertEqual(
            agreement.scope_snapshot['work_breakdown']['tasks'],
            approved.data['revisions'][0]['snapshot'],
        )
        project = Project.objects.get(agreement=agreement)
        self.assertEqual(
            list(project.tasks.values_list('title', flat=True)),
            approved_titles,
        )
