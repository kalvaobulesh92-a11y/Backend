from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from categories.models import ServiceCategory
from projects.models import Project, ProjectTask, TaskUpdate
from profiles.models import WorkerProfile
from quotations.models import JobRequest, Quotation
from services.models import Service

User = get_user_model()


class ProjectWorkflowTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            email='project-customer@example.com',
            phone='9100000001',
            full_name='Project Customer',
            password='SecurePass123!',
            is_customer=True,
        )
        self.worker_user = User.objects.create_user(
            email='project-worker@example.com',
            phone='9100000002',
            full_name='Project Worker',
            password='SecurePass123!',
            is_customer=False,
            is_worker=True,
        )
        self.worker, _ = WorkerProfile.objects.get_or_create(user=self.worker_user)
        self.other_user = User.objects.create_user(
            email='project-outsider@example.com',
            phone='9100000003',
            full_name='Project Outsider',
            password='SecurePass123!',
            is_customer=True,
        )
        self.category = ServiceCategory.objects.create(name='Project Electrical', slug='project-electrical')
        self.service = Service.objects.create(
            category=self.category,
            name='Project Wiring',
            slug='project-wiring',
        )
        self.client = APIClient()

    def create_agreed_project(self):
        self.client.force_authenticate(self.customer)
        job_response = self.client.post(
            '/api/quotations/jobs/',
            {
                'category_id': self.category.id,
                'service_id': self.service.id,
                'title': 'Install new wiring',
                'description': 'Wire the kitchen and two bedrooms.',
            },
            format='json',
        )
        self.assertEqual(job_response.status_code, 201, job_response.data)
        job = JobRequest.objects.get(pk=job_response.data['id'])

        self.client.force_authenticate(self.worker_user)
        quote_response = self.client.post(
            '/api/quotations/',
            {
                'job_request_id': job.id,
                'amount': '2500.00',
                'message': 'Includes installation and testing.',
                'estimated_days': 3,
            },
            format='json',
        )
        self.assertEqual(quote_response.status_code, 201, quote_response.data)
        quotation = Quotation.objects.get(pk=quote_response.data['id'])

        self.client.force_authenticate(self.customer)
        agreement_response = self.client.post(f'/api/quotations/{quotation.id}/accept/')
        self.assertEqual(agreement_response.status_code, 201, agreement_response.data)
        project = Project.objects.get(agreement__job_request=job)
        return job, quotation, project

    def test_acceptance_creates_project_and_parties_can_track_task_lifecycle(self):
        job, _, project = self.create_agreed_project()
        task = project.tasks.get()
        self.assertEqual(project.title, job.title)
        self.assertEqual(task.title, job.title)

        self.client.force_authenticate(self.other_user)
        self.assertEqual(self.client.get(f'/api/projects/{project.id}/').status_code, 404)
        self.assertEqual(
            self.client.post(
                f'/api/projects/tasks/{task.id}/transition/',
                {'transition': 'start'},
                format='json',
            ).status_code,
            404,
        )

        self.client.force_authenticate(self.customer)
        customer_start = self.client.post(
            f'/api/projects/tasks/{task.id}/transition/',
            {'transition': 'start'},
            format='json',
        )
        self.assertEqual(customer_start.status_code, 403)

        self.client.force_authenticate(self.worker_user)
        started = self.client.post(
            f'/api/projects/tasks/{task.id}/transition/',
            {'transition': 'start'},
            format='json',
        )
        self.assertEqual(started.status_code, 200, started.data)
        self.assertEqual(started.data['status'], ProjectTask.Status.IN_PROGRESS)
        self.assertEqual(
            Project.objects.get(pk=project.pk).status,
            Project.Status.IN_PROGRESS,
        )
        missing_note = self.client.post(
            f'/api/projects/tasks/{task.id}/transition/',
            {'transition': 'submit'},
            format='json',
        )
        self.assertEqual(missing_note.status_code, 400)
        submitted = self.client.post(
            f'/api/projects/tasks/{task.id}/transition/',
            {'transition': 'submit', 'note': 'Installation is ready for inspection.'},
            format='json',
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(submitted.data['status'], ProjectTask.Status.SUBMITTED)

        self.client.force_authenticate(self.customer)
        changes = self.client.post(
            f'/api/projects/tasks/{task.id}/transition/',
            {'transition': 'request_changes', 'note': 'Please secure the exposed conduit.'},
            format='json',
        )
        self.assertEqual(changes.status_code, 200, changes.data)
        self.assertEqual(changes.data['status'], ProjectTask.Status.CHANGES_REQUESTED)

        self.client.force_authenticate(self.worker_user)
        self.assertEqual(
            self.client.post(
                f'/api/projects/tasks/{task.id}/transition/',
                {'transition': 'start'},
                format='json',
            ).data['status'],
            ProjectTask.Status.IN_PROGRESS,
        )
        self.assertEqual(
            self.client.post(
                f'/api/projects/tasks/{task.id}/transition/',
                {'transition': 'submit', 'note': 'Conduit secured and rechecked.'},
                format='json',
            ).status_code,
            200,
        )

        self.client.force_authenticate(self.worker_user)
        forbidden_approval = self.client.post(
            f'/api/projects/tasks/{task.id}/transition/',
            {'transition': 'approve'},
            format='json',
        )
        self.assertEqual(forbidden_approval.status_code, 403)
        self.client.force_authenticate(self.customer)
        approved = self.client.post(
            f'/api/projects/tasks/{task.id}/transition/',
            {'transition': 'approve', 'note': 'Work verified.'},
            format='json',
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data['status'], ProjectTask.Status.APPROVED)
        self.assertEqual(
            Project.objects.get(pk=project.pk).status,
            Project.Status.COMPLETED,
        )
        self.assertEqual(TaskUpdate.objects.filter(task=task).count(), 6)

    def test_project_parties_can_add_checklist_tasks_and_tasks_are_ordered(self):
        _, _, project = self.create_agreed_project()
        self.client.force_authenticate(self.worker_user)
        response = self.client.post(
            f'/api/projects/{project.id}/tasks/',
            {'title': 'Test each electrical circuit', 'description': 'Record the final checks.'},
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['sort_order'], 1)
        self.assertEqual(response.data['created_by_name'], 'Project Worker')

        self.client.force_authenticate(self.customer)
        listed = self.client.get(f'/api/projects/{project.id}/tasks/')
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([task['sort_order'] for task in listed.data], [0, 1])

