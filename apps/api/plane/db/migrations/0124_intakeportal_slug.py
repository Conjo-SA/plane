from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('db', '0123_intakeportal'),
    ]

    operations = [
        migrations.AddField(
            model_name='intakeportal',
            name='slug',
            field=models.CharField(blank=True, db_index=True, max_length=60, null=True, unique=True),
        ),
    ]
