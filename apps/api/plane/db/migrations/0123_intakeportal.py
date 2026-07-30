from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import plane.db.models.intake
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('db', '0122_alter_draftissue_assignees_alter_issue_assignees_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='IntakePortal',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created At')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Last Modified At')),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, primary_key=True, serialize=False, unique=True)),
                ('anchor', models.CharField(db_index=True, default=plane.db.models.intake.get_intake_portal_anchor, max_length=255, unique=True)),
                ('is_enabled', models.BooleanField(default=False)),
                ('title', models.CharField(blank=True, max_length=255)),
                ('description', models.TextField(blank=True)),
                ('success_message', models.TextField(blank=True)),
                ('is_attachment_enabled', models.BooleanField(default=False)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='intakeportal_created_by', to=settings.AUTH_USER_MODEL, verbose_name='Created By')),
                ('intake', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='portals', to='db.intake')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='project_intakeportal', to='db.project')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='intakeportal_updated_by', to=settings.AUTH_USER_MODEL, verbose_name='Last Modified By')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='workspace_intakeportal', to='db.workspace')),
            ],
            options={
                'verbose_name': 'IntakePortal',
                'verbose_name_plural': 'IntakePortals',
                'db_table': 'intake_portals',
                'ordering': ('-created_at',),
            },
        ),
        migrations.AddConstraint(
            model_name='intakeportal',
            constraint=models.UniqueConstraint(condition=models.Q(('deleted_at__isnull', True)), fields=('project',), name='intake_portal_unique_project_when_deleted_at_null'),
        ),
    ]
