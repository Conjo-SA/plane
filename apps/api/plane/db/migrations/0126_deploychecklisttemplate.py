from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import plane.db.models.deploy_checklist
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('db', '0125_intakeportal_verification_session'),
    ]

    operations = [
        migrations.CreateModel(
            name='DeployChecklistTemplate',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created At')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Last Modified At')),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, primary_key=True, serialize=False, unique=True)),
                ('is_enabled', models.BooleanField(default=True)),
                ('items', models.JSONField(default=plane.db.models.deploy_checklist.get_default_deploy_checklist_items)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='deploychecklisttemplate_created_by', to=settings.AUTH_USER_MODEL, verbose_name='Created By')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='project_deploychecklisttemplate', to='db.project')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='deploychecklisttemplate_updated_by', to=settings.AUTH_USER_MODEL, verbose_name='Last Modified By')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='workspace_deploychecklisttemplate', to='db.workspace')),
            ],
            options={
                'verbose_name': 'DeployChecklistTemplate',
                'verbose_name_plural': 'DeployChecklistTemplates',
                'db_table': 'deploy_checklist_templates',
                'ordering': ('-created_at',),
            },
        ),
        migrations.AddConstraint(
            model_name='deploychecklisttemplate',
            constraint=models.UniqueConstraint(condition=models.Q(('deleted_at__isnull', True)), fields=('project',), name='deploy_checklist_unique_project_when_deleted_at_null'),
        ),
    ]
