from django.db import transaction

from projects.models import Project, ProjectTask


@transaction.atomic
def create_project_for_agreement(agreement):
    project, created = Project.objects.get_or_create(
        agreement=agreement,
        defaults={
            'title': agreement.scope_snapshot['title'],
            'description': agreement.scope_snapshot['description'],
        },
    )
    if created:
        approved_tasks = agreement.scope_snapshot.get('work_breakdown', {}).get('tasks', [])
        if approved_tasks:
            for task in approved_tasks:
                ProjectTask.objects.create(
                    project=project,
                    title=task['title'],
                    description=task.get('description', ''),
                    sort_order=task['sort_order'],
                    created_by=agreement.customer,
                )
        else:
            ProjectTask.objects.create(
                project=project,
                title=project.title,
                description=project.description,
                sort_order=0,
                created_by=agreement.customer,
            )
    return project
