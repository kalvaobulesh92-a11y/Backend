import re

from django.db import migrations, models


def populate_usernames(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    used_usernames = set()

    for user in User.objects.only('pk', 'email').order_by('pk').iterator():
        base = re.sub(r'[^a-z0-9._-]', '', user.email.split('@', 1)[0].lower())[:140] or 'user'
        username = base
        suffix = 1
        while username.casefold() in used_usernames:
            username = f'{base[:140]}-{suffix}'
            suffix += 1
        used_usernames.add(username.casefold())
        User.objects.filter(pk=user.pk).update(username=username)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='username',
            field=models.CharField(blank=True, max_length=150, null=True),
        ),
        migrations.RunPython(populate_usernames, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='user',
            name='username',
            field=models.CharField(max_length=150, unique=True),
        ),
    ]
