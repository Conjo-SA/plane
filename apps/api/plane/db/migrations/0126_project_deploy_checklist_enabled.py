from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('db', '0125_intakeportal_verification_session'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='deploy_checklist_enabled',
            field=models.BooleanField(default=False),
        ),
    ]
