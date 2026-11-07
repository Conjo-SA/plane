# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Conjo: the client activity report as a PDF, for the monthly e-mail (CONJO-52).

Draws the payload of ``build_client_report`` with the layout of the printed report in the web app
(``client-report-document.tsx``): page 1 is the summary, the next pages are the detail. Nothing is
computed here, so the PDF always has the numbers of the screen.
"""

# Python imports
import datetime
import re
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

# Third party imports
from fontTools.ttLib import TTFont
from fpdf import FPDF

ASSETS = Path(__file__).resolve().parent / "conjo_report_assets"
FONTS = {"": "regular.ttf", "semi": "semibold.ttf", "bold": "bold.ttf", "heavy": "heavy.ttf"}
LOGO = ASSETS / "conjo-logo-black.png"

MONTHS = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)

INK = "#141414"
MUTED = "#6B6B66"
FAINT = "#8A8A84"
SOFT_INK = "#3D3D3A"
LINE = "#ECECE8"
ROW_LINE = "#F0F0EC"
TRACK = "#F1F1EE"
PANEL = "#F6F6F3"
EVO = "#2B5BA8"
MAN = "#18794E"
KIND = {
    "evolution": {"label": "Evolução", "bg": "#E7EEF9", "ink": EVO, "kpi": "#EEF3FB"},
    "maintenance": {"label": "Manutenção", "bg": "#E6F4EC", "ink": MAN, "kpi": "#EDF7F1"},
}

PAGE_W, PAGE_H = 210, 297
SIDE = 14
CONTENT_W = PAGE_W - 2 * SIDE
FOOTER_H = 16
PX = 0.2646  # one CSS pixel in millimetres
# Longest description of a detail row: a row must fit on one page (the PDF does not split rows).
MAX_ROW_TEXT = 1500
PT = 0.75  # one CSS pixel in points


# --------------------------------------------------------------------------- #
# Formatting (same output as the web document)
# --------------------------------------------------------------------------- #


def _number(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError):
        number = Decimal("0")
    number = number.quantize(Decimal("0.01"))
    whole, _, cents = f"{abs(number):.2f}".partition(".")
    whole = f"{int(whole):,}".replace(",", ".")
    cents = cents.rstrip("0")
    sign = "-" if number < 0 else ""
    return f"{sign}{whole},{cents}" if cents else f"{sign}{whole}"


def hours_text(value):
    """``"30.50"`` → ``"30,5 h"``."""
    return f"{_number(value)} h"


def _date(value):
    return datetime.date.fromisoformat(str(value)[:10])


def full_date(value):
    return f"{_date(value):%d/%m/%Y}"


def _day_month(value):
    return f"{_date(value):%d/%m}"


def period_text(start, end):
    """``"Setembro de 2026 (01/09 a 30/09)"`` for a calendar month; ``"01/09/2026 a 15/09/2026"`` otherwise."""
    first, last = _date(start), _date(end)
    next_month = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    if first.day == 1 and last == next_month - datetime.timedelta(days=1):
        month = MONTHS[first.month - 1].capitalize()
        return f"{month} de {first.year} ({_day_month(start)} a {_day_month(end)})"
    return full_date(start) if first == last else f"{full_date(start)} a {full_date(end)}"


def _plural(count, one, many):
    return f"{count} {one if count == 1 else many}"


def _hours(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _share(part, total):
    return max(0.0, min(1.0, part / total)) if total > 0 else 0.0


def _rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))


@lru_cache(maxsize=1)
def _glyphs():
    """Characters the bundled font can draw; anything else (emoji, rare symbols) is left out."""
    font = TTFont(str(ASSETS / FONTS[""]), lazy=True)
    return frozenset(font.getBestCmap())


def clean(text):
    glyphs = _glyphs()
    text = "".join(ch for ch in str(text or "") if ord(ch) in glyphs or ch.isspace())
    return re.sub(r" ([.,;:!?)])", r"\1", " ".join(text.split()))


# --------------------------------------------------------------------------- #
# Document
# --------------------------------------------------------------------------- #


class ReportPDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        for style, name in FONTS.items():
            self.add_font(f"inter{style}", "", str(ASSETS / name))
        self.set_auto_page_break(False)
        self.set_margins(SIDE, 12, SIDE)
        self.footers = {}
        self.set_title("Relatório de atividades")
        self.set_author("Conjo SA")
        self.set_creator("Tasks")

    # Small drawing helpers (sizes in CSS pixels, as in the web document) --------

    def font(self, size_px, weight="", color=INK):
        self.set_font(f"inter{weight}", size=size_px * PT)
        self.set_text_color(*_rgb(color))

    def fill(self, color):
        self.set_fill_color(*_rgb(color))

    def box(self, x, y, w, h, color, radius=0, border=None):
        if w <= 0 or h <= 0:
            return
        self.fill(color)
        style = "F"
        if border:
            self.set_draw_color(*_rgb(border))
            self.set_line_width(0.25)
            style = "DF"
        if radius:
            self.rect(x, y, w, h, style=style, round_corners=True, corner_radius=min(radius, h / 2, w / 2))
        else:
            self.rect(x, y, w, h, style=style)

    def hline(self, y, color=LINE, x=SIDE, w=CONTENT_W):
        self.set_draw_color(*_rgb(color))
        self.set_line_width(0.25)
        self.line(x, y, x + w, y)

    def text_at(self, x, y, w, text, size, weight="", color=INK, align="L"):
        """One line, cut to fit ``w``; returns the line height."""
        self.font(size, weight, color)
        text = clean(text)
        while text and self.get_string_width(text) > w:
            text = text[:-2].rstrip() + "…" if len(text) > 2 else ""
        h = size * PX * 1.35
        self.set_xy(x, y)
        self.cell(w, h, text, align=align)
        return h

    def lines(self, x, y, w, text, size, weight="", color=INK, leading=1.4, draw=True):
        """Wrapped text; returns its height."""
        self.font(size, weight, color)
        h = size * PX * leading
        text = clean(text)
        if not text:
            return 0
        rows = self.multi_cell(w, h, text, dry_run=True, output="LINES")
        if draw:
            self.set_xy(x, y)
            self.multi_cell(w, h, text, align="L")
        return h * len(rows)

    def bar(self, x, y, w, h, parts, track=TRACK):
        """A rounded bar with consecutive segments ``[(share, color)]``."""
        self.box(x, y, w, h, track, radius=h / 2)
        start = x
        for share, color in parts:
            seg = w * share
            if seg > 0.2:
                self.box(start, y, seg, h, color, radius=min(h / 2, seg / 2))
                start += seg

    def tag(self, x, y, kind, small=False):
        style = KIND[kind]
        size = 10 if small else 10.5
        self.font(size, "bold", style["ink"])
        w = self.get_string_width(style["label"]) + (12 if small else 14) * PX
        h = (18 if small else 20) * PX
        self.box(x, y, w, h, style["bg"], radius=(5 if small else 6) * PX)
        self.set_xy(x, y)
        self.cell(w, h, style["label"], align="C")
        return w

    # Page frame ------------------------------------------------------------------

    def new_page(self, footer_text):
        self.add_page()
        self.footers[self.page_no()] = footer_text

    def footer(self):
        top = PAGE_H - FOOTER_H
        self.hline(top)
        self.lines(SIDE, top + 3.5, CONTENT_W - 32, self.footers.get(self.page_no(), ""), 10, color=FAINT)
        self.text_at(SIDE, top + 3.5, CONTENT_W, f"Página {self.page_no()} de {{nb}}", 10, color=FAINT, align="R")

    @property
    def bottom(self):
        return PAGE_H - FOOTER_H - 4


def _summary_page(pdf, report):
    pdf.new_page(SUMMARY_FOOTER)
    client_name = report["client"].get("legal_name") or report["client"]["name"]
    period = period_text(report["period"]["from"], report["period"]["to"])

    # Header: logo, title and the issue data on the right.
    y = 44 * PX
    right_w = 70
    if LOGO.exists():
        pdf.image(str(LOGO), x=SIDE, y=y, h=48 * PX)
    y += 48 * PX + 18 * PX
    meta = [("Nº", report["number"]), ("Emitido em", full_date(report["issued_on"]))]
    if report.get("contract"):
        meta.append(("Contrato", report["contract"]["name"]))
    meta.append(("Responsável", report["owner"]))
    my = 44 * PX
    for label, value in meta:
        pdf.font(12, "semi")
        value = clean(value)
        value_w = min(pdf.get_string_width(value) + 0.5, right_w - 22)
        pdf.text_at(PAGE_W - SIDE - value_w, my, value_w, value, 12, "semi", align="R")
        pdf.text_at(PAGE_W - SIDE - right_w, my, right_w - value_w - 3, label, 12, color=FAINT, align="R")
        my += 18 * PX

    left_w = CONTENT_W - right_w - 6
    y += pdf.text_at(SIDE, y, left_w, "RELATÓRIO DE ATIVIDADES", 11, "bold", FAINT) + 1
    y += pdf.lines(SIDE, y, left_w, client_name, 28, "heavy", leading=1.15) + 1
    y += pdf.text_at(SIDE, y, left_w, period, 14, color=MUTED)
    y = max(y, my) + 28 * PX
    pdf.hline(y)

    # KPIs.
    totals = report["totals"]
    open_items = totals["items"] - totals["done_items"]
    if totals["items"] == 0:
        done_note = "Nenhum chamado no período"
    elif open_items == 0:
        done_note = "Todos concluídos"
    else:
        done_note = f"{open_items} {'segue' if open_items == 1 else 'seguem'} em andamento"
    kpis = [
        ("Horas no período", hours_text(totals["hours"]), "Evolução e manutenção somadas", PANEL, SOFT_INK),
        (
            "Evolução",
            hours_text(totals["evolution_hours"]),
            "Novas funcionalidades e mudanças pedidas",
            KIND["evolution"]["kpi"],
            EVO,
        ),
        (
            "Manutenção",
            hours_text(totals["maintenance_hours"]),
            "Incluídas no contrato, sem débito",
            KIND["maintenance"]["kpi"],
            MAN,
        ),
        ("Chamados concluídos", f"{totals['done_items']} de {totals['items']}", done_note, PANEL, SOFT_INK),
    ]
    y += 26 * PX
    gap = 12 * PX
    kpi_w = (CONTENT_W - 3 * gap) / 4
    pad = 14 * PX
    note_h = max(pdf.lines(0, 0, kpi_w - 2 * pad, k[2], 11, leading=1.35, draw=False) for k in kpis)
    kpi_h = pad + 11.5 * PX * 1.35 + 26 * PX * 1.15 + note_h + 12 * PX + 8 * PX
    for i, (label, value, note, bg, ink) in enumerate(kpis):
        x = SIDE + i * (kpi_w + gap)
        pdf.box(x, y, kpi_w, kpi_h, bg, radius=12 * PX)
        ky = y + pad
        ky += pdf.text_at(x + pad, ky, kpi_w - 2 * pad, label, 11.5, "bold", ink) + 1
        ky += pdf.text_at(x + pad, ky, kpi_w - 2 * pad, value, 26, "heavy") + 1
        pdf.lines(x + pad, ky, kpi_w - 2 * pad, note, 11, color=MUTED, leading=1.35)
    y += kpi_h + 22 * PX

    # Hour package.
    pkg = report.get("package")
    pdf.text_at(SIDE, y, CONTENT_W / 2, "Pacote de horas de evolução", 14, "heavy")
    if pkg:
        used = _hours(pkg["used_before"]) + _hours(pkg["used_in_period"])
        validity = ""
        if pkg.get("valid_until"):
            validity = f"válido até {full_date(pkg['valid_until'])}"
            if pkg.get("next_expiry") and pkg["next_expiry"] != pkg["valid_until"]:
                validity += f" (parte vence em {full_date(pkg['next_expiry'])})"
        side_text = f"{hours_text(used)} usadas de {hours_text(pkg['contracted'])}"
        if validity:
            side_text += f" · {validity}"
        pdf.text_at(SIDE + CONTENT_W * 0.38, y + 0.6, CONTENT_W * 0.62, side_text, 12, color=MUTED, align="R")
        y += 14 * PX * 1.35 + 10 * PX
        contracted = _hours(pkg["contracted"])
        pdf.bar(
            SIDE,
            y,
            CONTENT_W,
            14 * PX,
            [
                (_share(_hours(pkg["used_before"]), contracted), "#B9C9E6"),
                (_share(_hours(pkg["used_in_period"]), contracted), EVO),
            ],
        )
        y += 14 * PX + 10 * PX
        legend = [
            ("#B9C9E6", f"Meses anteriores {hours_text(pkg['used_before'])}", False),
            (EVO, f"Este período {hours_text(pkg['used_in_period'])}", False),
            (TRACK, f"Saldo {hours_text(pkg['balance'])}", True),
        ]
        if _hours(pkg.get("excess_in_period")) > 0:
            legend.append(("#C2410C", f"Além do pacote {hours_text(pkg['excess_in_period'])}", False))
        if _hours(pkg.get("excess_returned_in_period")) > 0:
            legend.append(("#15803D", f"Excedente devolvido {hours_text(pkg['excess_returned_in_period'])}", False))
        x = SIDE
        for color, text, border in legend:
            pdf.box(x, y + 1.0, 9 * PX, 9 * PX, color, radius=3 * PX, border="#DDDDD8" if border else None)
            pdf.font(11.5, color=SOFT_INK)
            w = pdf.get_string_width(clean(text)) + 1
            pdf.text_at(x + 9 * PX + 1.6, y, w, text, 11.5, color=SOFT_INK)
            x += 9 * PX + 1.6 + w + 18 * PX
        y += 11.5 * PX * 1.35
    else:
        y += 14 * PX * 1.35 + 10 * PX
        y += pdf.text_at(SIDE, y, CONTENT_W, "Sem pacote de horas de evolução no período.", 12, color=MUTED)
    y += 22 * PX

    # Hours by kind and by system, side by side.
    col_gap = 28 * PX
    col_w = (CONTENT_W - col_gap) / 2
    left, right = SIDE, SIDE + col_w + col_gap
    ly = ry = y
    ly += pdf.text_at(left, ly, col_w, "Horas por tipo", 14, "heavy") + 10 * PX
    for item in report["by_kind"]:
        label = KIND.get(item["kind"], {"label": item["kind"]})["label"]
        pdf.text_at(left, ly, col_w, label, 12.5, "bold")
        pdf.text_at(left, ly, col_w, hours_text(item["hours"]), 12.5, "bold", align="R")
        ly += 12.5 * PX * 1.35 + 5 * PX
        pdf.bar(
            left,
            ly,
            col_w,
            8 * PX,
            [(_share(item["minutes"], totals["minutes"]), KIND.get(item["kind"], KIND["evolution"])["ink"])],
        )
        ly += 8 * PX + 5 * PX
        if item["items"] == 0:
            note = "Nenhum chamado no período"
        else:
            note = (
                f"{_plural(item['items'], 'chamado', 'chamados')}, "
                f"{_plural(item['done_items'], 'concluído', 'concluídos')}"
            )
        ly += pdf.text_at(left, ly, col_w, note, 11, color=MUTED) + 10 * PX

    ry += pdf.text_at(right, ry, col_w, "Horas por sistema", 14, "heavy") + 10 * PX
    if not report["by_system"]:
        ry += pdf.text_at(right, ry, col_w, "Nenhuma hora registrada no período.", 12, color=MUTED)
    name_w, hours_w = 110 * PX, 46 * PX
    for system in report["by_system"]:
        row_h = 12.5 * PX * 1.35
        pdf.text_at(right, ry, name_w, system["name"], 12.5, "bold")
        bar_x = right + name_w + 10 * PX
        bar_w = col_w - name_w - hours_w - 20 * PX
        pdf.bar(
            bar_x,
            ry + (row_h - 8 * PX) / 2,
            bar_w,
            8 * PX,
            [
                (_share(system["evolution_minutes"], system["minutes"]), EVO),
                (_share(system["maintenance_minutes"], system["minutes"]), MAN),
            ],
        )
        pdf.text_at(right + col_w - hours_w, ry, hours_w, hours_text(system["hours"]), 12.5, "bold", align="R")
        ry += row_h + 10 * PX
    y = max(ly, ry) + 14 * PX

    # Highlights (cards); a card that does not fit goes to a new page.
    y += pdf.text_at(SIDE, y, CONTENT_W, "Principais entregas", 14, "heavy") + 10 * PX
    if not report["highlights"]:
        pdf.text_at(SIDE, y, CONTENT_W, "Nenhuma entrega registrada no período.", 12, color=MUTED)
    pad = 13 * PX
    for item in report["highlights"]:
        side_label = "Em orçamento aprovado" if item.get("budgeted") else hours_text(item["hours"])
        pdf.font(12.5, "bold")
        side_w = pdf.get_string_width(side_label) + 1
        pdf.font(10.5, "bold")
        tag_w = pdf.get_string_width(KIND.get(item["kind"], KIND["evolution"])["label"]) + 14 * PX
        title_x = SIDE + pad + tag_w + 8 * PX
        title_w = CONTENT_W - 2 * pad - tag_w - 8 * PX - side_w - 14 * PX
        title_h = pdf.lines(title_x, 0, title_w, item["title"], 13.5, "heavy", leading=1.3, draw=False)
        summary_h = pdf.lines(0, 0, CONTENT_W - 2 * pad, item.get("summary"), 12, leading=1.45, draw=False)
        card_h = pad + max(title_h, 20 * PX) + (4 * PX + summary_h if summary_h else 0) + pad
        if y + card_h > pdf.bottom:
            pdf.new_page(SUMMARY_FOOTER)
            y = 36 * PX
        pdf.box(SIDE, y, CONTENT_W, card_h, "#FFFFFF", radius=12 * PX, border=LINE)
        cy = y + pad
        pdf.tag(SIDE + pad, cy + max(0, (13.5 * PX * 1.3 - 20 * PX) / 2), item["kind"])
        pdf.lines(title_x, cy, title_w, item["title"], 13.5, "heavy", leading=1.3)
        pdf.text_at(PAGE_W - SIDE - pad - side_w, cy, side_w, side_label, 12.5, "bold", SOFT_INK, align="R")
        cy += max(title_h, 20 * PX) + 4 * PX
        if summary_h:
            pdf.lines(SIDE + pad, cy, CONTENT_W - 2 * pad, item["summary"], 12, color="#4A4A45", leading=1.45)
        y += card_h + 10 * PX


SUMMARY_FOOTER = "Conjo SA · contato@conjosa.com.br · conjosa.com.br"
DETAIL_COLS = (("Data", 46), ("Chamado", 72), ("Tipo", 78), ("O que foi feito", None), ("Horas", 48))


def _detail_header(pdf, report, client_name, period):
    pdf.new_page(
        f"Gerado pelo Tasks em {full_date(report['issued_on'])}. Cada linha corresponde a um lançamento do "
        "chamado ou a um orçamento aprovado."
    )
    y = 36 * PX
    title = "Detalhamento das atividades"
    pdf.font(18, "heavy")
    title_w = pdf.get_string_width(title) + 2
    pdf.text_at(SIDE, y, title_w, title, 18, "heavy")
    side_w = CONTENT_W - title_w - 4
    side = f"{client_name} · {period}"
    pdf.font(12)
    if pdf.get_string_width(clean(side)) > side_w:
        side = period
    pdf.text_at(SIDE + title_w + 4, y + 1.2, side_w, side, 12, color=MUTED, align="R")
    y += 18 * PX * 1.35 + 18 * PX
    pdf.hline(y)
    y += 14 * PX
    x = SIDE
    widths = _detail_widths()
    for (label, _), w in zip(DETAIL_COLS, widths):
        align = "R" if label == "Horas" else "L"
        pdf.text_at(x, y + 8 * PX, w - 6 * PX, label.upper(), 10.5, "bold", FAINT, align=align)
        x += w
    return y + 8 * PX + 10.5 * PX * 1.35 + 8 * PX


def _detail_widths():
    fixed = sum(w for _, w in DETAIL_COLS if w) * PX
    return [w * PX if w else CONTENT_W - fixed for _, w in DETAIL_COLS]


def _detail_pages(pdf, report):
    client_name = report["client"].get("legal_name") or report["client"]["name"]
    period = period_text(report["period"]["from"], report["period"]["to"])
    widths = _detail_widths()
    pad = 8 * PX
    y = _detail_header(pdf, report, client_name, period)

    if not report["rows"]:
        pdf.hline(y, ROW_LINE)
        y += pdf.text_at(SIDE, y + 12 * PX, CONTENT_W, "Nenhuma hora registrada no período.", 11.5, color=MUTED)
        y += 24 * PX
    for row in report["rows"]:
        what_w = widths[3] - 12 * PX
        title = clean(row["title"])
        title = title if title.endswith((".", "!", "?")) else f"{title}."
        description = clean(row.get("description"))
        if len(description) > MAX_ROW_TEXT:
            description = description[:MAX_ROW_TEXT].rsplit(" ", 1)[0] + "…"
        title_h = pdf.lines(0, 0, what_w, title, 11.5, "bold", leading=1.45, draw=False)
        desc_h = pdf.lines(0, 0, what_w, description, 11.5, leading=1.45, draw=False)
        row_h = pad + max(title_h + desc_h, 18 * PX) + pad
        if y + row_h > pdf.bottom:
            y = _detail_header(pdf, report, client_name, period)
        pdf.hline(y, ROW_LINE)
        x = SIDE
        pdf.text_at(x, y + pad, widths[0] - 6 * PX, _day_month(row["date"]), 11.5, color=MUTED)
        x += widths[0]
        pdf.text_at(x + 6 * PX, y + pad, widths[1] - 12 * PX, row["key"], 10.5, "semi")
        x += widths[1]
        if row["kind"] in KIND:
            pdf.tag(x + 6 * PX, y + pad, row["kind"], small=True)
        x += widths[2]
        pdf.lines(x + 6 * PX, y + pad, what_w, title, 11.5, "bold", leading=1.45)
        if desc_h:
            pdf.lines(x + 6 * PX, y + pad + title_h, what_w, description, 11.5, leading=1.45)
        hours = "—" if row.get("budgeted") else hours_text(row["hours"])
        pdf.text_at(PAGE_W - SIDE - widths[4], y + pad, widths[4], hours, 11.5, "bold", align="R")
        y += row_h

    totals = report["totals"]
    for label, value, weight in (
        ("Evolução", totals["evolution_hours"], "semi"),
        ("Manutenção (incluída no contrato)", totals["maintenance_hours"], "semi"),
        ("Total do período", totals["hours"], "heavy"),
    ):
        row_h = 2 * pad + 11.5 * PX * 1.35
        if y + row_h > pdf.bottom:
            y = _detail_header(pdf, report, client_name, period)
        pdf.hline(y, "#E4E4E0")
        pdf.text_at(SIDE, y + pad, CONTENT_W - widths[4] - 6 * PX, label, 11.5, weight, SOFT_INK, align="R")
        pdf.text_at(PAGE_W - SIDE - widths[4], y + pad, widths[4], hours_text(value), 11.5, "heavy", align="R")
        y += row_h

    # Next steps and how the hours are counted, side by side.
    steps = [
        (
            f'Orçamento de {hours_text(step["hours"])} enviado para "{step["title"]}" ({step["key"]}), '
            "aguardando aprovação."
            if step.get("type") == "pending_estimate"
            else f"{step['title']}: em andamento ({step['key']})."
        )
        for step in report["next_steps"]
    ] or ["Nenhum chamado em aberto no momento."]
    how = [
        (
            "Evolução",
            EVO,
            " é tudo o que acrescenta ou muda funcionalidade a pedido do cliente e é debitado do pacote "
            "contratado, depois de orçamento aprovado. Conta o total de horas aprovado, uma única vez. Os "
            'lançamentos desse trabalho aparecem com "—" porque já estão no orçamento.',
        ),
        (
            "Manutenção",
            MAN,
            " é a correção de bugs: erro, falha ou comportamento inesperado do sistema. Está incluída no "
            "contrato e não é debitada.",
        ),
    ]
    gap = 20 * PX
    panel_w = (CONTENT_W - gap) / 2
    pad = 15 * PX
    inner = panel_w - 2 * pad
    steps_h = sum(pdf.lines(0, 0, inner - 14 * PX, s, 12, leading=1.45, draw=False) + 4 * PX for s in steps)
    how_h = sum(pdf.lines(0, 0, inner, f"{k}{t}", 11.5, leading=1.5, draw=False) + 6 * PX for k, _, t in how)
    head_h = 13 * PX * 1.35 + 8 * PX
    panel_h = 2 * pad + head_h + max(steps_h, how_h)
    y += 20 * PX
    if y + panel_h > pdf.bottom:
        y = _detail_header(pdf, report, client_name, period)
    left, right = SIDE, SIDE + panel_w + gap
    pdf.box(left, y, panel_w, panel_h, PANEL, radius=12 * PX)
    pdf.box(right, y, panel_w, panel_h, PANEL, radius=12 * PX)
    pdf.text_at(left + pad, y + pad, inner, "Em andamento e próximos passos", 13, "heavy")
    pdf.text_at(right + pad, y + pad, inner, "Como as horas são contadas", 13, "heavy")
    sy = y + pad + head_h
    for step in steps:
        if step != "Nenhum chamado em aberto no momento.":
            pdf.box(left + pad, sy + 6 * PX, 6 * PX, 6 * PX, SOFT_INK, radius=3 * PX)
            sy += pdf.lines(left + pad + 14 * PX, sy, inner - 14 * PX, step, 12, leading=1.45) + 4 * PX
        else:
            sy += pdf.lines(left + pad, sy, inner, step, 12, leading=1.45) + 4 * PX
    hy = y + pad + head_h
    for kind, color, text in how:
        # The kind in bold and in its color, followed by the explanation on the same line.
        pdf.set_xy(right + pad, hy)
        pdf.set_left_margin(right + pad)
        pdf.set_right_margin(PAGE_W - right - panel_w + pad)
        line_h = 11.5 * PX * 1.5
        pdf.font(11.5, "bold", color)
        pdf.write(line_h, kind)
        pdf.font(11.5, color=SOFT_INK)
        pdf.write(line_h, " " + clean(text))
        pdf.set_margins(SIDE, 12, SIDE)
        hy = pdf.get_y() + line_h + 6 * PX


def render_client_report_pdf(report):
    """PDF bytes of a ``build_client_report`` payload."""
    pdf = ReportPDF()
    pdf.set_subject(f"{report['number']} · {report['client']['name']}")
    _summary_page(pdf, report)
    _detail_pages(pdf, report)
    return bytes(pdf.output())
