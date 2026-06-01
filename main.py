"""SyllaSync 진입점.

사용법
------
  python main.py            # 웹 서버 실행 (http://127.0.0.1:5000)
  python main.py --cli      # sample_input.json 으로 콘솔에서 캘린더 생성 + semester.ics 저장

웹 없이 빠르게 테스트하려면 --cli 를 쓰세요.
"""
from __future__ import annotations

import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "data", "courses.json")
SAMPLE_INPUT = os.path.join(BASE_DIR, "sample_input.json")


def run_cli():
    from src.calendar_builder import load_courses, build_calendar
    from src.ics_export import save_ics

    data = load_courses(DATA_PATH)
    with open(SAMPLE_INPUT, encoding="utf-8") as f:
        selected = json.load(f)["selected_courses"]

    cal = build_calendar(data, selected)

    print("=" * 60)
    print("선택 과목:", ", ".join(c["name"] for c in cal["courses"]))
    print("=" * 60)

    print("\n[통합 일정 - 날짜순]")
    for e in cal["events"]:
        flag = "" if e["date_confirmed"] else "  (추정)"
        t = (" " + e["time"]) if e["time"] else ""
        print(f"  {e['date']}{t}  [{e['type']}] {e['course']} · {e['title']}{flag}")

    if cal["overloaded_weeks"]:
        print("\n[⚠️ 과부하 주의 주차]")
        for w in cal["overloaded_weeks"]:
            titles = ", ".join(x["title"] for x in w["events"])
            print(f"  {w['start']} 주: {w['count']}건 ({titles})")

    if cal["tbd_events"]:
        print("\n[📌 날짜 미정 (강의 중 공지)]")
        for e in cal["tbd_events"]:
            wk = f" (약 {e['week']}주차)" if e["week"] else ""
            print(f"  {e['course']} · {e['title']}{wk}")

    out = os.path.join(BASE_DIR, "semester.ics")
    save_ics(cal, out, "내 학기 일정")
    print(f"\n✅ 캘린더 파일 저장: {out}")
    print("   (구글/애플 캘린더에서 import 하세요.)")


def run_web():
    from src.app import app
    print("SyllaSync 웹 서버 실행 → http://127.0.0.1:5000  (종료: Ctrl+C)")
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    if "--cli" in sys.argv:
        run_cli()
    else:
        run_web()
