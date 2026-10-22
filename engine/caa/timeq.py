from __future__ import annotations

import locale
import os
import re
import sys
import time
from datetime import date, datetime, timedelta

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
ASPECTS = {"16:9", "9:16", "4:3", "3:4", "1:1", "21:9", "4:5", "5:4", "3:2", "2:3"}
FILLER = {"on", "at", "around", "about", "approx", "approximately", "recorded", "shot", "taken", "filmed", "captured",
          "from", "in", "during", "the", "of", "between", "and", "time", "date", "dated", "exactly"}
PARTS = {"morning": (5 * 3600, 12 * 3600), "afternoon": (12 * 3600, 17 * 3600), "evening": (17 * 3600, 21 * 3600),
         "night": (21 * 3600, 29 * 3600), "sunrise": (5 * 3600, 8 * 3600), "sunset": (17 * 3600, 20 * 3600)}


def system_date_order() -> str:
    env = os.environ.get("CAA_DATE_ORDER", "").upper()
    if env in ("DMY", "MDY", "YMD"):
        return env
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\International") as k:
                fmt = str(winreg.QueryValueEx(k, "sShortDate")[0]).lower()
            order = sorted((fmt.find(c), c) for c in "dmy" if c in fmt)
            return "".join(c for _, c in order).upper() or "DMY"
        except OSError:
            return "DMY"
    try:
        old = locale.setlocale(locale.LC_TIME)
        locale.setlocale(locale.LC_TIME, "")
        s = time.strftime("%x", (2001, 2, 3, 0, 0, 0, 5, 34, 0))
        locale.setlocale(locale.LC_TIME, old)
        nums = re.findall(r"\d+", s)
        if nums and nums[0].lstrip("0") == "3":
            return "DMY"
        if nums and nums[0] in ("2001",):
            return "YMD"
        if nums and nums[0].lstrip("0") == "2":
            return "MDY"
    except (locale.Error, ValueError):
        pass
    return "DMY"


def _year(y: str | None, today: date) -> int:
    if not y:
        return today.year
    n = int(y)
    return n + 2000 if n < 100 else n


def _valid(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _past(dt: date, today: date) -> date:
    return dt if dt <= today else _valid(dt.year - 1, dt.month, dt.day) or dt


class When:
    def __init__(self):
        self.d0: date | None = None
        self.d1: date | None = None
        self.point: int | None = None
        self.tol: int = 0
        self.tod: tuple[int, int] | None = None
        self.labels: list[str] = []
        self.rest: str = ""
        self.alt: date | None = None
        self.raw: str = ""

    @property
    def found(self) -> bool:
        return self.d0 is not None or self.point is not None or self.tod is not None

    def to_dict(self, q: str = "") -> dict:
        out = {
            "start": datetime.combine(self.d0, datetime.min.time()).timestamp() if self.d0 else None,
            "end": datetime.combine(self.d1 + timedelta(days=1), datetime.min.time()).timestamp() if self.d1 else None,
            "point": self.point, "tol": self.tol, "tod": list(self.tod) if self.tod else None,
            "label": ", ".join(self.labels), "rest": self.rest, "alt": None,
        }
        if self.alt is not None and self.d0 is not None:
            primary = _fmt_date(self.d0)
            alt_label = _fmt_date(self.alt)
            i = q.lower().find(self.raw)
            out["date_label"] = primary
            out["alt"] = {
                "start": datetime.combine(self.alt, datetime.min.time()).timestamp(),
                "end": datetime.combine(self.alt + timedelta(days=1), datetime.min.time()).timestamp(),
                "label": ", ".join(alt_label if x == primary else x for x in self.labels),
                "date_label": alt_label, "text": self.raw,
                "query": (q[:i] + alt_label + q[i + len(self.raw):]).strip() if i >= 0 else f"{alt_label} {self.rest}".strip(),
            }
        return out


def _fmt_date(d: date) -> str:
    return f"{d.day} {d.strftime('%b')} {d.year}"


def _fmt_tod(sec: int) -> str:
    h, m = divmod(sec // 60, 60)
    ap = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {ap}"


def parse_when(q: str, order: str = "DMY", today: date | None = None) -> dict | None:
    today = today or date.today()
    text = " " + q.lower() + " "
    w = When()

    def take(m: re.Match) -> None:
        nonlocal text
        a, b = m.span()
        text = text[:a] + " " * (b - a) + text[b:]

    def set_day(d: date | None, label: str | None = None) -> bool:
        if d is None:
            return False
        w.d0 = w.d1 = d
        w.labels.append(label or _fmt_date(d))
        return True

    m = re.search(r"(?<![\d/.\-])(\d{4})-(\d{1,2})-(\d{1,2})(?![\d])", text)
    if m and set_day(_valid(int(m.group(1)), int(m.group(2)), int(m.group(3)))):
        take(m)
    if w.d0 is None:
        m = next((x for x in re.finditer(r"(?<![\d:])(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2}|\d{4}))?(?![\d:])", text)
                  if x.group(3) or "/" in x.group(0)), None)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            y = _year(m.group(3), today)
            if a > 12 and b <= 12:
                d, mo = a, b
            elif b > 12 and a <= 12:
                d, mo = b, a
            elif order == "MDY":
                d, mo = b, a
            else:
                d, mo = a, b
            dt = _valid(y, mo, d)
            if dt and not m.group(3):
                dt = _past(dt, today)
            if set_day(dt):
                if a <= 12 and b <= 12 and a != b:
                    alt = _valid(y, d, mo)
                    if alt and not m.group(3):
                        alt = _past(alt, today)
                    w.alt = alt
                    w.raw = m.group(0).strip()
                take(m)
    if w.d0 is None:
        m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + MON + r"\.?,?(?:\s+(\d{4}))?\b", text)
        if m:
            dt = _valid(_year(m.group(3), today), MONTHS[m.group(2)[:3]], int(m.group(1)))
            if dt and not m.group(3):
                dt = _past(dt, today)
            if set_day(dt):
                take(m)
    if w.d0 is None:
        m = re.search(r"\b" + MON + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", text)
        if m:
            dt = _valid(_year(m.group(3), today), MONTHS[m.group(1)[:3]], int(m.group(2)))
            if dt and not m.group(3):
                dt = _past(dt, today)
            if set_day(dt):
                take(m)
    if w.d0 is None:
        m = re.search(r"\b" + MON + r"\.?(?:\s+(\d{4}))?\b", text)
        if m and (m.group(2) or len(m.group(1)) > 3 or re.search(r"\b(in|during|from)\s+" + re.escape(m.group(1)), text)):
            mo = MONTHS[m.group(1)[:3]]
            y = int(m.group(2)) if m.group(2) else (today.year if mo <= today.month else today.year - 1)
            w.d0 = date(y, mo, 1)
            w.d1 = (date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1))
            w.labels.append(f"{w.d0.strftime('%B')} {y}")
            take(m)
    if w.d0 is None:
        rel = [
            (r"\btoday\b", lambda: (today, today, "today")),
            (r"\byesterday\b", lambda: (today - timedelta(days=1), today - timedelta(days=1), "yesterday")),
            (r"\bthis week\b", lambda: (today - timedelta(days=today.weekday()), today, "this week")),
            (r"\blast week\b", lambda: (today - timedelta(days=today.weekday() + 7), today - timedelta(days=today.weekday() + 1), "last week")),
            (r"\bthis month\b", lambda: (today.replace(day=1), today, "this month")),
            (r"\blast month\b", lambda: ((today.replace(day=1) - timedelta(days=1)).replace(day=1), today.replace(day=1) - timedelta(days=1), "last month")),
            (r"\bthis year\b", lambda: (date(today.year, 1, 1), today, "this year")),
            (r"\blast year\b", lambda: (date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), "last year")),
        ]
        for pat, fn in rel:
            m = re.search(pat, text)
            if m:
                w.d0, w.d1, label = fn()
                w.labels.append(label)
                take(m)
                break
    if w.d0 is None:
        m = re.search(r"\b(\d{1,3})\s+days?\s+ago\b", text)
        if m:
            d = today - timedelta(days=int(m.group(1)))
            set_day(d)
            take(m)
    if w.d0 is None:
        m = re.search(r"\b(?:last\s+)?(" + "|".join(WEEKDAYS) + r")\b", text)
        if m:
            back = (today.weekday() - WEEKDAYS.index(m.group(1))) % 7
            if m.group(0).startswith("last") and back == 0:
                back = 7
            set_day(today - timedelta(days=back), f"{m.group(1).title()} {_fmt_date(today - timedelta(days=back))}")
            take(m)
    if w.d0 is None:
        m = re.search(r"\b(?:in|from|during)?\s*(20\d{2})\b", text)
        if m and not re.search(r"\d{5,}", m.group(0)) and int(m.group(1)) <= today.year + 1:
            y = int(m.group(1))
            w.d0, w.d1 = date(y, 1, 1), date(y, 12, 31)
            w.labels.append(str(y))
            take(m)

    m = re.search(r"(?<![\d:])(\d{1,2})[:.](\d{2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?(?![\d:])", text)
    if m and not (m.group(4) is None and f"{int(m.group(1))}:{m.group(2)}" in ASPECTS and w.d0 is None):
        h, mi, se = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        ap = (m.group(4) or "").replace(".", "")
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        if h < 24 and mi < 60:
            w.point = h * 3600 + mi * 60 + se
            w.tol = 30 if m.group(3) else 120
            w.labels.append(("at " if m.group(3) else "around ") + _fmt_tod(w.point))
            take(m)
    if w.point is None:
        m = re.search(r"\b(\d{1,2})\s*(a\.?m\.?|p\.?m\.?)(?=\s|$|[,.])", text)
        if m:
            h = int(m.group(1))
            ap = m.group(2).replace(".", "")
            if 1 <= h <= 12:
                h = (h % 12) + (12 if ap == "pm" else 0)
                w.point = h * 3600
                w.tol = 1800
                w.labels.append(f"around {_fmt_tod(w.point)}")
                take(m)
    if w.point is None:
        m = re.search(r"\b(noon|midday|midnight)\b", text)
        if m:
            w.point = 12 * 3600 if m.group(1) != "midnight" else 0
            w.tol = 1800
            w.labels.append(f"around {m.group(1)}")
            take(m)
    if w.point is None:
        m = re.search(r"\b(morning|afternoon|evening|night|sunrise|sunset)s?\b", text)
        if m and (w.d0 is not None or re.search(r"\b(in the|this|yesterday|every|at)\s+" + m.group(1), q.lower())):
            w.tod = PARTS[m.group(1)]
            w.labels.append(f"in the {m.group(1)}")
            take(m)
    if not w.found:
        return None
    words = [t for t in re.findall(r"[a-z0-9\-:']+", text) if t not in FILLER]
    w.rest = " ".join(words)
    return w.to_dict(q)


def match(captured_at: float | None, duration: float | None, when: dict) -> tuple[bool, float, float | None]:
    if captured_at is None:
        return False, 0.0, None
    t0 = float(captured_at)
    dur = max(0.0, float(duration or 0.0))
    t1 = t0 + dur
    start, end = when.get("start"), when.get("end")
    if start is not None and (t1 < start or t0 >= end):
        return False, 0.0, None
    point, tol, tod = when.get("point"), when.get("tol") or 0, when.get("tod")
    if point is None and tod is None:
        return True, 0.0, None
    days = []
    if start is not None:
        d = datetime.fromtimestamp(start).date()
        last = datetime.fromtimestamp(end - 1).date()
        while d <= last and len(days) < 400:
            days.append(d)
            d += timedelta(days=1)
    else:
        d0 = datetime.fromtimestamp(t0).date()
        days = [d0 - timedelta(days=1), d0, d0 + timedelta(days=1)]
    best: tuple[bool, float, float | None] = (False, 0.0, None)
    for d in days:
        midnight = datetime.combine(d, datetime.min.time()).timestamp()
        if point is not None:
            p = midnight + point
            gap = max(0.0, t0 - p, p - t1)
            if gap <= tol and (not best[0] or gap < best[1]):
                offset = min(max(0.0, p - t0), dur) if dur else None
                best = (True, gap, offset)
        else:
            a, b = midnight + tod[0], midnight + tod[1]
            if t1 >= a and t0 <= b:
                return True, 0.0, None
    return best
