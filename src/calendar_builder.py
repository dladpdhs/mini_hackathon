"""여러 과목의 일정을 하나의 학기 캘린더로 통합하고, 과부하 주차를 감지한다."""
from __future__ import annotations

import json
import calendar as _calmod
import datetime as dt
from collections import defaultdict

from .llm_extractor import parse_meeting_weekdays

OVERLOAD_THRESHOLD = 3  # 같은 주에 이만큼 이상 마감/시험이 몰리면 '과부하'로 표시
UPCOMING_DAYS = 14      # 오늘 기준 며칠 안의 마감을 '임박'으로 표시

# 과목(분반)별 구분 색 팔레트
_PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c",
            "#0891b2", "#db2777", "#65a30d", "#7c3aed", "#0d9488"]


def course_label(course: dict) -> str:
    """선택 목록/범례에 쓸 표시 이름. 예: '대학글쓰기 1 · 이지원 (002)'."""
    parts = [course["name"]]
    if course.get("instructor"):
        parts.append(" · " + course["instructor"])
    if course.get("section"):
        parts.append(f" ({course['section']})")
    return "".join(parts)


def load_courses(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _semester_start(data: dict) -> dt.date:
    return dt.date.fromisoformat(data["semester"]["start_date"])


def week_to_date(start: dt.date, week: int) -> dt.date:
    """주차 번호 -> 해당 주 월요일 날짜."""
    return start + dt.timedelta(days=7 * (week - 1))


def _course_weekdays(course: dict) -> list[int]:
    """과목의 수업 요일 목록(0=월~6=일). 데이터에 명시됐거나 class_time에서 추정."""
    if course.get("meeting_weekdays"):
        return list(course["meeting_weekdays"])
    return parse_meeting_weekdays(course.get("class_time", "") or "")


def _resolve_date(start: dt.date, ev: dict, meeting_wds: list[int]):
    """이벤트의 날짜를 확정한다. (resolved_date, confirmed) 반환.

    - 명시적 날짜가 있으면 그대로 사용 (확정).
    - 주차만 있으면 그 주로 매핑하되, 이벤트에 요일이 있으면 그 요일,
      없으면 수업 요일 중 마지막 날(시험/마감이 주 후반인 경우가 많음)에 배치 (추정).
    """
    if ev.get("date"):
        return dt.date.fromisoformat(ev["date"]), bool(ev.get("date_confirmed", True))
    if ev.get("week"):
        monday = week_to_date(start, int(ev["week"]))
        wd = ev.get("weekday")
        if wd is None and meeting_wds:
            wd = meeting_wds[-1]
        return monday + dt.timedelta(days=wd or 0), False  # 추정 날짜
    return None, False


def build_calendar(data: dict, selected_ids: list[str]) -> dict:
    """선택한 과목들의 일정을 통합한 캘린더 데이터를 만든다.

    반환:
      {
        "events": [통합·정렬된 이벤트],
        "overloaded_weeks": [{"week", "start", "count", "events"}],
        "weekly_view": [{"week", "start", "lectures":[...], "events":[...]}],
        "courses": [선택 과목 메타],
        "tbd_events": [날짜 미정 이벤트],
      }
    """
    start = _semester_start(data)
    by_id = {c["course_id"]: c for c in data["courses"]}
    selected = [by_id[cid] for cid in selected_ids if cid in by_id]

    meeting = {c["course_id"]: _course_weekdays(c) for c in selected}
    colors = {c["course_id"]: _PALETTE[i % len(_PALETTE)] for i, c in enumerate(selected)}
    labels = {c["course_id"]: course_label(c) for c in selected}

    events = []
    for course in selected:
        cid = course["course_id"]
        for ev in course.get("events", []):
            resolved, confirmed = _resolve_date(start, ev, meeting[cid])
            events.append({
                "course": labels[cid],
                "course_id": cid,
                "color": colors[cid],
                "title": ev["title"],
                "type": ev.get("type", "lecture"),
                "date": resolved.isoformat() if resolved else None,
                "time": ev.get("time"),
                "date_confirmed": confirmed,
                "week": ev.get("week"),
            })

    # 날짜 있는 것 / 미정인 것 분리
    dated = [e for e in events if e["date"]]
    tbd = [e for e in events if not e["date"]]
    dated.sort(key=lambda e: (e["date"], e["time"] or ""))

    # 과부하 주차 감지 (ISO 주 기준)
    by_week = defaultdict(list)
    for e in dated:
        d = dt.date.fromisoformat(e["date"])
        iso_year, iso_week, _ = d.isocalendar()
        by_week[(iso_year, iso_week)].append(e)
    overloaded = []
    for (iy, iw), evs in sorted(by_week.items()):
        if len(evs) >= OVERLOAD_THRESHOLD:
            monday = dt.date.fromisocalendar(iy, iw, 1)
            overloaded.append({
                "week_label": f"{monday.isoformat()} 주",
                "start": monday.isoformat(),
                "count": len(evs),
                "events": evs,
            })

    # 주차별 보기 (강의 주제 + 이벤트)
    weekly_view = []
    total_weeks = data["semester"].get("weeks", 15)
    for w in range(1, total_weeks + 1):
        wk_start = week_to_date(start, w)
        wk_end = wk_start + dt.timedelta(days=6)
        lectures = []
        for course in selected:
            cid = course["course_id"]
            wds = meeting[cid] or [0]  # 수업 요일 모름 -> 월요일
            for wk in course.get("weekly", []):
                if wk.get("week") == w:
                    for wd in wds:  # 수업 요일마다 강의 칸 배치
                        lectures.append({
                            "course": labels[cid],
                            "color": colors[cid],
                            "topic": wk["topic"],
                            "date": (wk_start + dt.timedelta(days=wd)).isoformat(),
                        })
        wk_events = [
            e for e in dated
            if wk_start <= dt.date.fromisoformat(e["date"]) <= wk_end
        ]
        weekly_view.append({
            "week": w,
            "start": wk_start.isoformat(),
            "end": wk_end.isoformat(),
            "lectures": lectures,
            "events": wk_events,
        })

    # 마감 임박 (오늘 기준 UPCOMING_DAYS 이내)
    today = dt.date.today()
    horizon = today + dt.timedelta(days=UPCOMING_DAYS)
    upcoming = []
    for e in dated:
        d = dt.date.fromisoformat(e["date"])
        if today <= d <= horizon and e["type"] != "lecture":
            ev = dict(e)
            ev["d_day"] = (d - today).days
            upcoming.append(ev)

    return {
        "events": dated,
        "tbd_events": tbd,
        "overloaded_weeks": overloaded,
        "weekly_view": weekly_view,
        "upcoming": upcoming,
        "today": today.isoformat(),
        "courses": [{"course_id": c["course_id"], "name": labels[c["course_id"]],
                     "color": colors[c["course_id"]]} for c in selected],
    }


def build_month_grid(cal: dict) -> list[dict]:
    """build_calendar 결과를 월별 달력(그리드) 형태로 변환.

    각 주차의 강의 주제는 그 주 월요일 칸에, 과제/시험은 해당 날짜 칸에 표시한다.
    반환: [{"label","year","month","weeks":[[day,...]]}, ...]
      day = {"day":int|None, "date":str|None, "in_month":bool,
             "events":[...], "lectures":[{"course","topic"}]}
    """
    events_by_date = defaultdict(list)
    for e in cal["events"]:
        events_by_date[e["date"]].append(e)

    lectures_by_date = defaultdict(list)  # 각 강의 -> 실제 수업 요일 칸
    all_dates = list(events_by_date.keys())
    for wk in cal["weekly_view"]:
        for lec in wk["lectures"]:
            d = lec.get("date", wk["start"])
            lectures_by_date[d].append(lec)
            all_dates.append(d)
    if not all_dates:
        return []

    dmin = min(dt.date.fromisoformat(d) for d in all_dates)
    dmax = max(dt.date.fromisoformat(d) for d in all_dates)

    today = dt.date.today()
    cal_obj = _calmod.Calendar(firstweekday=0)  # 월요일 시작
    months = []
    y, m = dmin.year, dmin.month
    while (y, m) <= (dmax.year, dmax.month):
        weeks = []
        for week in cal_obj.monthdatescalendar(y, m):
            row = []
            for day in week:
                iso = day.isoformat()
                row.append({
                    "day": day.day,
                    "date": iso,
                    "in_month": day.month == m,
                    "is_today": day == today,
                    "weekend": day.weekday() >= 5,
                    "events": events_by_date.get(iso, []),
                    "lectures": lectures_by_date.get(iso, []),
                })
            weeks.append(row)
        months.append({"label": f"{y}년 {m}월", "year": y, "month": m, "weeks": weeks})
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return months
