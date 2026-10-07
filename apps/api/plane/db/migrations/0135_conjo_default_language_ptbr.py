# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Tasks (Conjo SA): português do Brasil como idioma padrão dos perfis.

from django.db import migrations, models
from django.db.models import Q


def set_ptbr_language(apps, schema_editor):
    Profile = apps.get_model("db", "Profile")
    Profile.objects.filter(Q(language="en") | Q(language="") | Q(language__isnull=True)).update(language="pt-BR")


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0134_conjo_issue_clients"),
    ]

    operations = [
        migrations.AlterField(
            model_name="profile",
            name="language",
            field=models.CharField(default="pt-BR", max_length=255),
        ),
        migrations.RunPython(set_ptbr_language, migrations.RunPython.noop),
    ]
