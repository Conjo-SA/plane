# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Conjo: business days in Fortaleza/CE, for the monthly report e-mail (CONJO-52).

Weekends, national holidays, the Ceará and Fortaleza holidays and the days the team does not work
(Carnival and Corpus Christi, optional nationwide) are not business days. The list is kept in code, so a
new holiday is one line here.
"""

# Python imports
import datetime

# Fixed dates (month, day): national, then Ceará (São José, Data Magna) and Fortaleza (Assunção).
FIXED_HOLIDAYS = {
    (1, 1): "Confraternização Universal",
    (4, 21): "Tiradentes",
    (5, 1): "Dia do Trabalho",
    (9, 7): "Independência do Brasil",
    (10, 12): "Nossa Senhora Aparecida",
    (11, 2): "Finados",
    (11, 15): "Proclamação da República",
    (11, 20): "Dia Nacional de Zumbi e da Consciência Negra",
    (12, 25): "Natal",
    (3, 19): "São José (Ceará)",
    (3, 25): "Data Magna do Ceará",
    (8, 15): "Nossa Senhora da Assunção (Fortaleza)",
}

# Dates that follow Easter (days from Easter Sunday).
EASTER_HOLIDAYS = {
    -48: "Carnaval",
    -47: "Carnaval",
    -2: "Sexta-feira Santa",
    60: "Corpus Christi",
}


def easter(year):
    """Easter Sunday (Gregorian calendar, anonymous algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return datetime.date(year, month, day + 1)


def holidays(year):
    """``{date: name}`` of the year's holidays."""
    days = {datetime.date(year, month, day): name for (month, day), name in FIXED_HOLIDAYS.items()}
    sunday = easter(year)
    for offset, name in EASTER_HOLIDAYS.items():
        days.setdefault(sunday + datetime.timedelta(days=offset), name)
    return days


def is_business_day(day):
    return day.weekday() < 5 and day not in holidays(day.year)


def first_business_day(year, month):
    day = datetime.date(year, month, 1)
    while not is_business_day(day):
        day += datetime.timedelta(days=1)
    return day
