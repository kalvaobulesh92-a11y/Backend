from django.contrib import admin
from projects.models import Project, ProjectTask, TaskUpdate


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'status', 'created_at', 'completed_at')
    list_filter = ('status', 'created_at')
    search_fields = ('title', 'description', 'agreement__customer__full_name')
    readonly_fields = tuple(field.name for field in Project._meta.fields)

    def has_add_permission(self, request):
        return False


@admin.register(ProjectTask)
class ProjectTaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'project', 'title', 'status', 'sort_order')
    list_filter = ('status',)
    search_fields = ('title', 'description', 'project__title')
    readonly_fields = tuple(field.name for field in ProjectTask._meta.fields)

    def has_add_permission(self, request):
        return False


@admin.register(TaskUpdate)
class TaskUpdateAdmin(admin.ModelAdmin):
    list_display = ('id', 'task', 'actor', 'from_status', 'to_status', 'created_at')
    list_filter = ('to_status', 'created_at')
    readonly_fields = tuple(field.name for field in TaskUpdate._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
