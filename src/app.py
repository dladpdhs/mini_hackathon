"""SyllaSync 웹앱 (Flask).

- 메인 화면: 과목 검색/체크 + 강의계획서 PDF 업로드
- 결과 화면: 달력(월 그리드) + 주차별 일정 + 과부하 경고 + 날짜 미정 + .ics 다운로드
"""
from __future__ import annotations

import io
import os
import tempfile

from flask import (
    Flask, request, render_template_string, send_file, redirect, url_for, flash
)

from .calendar_builder import load_courses, build_calendar, build_month_grid
from .ics_export import build_ics
from .llm_extractor import extract_course, _has_api_key, _name_from_filename

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(BASE_DIR, "data", "courses.json")

app = Flask(__name__)
app.secret_key = "syllasync-demo"

# 파일 데이터 + 업로드로 추가된 과목을 함께 보관 (간단한 인메모리 저장)
DATASET = load_courses(DATA_PATH)


def _all_courses():
    return DATASET["courses"]


PAGE = """
<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SyllaSync · 강의계획서 → 학기 캘린더</title>
<script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-slate-50 text-slate-800">
<div class="max-w-3xl mx-auto p-6">
  <h1 class="text-2xl font-bold">📅 SyllaSync</h1>
  <p class="text-slate-500 mb-2">강의계획서를 분석해 한 학기 캘린더(퀴즈·과제·시험)를 자동으로 만들어 드립니다.</p>
  <p class="text-xs mb-6 {{ 'text-green-600' if has_key else 'text-amber-600' }}">
    LLM 모드: {{ 'API 키 감지됨 — 업로드 PDF를 실시간 분석합니다.' if has_key else 'API 키 없음 — 내장 데이터셋 + 규칙 기반 분석으로 동작합니다.' }}
  </p>

  {% with msgs = get_flashed_messages() %}{% if msgs %}
  <div class="bg-blue-100 text-blue-800 p-3 rounded mb-4 text-sm">{{ msgs[0] }}</div>
  {% endif %}{% endwith %}

  <form action="{{ url_for('generate') }}" method="post" class="bg-white rounded-xl shadow p-5 mb-6">
    <label class="font-semibold">1) 듣는 과목을 선택하세요</label>
    <input id="search" placeholder="과목 검색..." onkeyup="filt()"
           class="w-full border rounded px-3 py-2 my-3 text-sm">
    <div id="list" class="space-y-2 max-h-72 overflow-auto">
      {% for c in courses %}
      <label class="course flex items-center gap-2 p-2 rounded hover:bg-slate-50 cursor-pointer">
        <input type="checkbox" name="course" value="{{ c.course_id }}">
        <span class="font-medium">{{ c.name }}</span>
        <span class="text-xs text-slate-400">{{ c.name_en }} · {{ c.credits or '?' }}학점</span>
      </label>
      {% endfor %}
    </div>
    <button class="mt-4 bg-slate-900 text-white px-5 py-2 rounded-lg w-full">학기 캘린더 만들기</button>
  </form>

  <form action="{{ url_for('upload') }}" method="post" enctype="multipart/form-data"
        class="bg-white rounded-xl shadow p-5">
    <label class="font-semibold">2) 또는 새 강의계획서 PDF 업로드</label>
    <input type="file" name="pdf" accept="application/pdf" class="block my-3 text-sm">
    <button class="bg-indigo-600 text-white px-5 py-2 rounded-lg">업로드 & 분석</button>
    <p class="text-xs text-slate-400 mt-2">분석된 과목이 위 목록에 추가됩니다.</p>
  </form>
</div>
<script>
function filt(){let q=document.getElementById('search').value.toLowerCase();
document.querySelectorAll('.course').forEach(e=>{e.style.display=e.innerText.toLowerCase().includes(q)?'':'none';});}
</script>
</body></html>
"""

RESULT = """
<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>학기 캘린더 결과</title><script src="https://cdn.tailwindcss.com"></script>
<style>
  .cell{min-height:84px}
  .chip{font-size:10px;line-height:1.2;border-radius:4px;padding:1px 4px;margin-top:2px;display:block;
        overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
</style></head>
<body class="bg-slate-50 text-slate-800">
<div class="max-w-5xl mx-auto p-6">
  <a href="{{ url_for('index') }}" class="text-sm text-indigo-600">← 다시 선택</a>
  <h1 class="text-2xl font-bold mt-2">📅 {{ cal.courses|length }}개 과목 학기 캘린더</h1>
  <p class="text-slate-500 mb-4">{% for c in cal.courses %}<span class="inline-block bg-slate-200 rounded px-2 py-0.5 text-xs mr-1">{{ c.name }}</span>{% endfor %}</p>

  <a href="{{ ics_url }}" class="inline-block bg-green-600 text-white px-4 py-2 rounded-lg mb-4">⬇ .ics 캘린더 다운로드 (구글/애플 캘린더 import)</a>

  <div class="text-xs mb-4 flex gap-3 flex-wrap">
    <span class="text-purple-600">■ 강의</span>
    <span class="text-blue-600">■ 과제</span>
    <span class="text-orange-600">■ 퀴즈</span>
    <span class="text-red-600">■ 시험</span>
    <span class="text-pink-600">■ 발표</span>
  </div>

  {% if cal.overloaded_weeks %}
  <div class="bg-red-50 border border-red-200 rounded-xl p-4 mb-6">
    <h2 class="font-bold text-red-700">⚠️ 과부하 주의 주차</h2>
    {% for w in cal.overloaded_weeks %}
    <p class="text-sm mt-1 text-red-700">· {{ w.start }} 주: 마감/시험 {{ w.count }}건 몰림
      ({% for e in w.events %}{{ e.title }}{% if not loop.last %}, {% endif %}{% endfor %})</p>
    {% endfor %}
  </div>
  {% endif %}

  <!-- ===== 달력(월 그리드) ===== -->
  {% for mon in months %}
  <h2 class="font-bold mt-6 mb-2">{{ mon.label }}</h2>
  <table class="w-full table-fixed border-collapse bg-white rounded-lg overflow-hidden shadow-sm">
    <thead><tr class="bg-slate-100 text-xs text-slate-500">
      <th class="p-1">월</th><th class="p-1">화</th><th class="p-1">수</th><th class="p-1">목</th>
      <th class="p-1">금</th><th class="p-1 text-red-400">토</th><th class="p-1 text-red-400">일</th>
    </tr></thead>
    <tbody>
    {% for week in mon.weeks %}
      <tr>
      {% for d in week %}
        <td class="cell border align-top p-1 {{ '' if d.in_month else 'bg-slate-50 text-slate-300' }}">
          {% if d.in_month %}
          <div class="text-xs text-slate-400">{{ d.day }}</div>
          {% for l in d.lectures %}
          <span class="chip bg-purple-100 text-purple-700" title="{{ l.course }}: {{ l.topic }}">📘 {{ l.topic }}</span>
          {% endfor %}
          {% for e in d.events %}
          <span class="chip {% if e.type=='exam' %}bg-red-100 text-red-700{% elif e.type=='quiz' %}bg-orange-100 text-orange-700{% elif e.type=='assignment' %}bg-blue-100 text-blue-700{% else %}bg-pink-100 text-pink-700{% endif %}"
                title="{{ e.course }} · {{ e.title }}">{{ e.title }}</span>
          {% endfor %}
          {% endif %}
        </td>
      {% endfor %}
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% endfor %}

  {% if cal.tbd_events %}
  <div class="bg-amber-50 border border-amber-200 rounded-xl p-4 mt-6">
    <h2 class="font-bold text-amber-700">📌 날짜 미정 (강의 중 공지 예정)</h2>
    {% for e in cal.tbd_events %}
    <p class="text-sm mt-1">· {{ e.course }} · {{ e.title }} {% if e.week %}(약 {{ e.week }}주차){% endif %}</p>
    {% endfor %}
  </div>
  {% endif %}
</div></body></html>
"""


@app.route("/")
def index():
    return render_template_string(PAGE, courses=_all_courses(), has_key=_has_api_key())


@app.route("/generate", methods=["POST"])
def generate():
    selected = request.form.getlist("course")
    if not selected:
        flash("최소 한 과목을 선택하세요.")
        return redirect(url_for("index"))
    cal = build_calendar(DATASET, selected)
    months = build_month_grid(cal)
    ics_url = url_for("download_ics", ids=",".join(selected))
    return render_template_string(RESULT, cal=cal, months=months, ics_url=ics_url)


@app.route("/download.ics")
def download_ics():
    selected = request.args.get("ids", "").split(",")
    cal = build_calendar(DATASET, [s for s in selected if s])
    content = build_ics(cal, "내 학기 일정")
    return send_file(
        io.BytesIO(content.encode("utf-8")),
        mimetype="text/calendar",
        as_attachment=True,
        download_name="semester.ics",
    )


@app.route("/upload", methods=["POST"])
def upload():
    f = request.files.get("pdf")
    if not f or not f.filename:
        flash("PDF 파일을 선택하세요.")
        return redirect(url_for("index"))
    # 원본 파일명을 보존해 과목명 추정에 활용 (임시 폴더에 같은 이름으로 저장)
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, os.path.basename(f.filename))
    f.save(path)
    try:
        course = extract_course(path)
    finally:
        try:
            os.unlink(path)
            os.rmdir(tmpdir)
        except OSError:
            pass
    # 과목명이 비었거나 미상이면 파일명에서 보정
    if not course.get("name") or course["name"].startswith("(제목"):
        course["name"] = _name_from_filename(f.filename) or "새 과목"
    course.setdefault("course_id", "uploaded_%d" % len(DATASET["courses"]))
    DATASET["courses"].append(course)
    how = "LLM" if course.get("_extracted_by") == "llm" else "규칙 기반"
    flash(f"'{course.get('name','새 과목')}' 분석 완료 ({how}, 주차 {len(course.get('weekly', []))}개). 목록에서 선택해 캘린더를 만드세요.")
    return redirect(url_for("index"))
