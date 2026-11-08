# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Conjo: the e-mail of the client activity report, with the Conjo look (CONJO-52).

E-mail clients only render tables and inline styles reliably, so that is all this uses. The logo goes
inside the message (``cid:``), because many clients block images loaded from the internet.
"""

# Python imports
import datetime

# Django imports
from django.conf import settings
from django.utils.html import escape

# Module imports
from plane.utils.conjo_client_report_pdf import ASSETS, brl, hours_text, period_text

LOGO_CID = "conjo-logo"
LOGO_FILE = ASSETS / "conjo-logo-white.png"

NAVY = "#0b1f33"
NAVY_SOFT = "#13304d"
ACCENT = "#8fb0f5"
ACCENT_SOFT = "#b9c9ee"
PAGE = "#eef1f4"
TILE = "#f3f5f8"
LINE = "#e6eaee"
INK = "#0b1f33"
MUTED = "#66727f"
FONT = "'Nunito Sans','Segoe UI',system-ui,-apple-system,Roboto,Helvetica,Arial,sans-serif"


def inline_images():
    """``(content id, filename, mimetype, bytes)`` of the images the body references."""
    return [(LOGO_CID, LOGO_FILE.name, "image/png", LOGO_FILE.read_bytes())]


def _tile(label, value, note, width):
    return (
        f'<td width="{width}" valign="top" style="background:{TILE};border-radius:10px;padding:12px;">'
        f'<div style="font-size:12px;font-weight:700;color:{MUTED};">{escape(label)}</div>'
        f'<div style="font-size:20px;font-weight:800;color:{INK};line-height:1.3;">{escape(value)}</div>'
        f'<div style="font-size:11px;color:{MUTED};line-height:1.35;">{escape(note)}</div>'
        "</td>"
    )


def _row(label, value):
    return (
        f'<tr><td style="padding:10px 0;border-top:1px solid {LINE};color:{MUTED};font-size:14px;">{escape(label)}</td>'
        f'<td align="right" style="padding:10px 0;border-top:1px solid {LINE};font-size:14px;font-weight:700;'
        f'color:{INK};">{escape(value)}</td></tr>'
    )


def _value_band(value):
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{NAVY_SOFT};'
        'border-radius:10px;margin:0 0 8px;"><tr>'
        '<td style="padding:16px 18px;">'
        '<div style="font-size:13px;font-weight:700;color:#ffffff;">Valor das horas de evolução</div>'
        f'<div style="font-size:12px;color:{ACCENT_SOFT};">{escape(hours_text(value["hours"]))} × '
        f"{escape(brl(value['hour_rate']))} por hora</div>"
        "</td>"
        '<td align="right" style="padding:16px 18px;font-size:24px;font-weight:800;color:#ffffff;white-space:nowrap;">'
        f"{escape(brl(value['total']))}</td>"
        "</tr></table>"
    )


def report_email(report, test_recipients=None, exhausted=False):
    """Subject and HTML body.

    ``test_recipients``: who would get it in production (shown in a banner). ``exhausted``: the report goes
    because the hour package ran out, not because the month closed.
    """
    name = report["client"]["name"]
    client = report["client"].get("legal_name") or name
    period = period_text(report["period"]["from"], report["period"]["to"])
    totals, pkg, value = report["totals"], report["package"], report.get("value")

    subject = (
        f"Pacote de horas esgotado: {name}"
        if exhausted
        else f"Relatório de atividades: {name}, {period.split(' (')[0]}"
    )
    if test_recipients is not None:
        subject = f"[TESTE] {subject}"

    intro = (
        f"O pacote de horas de evolução de <b>{escape(client)}</b> chegou ao fim. Segue o relatório de atividades "
        f"do período de {escape(period)}."
        if exhausted
        else f"Segue o relatório de atividades de <b>{escape(client)}</b> referente a {escape(period)}."
    )

    rows = [_row("Chamados concluídos", f"{totals['done_items']} de {totals['items']}")]
    if pkg:
        balance = hours_text(pkg["balance"])
        if pkg.get("valid_until"):
            balance += f" (válido até {datetime.date.fromisoformat(pkg['valid_until']):%d/%m/%Y})"
        rows.append(_row("Saldo do pacote de horas", balance))

    banner = ""
    if test_recipients is not None:
        banner = (
            '<tr><td style="padding:0 0 12px;"><div style="background:#fff4e5;border:1px solid #f5c26b;'
            'border-radius:8px;padding:10px 12px;font-size:13px;color:#0b1f33;">Envio de teste. Com o envio '
            f"liberado, este e-mail iria para: {escape(', '.join(test_recipients))}.</div></td></tr>"
        )
    reply = (
        f'<p style="margin:0 0 16px;font-size:14px;color:{INK};">Qualquer dúvida, é só responder este e-mail.</p>'
        if settings.CONJO_REPORT_REPLY_TO
        else ""
    )

    html = (
        f'<div style="margin:0;padding:24px 12px;background:{PAGE};font-family:{FONT};">'
        '<table role="presentation" align="center" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:600px;margin:0 auto;">'
        f"{banner}"
        "<tr><td>"
        # Header
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{NAVY};'
        'border-radius:14px 14px 0 0;"><tr><td style="padding:26px 28px 24px;">'
        f'<img src="cid:{LOGO_CID}" alt="Conjo" width="104" height="49" style="display:block;border:0;color:#ffffff;'
        'font-size:22px;font-weight:800;" />'
        f'<div style="margin-top:20px;font-size:11px;font-weight:700;letter-spacing:1.4px;color:{ACCENT};">'
        "RELATÓRIO DE ATIVIDADES</div>"
        f'<div style="font-size:24px;font-weight:800;color:#ffffff;line-height:1.25;">{escape(client)}</div>'
        f'<div style="font-size:14px;color:{ACCENT_SOFT};">{escape(period)}</div>'
        "</td></tr></table>"
        # Body
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;">'
        '<tr><td style="padding:26px 28px 8px;">'
        f'<p style="margin:0 0 8px;font-size:14px;color:{INK};">Olá,</p>'
        f'<p style="margin:0 0 20px;font-size:14px;line-height:1.55;color:{INK};">{intro}</p>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 8px;"><tr>'
        f"{_tile('Horas no período', hours_text(totals['hours']), 'Evolução e manutenção', '32%')}"
        '<td width="2%"></td>'
        f"{_tile('Evolução', hours_text(totals['evolution_hours']), 'Mudanças pedidas', '32%')}"
        '<td width="2%"></td>'
        f"{_tile('Manutenção', hours_text(totals['maintenance_hours']), 'Incluída no contrato', '32%')}"
        "</tr></table>"
        f"{_value_band(value) if value else ''}"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:12px 0 16px;">'
        f"{''.join(rows)}</table>"
        f'<p style="margin:0 0 16px;font-size:14px;line-height:1.55;color:{INK};">O relatório completo, com o '
        f"detalhamento de cada atividade, está no PDF anexo (nº {escape(report['number'])}).</p>"
        f"{reply}"
        f'<p style="margin:0 0 20px;font-size:14px;color:{INK};">Equipe Conjo SA</p>'
        "</td></tr></table>"
        # Footer
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{NAVY};'
        'border-radius:0 0 14px 14px;"><tr><td style="padding:16px 28px;">'
        '<div style="font-size:12px;font-weight:700;color:#ffffff;">Conjo SA · contato@conjosa.com.br · conjosa.com.br'
        "</div>"
        f'<div style="font-size:11px;color:{ACCENT_SOFT};">Você recebe este relatório por ser contato de '
        f"{escape(name)} na Conjo SA.</div>"
        "</td></tr></table>"
        "</td></tr></table>"
        "</div>"
    )
    return subject, html
