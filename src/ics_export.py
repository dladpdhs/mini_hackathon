"""통합 캘린더 -> .ics (iCalendar) 파일 생성.

표준 라이브러리만 사용하므로 추가 설치가 필요 없다.
생성된 .ics 는 구글/애플 캘린더에 그대로 import 할 수 있다.
"""
from __future__ import annotations

import datetime as dt

_TYPE_EMOJI = {
    "exam": "[시험]",
    "quiz": "[퀴즈]",
    "assignment": "[과제]",
    "presentation": "[발표]",
    "lecture": "[강의]",
}


def _fmt_date(d: str) -> str:
    return d.replace("-", "")


def _escape(text: str) -> str:
    return text.replace(",", "\\,").replace(";", "\\;")


def build_ics(calendar: dict, calendar_name: str = "학기 일정") -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SyllaSync//Semester Calendar//KO",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{_escape(calendar_name)}",
    ]
    stamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    for i, ev in enumerate(calendar["events"]):
        date_compact = _fmt_date(ev["date"])
        tag = _TYPE_EMOJI.get(ev["type"], "")
        summary = f"{tag} {ev['course']} - {ev['title']}"
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:syllasync-{i}-{date_compact}@local")
        lines.append(f"DTSTAMP:{stamp}")
        if ev.get("time"):
            hh, mm = ev["time"].split(":")
            start = f"{date_compact}T{hh}{mm}00"
            end_dt = dt.datetime.strptime(start, "%Y%m%dT%H%M%S") + dt.timedelta(hours=2)
            lines.append(f"DTSTART:{start}")
            lines.append(f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}")
        else:
            # 종일 일정
            lines.append(f"DTSTART;VALUE=DATE:{date_compact}")
        desc = ev["course"]
        if not ev["date_confirmed"]:
            desc += " (날짜 미확정 - 주차 기준 추정)"
        lines.append(f"SUMMARY:{_escape(summary)}")
        lines.append(f"DESCRIPTION:{_escape(desc)}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def save_ics(calendar: dict, path: str, calendar_name: str = "학기 일정") -> str:
    content = build_ics(calendar, calendar_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
