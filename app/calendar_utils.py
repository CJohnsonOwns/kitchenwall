import calendar as cal
from datetime import date, datetime


def parse_month(month_str: str | None) -> date:
    if month_str:
        try:
            return datetime.strptime(month_str, "%Y-%m").date().replace(day=1)
        except ValueError:
            pass
    return date.today().replace(day=1)


def build_month_grid(month: date, bills_by_day: dict[int, list], week_start: str = "sun"):
    c = cal.Calendar(firstweekday=0 if week_start == "mon" else 6)
    weeks = c.monthdayscalendar(month.year, month.month)
    grid = []
    for week in weeks:
        row = []
        for day in week:
            if day == 0:
                row.append(None)
            else:
                row.append({"day": day, "bills": bills_by_day.get(day, [])})
        grid.append(row)
    return grid
