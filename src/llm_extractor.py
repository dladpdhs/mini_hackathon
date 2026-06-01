"""강의계획서 텍스트 -> 구조화 JSON 추출 (하이브리드).

동작 방식 (우선순위):
1. 환경변수 OPENAI_API_KEY 또는 ANTHROPIC_API_KEY 가 있으면 -> 실제 LLM 호출로 추출
2. 키가 없으면 -> 규칙 기반(휴리스틱) 파서로 최대한 추출
   (과목명, 주차별 강의표, 평가방법/학점, 일정 이벤트를 패턴으로 인식)

이렇게 하면 API 키가 있는 사람은 새 PDF도 정확히 분석할 수 있고,
키가 없는 채점자도 프로그램을 무조건 실행할 수 있다.
"""
from __future__ import annotations

import json
import os
import re
import datetime as dt

SEMESTER_START = dt.date(2026, 3, 2)  # 2026-1학기 1주차 월요일

EXTRACTION_PROMPT = """You are a syllabus parser. Read the following university course
syllabus text and return a STRICT JSON object with this schema:

{
  "name": "<course name in its original language>",
  "name_en": "<english name or empty>",
  "credits": <integer or null>,
  "instructor": "<instructor or empty>",
  "class_time": "<class time or empty>",
  "grading": "<one-line grading breakdown>",
  "weekly": [{"week": <int>, "topic": "<lecture topic for that week>"}],
  "events": [
    {"title": "<e.g. HW #1 due, Midterm, Quiz 2, 과제 1>",
     "type": "assignment|quiz|exam|presentation|lecture",
     "date": "YYYY-MM-DD or null if not given",
     "time": "HH:MM or null",
     "week": <int or null, the week number if only the week is known>,
     "date_confirmed": <true if an explicit date is given, false if 'TBD/announced later'>}
  ]
}

Rules:
- The semester starts on 2026-03-02 (week 1 Monday). If only a week is given, set "week"
  and leave "date" null with date_confirmed=false.
- Capture every assignment deadline, quiz, exam (midterm/final), and presentation.
- Return ONLY the JSON, no commentary.

SYLLABUS TEXT:
"""


def _has_api_key() -> bool:
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))


def extract_with_llm(text: str) -> dict:
    """실제 LLM API 호출. openai 또는 anthropic SDK 사용."""
    prompt = EXTRACTION_PROMPT + text[:12000]

    if os.getenv("ANTHROPIC_API_KEY"):
        import anthropic

        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text
    else:
        from openai import OpenAI

        client = OpenAI()
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = resp.choices[0].message.content

    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    return json.loads(raw)


# ===========================================================================
# 규칙 기반(휴리스틱) 폴백 파서 — API 키 없이도 동작
# ===========================================================================
_NAME_STOPWORDS = [
    "2026학년도", "2026", "학년도", "1학기", "2학기", "spring", "fall",
    "강의계획서", "강의계획표", "syllabus", "course", "0", "2026-1", "2026-2",
]


def _name_from_filename(filename: str | None) -> str:
    """파일명에서 과목명을 추정. 예) '2026학년도+1학기+통계학실험+강의계획서.pdf' -> '통계학실험'."""
    if not filename:
        return ""
    stem = os.path.splitext(os.path.basename(filename))[0]
    tokens = re.split(r"[\s_+\-]+", stem)
    kept = []
    for tok in tokens:
        low = tok.lower()
        if not tok or tok.isdigit():  # 순수 숫자 토큰(연도/레벨/분반)은 제외
            continue
        if any(sw in low for sw in _NAME_STOPWORDS):
            continue
        kept.append(tok)
    return " ".join(kept).strip()


def _name_from_text(text: str) -> str:
    """본문에서 과목명 패턴을 찾는다 (form-table / 영문 제목 등)."""
    # 1) form-table: '교과목명 <이름> 학점' 또는 '강좌번호 <이름> 학점' 사이의 이름
    for pat in (r"교과목명\s+(.+?)\s+학점", r"강좌번호\s+([^\d\n]{2,20}?)\s+학점"):
        m = re.search(pat, text)
        if m and re.search(r"[가-힣A-Za-z]", m.group(1)):
            return m.group(1).strip()
    # 2) 'XXX 강의계획표/강의계획서' 앞의 제목
    m = re.search(r"([가-힣A-Za-z][가-힣A-Za-z0-9 ]{2,30})\s*강의계획[표서]", text)
    if m:
        return m.group(1).strip()
    # 3) 첫 줄이 영문 제목 형태인 경우 (예: 'English Foundations (008)')
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if re.match(r"^[A-Z][A-Za-z ]{3,40}(\(\d+\))?$", first):
        return first
    return ""


def _extract_name(text: str, filename: str | None) -> str:
    return _name_from_filename(filename) or _name_from_text(text) or "(제목 미상)"


def _extract_credits(text: str):
    m = re.search(r"학점\s*(\d{1,2})", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{1,2})\s*credit", text, re.I)
    return int(m.group(1)) if m else None


def _extract_grading(text: str) -> str:
    for ln in text.splitlines():
        if ("성적비율" in ln or "Evaluation" in ln or "평가방법" in ln) and re.search(r"\d", ln):
            return ln.strip()[:120]
    for ln in text.splitlines():  # '출석'과 '%'가 함께 있는 줄
        if "출석" in ln and "%" in ln:
            return ln.strip()[:120]
    return ""


# 줄 시작 또는 짧은 라벨(예: '계획 3주') 뒤의 주차 표기를 잡는다.
_WEEK_PATTERNS = [
    re.compile(r"(?:^|\s)(\d{1,2})\s*주(?![가-힣])"),   # '1주', '계획 3주' (단 '13주에...' 같은 접속은 제외)
    re.compile(r"(?:^|\s)[Ww]eek\s*(\d{1,2})"),          # 'Week 1'
]


def _extract_weekly(text: str) -> list[dict]:
    lines = text.splitlines()
    weekly = {}
    for i, line in enumerate(lines):
        wk = None
        for pat in _WEEK_PATTERNS:
            m = pat.search(line)
            if m and m.start() <= 6:  # 주차 표기는 줄 앞쪽에만 (라벨 허용)
                wk = int(m.group(1))
                topic = line[m.end():]
                break
        if wk is None or not (1 <= wk <= 20):
            continue
        topic = topic.strip(" :\t")
        # 앞에 붙은 '날짜 범위'(예: 3-2 ~ 3-6)나 괄호만 제거 (챕터 번호 '1장' 등은 보존)
        topic = re.sub(r"^\(?\d{1,2}\s*[-/]\s*\d{1,2}\s*~\s*\d{1,2}\s*[-/]\s*\d{1,2}\)?\s*", "", topic)
        topic = re.sub(r"^\([^)]*\)\s*", "", topic).strip()
        if len(topic) < 2:  # 같은 줄에 주제가 없으면 다음 줄 참고
            for j in range(i + 1, min(i + 3, len(lines))):
                nxt = lines[j].strip()
                if nxt and not any(p.match(lines[j]) for p in _WEEK_PATTERNS):
                    topic = nxt
                    break
        if wk not in weekly and len(topic) >= 2:
            weekly[wk] = topic[:120]

    # 'N회차: 주제' 형식(세미나형 강의) 추가 — 2단 편집으로 줄이 섞여도 콜론 기준으로 잡는다.
    if not weekly:
        for m in re.finditer(r"(\d{1,2})\s*회차\s*[:：]\s*([^\n]{2,60})", text):
            wk = int(m.group(1))
            if 1 <= wk <= 20 and wk not in weekly:
                weekly[wk] = m.group(2).strip()[:120]

    return [{"week": w, "topic": t} for w, t in sorted(weekly.items())]


_DATE_PATTERNS = [
    re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일"),    # 6월 13일
    re.compile(r"(\d{1,2})\s*[/]\s*(\d{1,2})"),         # 4/24
]
_EVENT_KEYWORDS = {
    "exam": ["midterm", "final exam", "중간고사", "기말고사", "종합시험", "기말시험"],
    "quiz": ["quiz", "퀴즈"],
    "assignment": ["hw #", "homework", "assignment", "과제", "보고서 제출", "제출 마감"],
    "presentation": ["발표", "presentation"],
}


def _classify(text_low: str):
    for t, kws in _EVENT_KEYWORDS.items():
        if any(k in text_low for k in kws):
            return t
    return None


def _guess_md(month: int, day: int):
    try:
        return dt.date(2026, month, day).isoformat()
    except ValueError:
        return None


# --- 요일 인식 ---------------------------------------------------------------
_WD_KO = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
_WD_EN = [  # 긴 이름 먼저 매칭
    ("monday", 0), ("tuesday", 1), ("wednesday", 2), ("thursday", 3),
    ("friday", 4), ("saturday", 5), ("sunday", 6),
    ("mon", 0), ("tue", 1), ("wed", 2), ("thu", 3), ("fri", 4), ("sat", 5), ("sun", 6),
]


def find_weekday(text: str):
    """문자열에서 첫 번째 요일을 찾아 0(월)~6(일) 인덱스로 반환. 없으면 None."""
    low = text.lower()
    for name, idx in _WD_EN:
        if re.search(r"\b" + name, low):
            return idx
    for ch, idx in _WD_KO.items():
        if ch + "요일" in text:
            return idx
    return None


def parse_meeting_weekdays(text: str) -> list[int]:
    """수업 요일 집합을 추정. 예: '화/목', 'Class Time: Tuesday & Thursday' -> [1, 3]."""
    days = set()
    for m in re.finditer(r"([월화수목금토일])\s*[/·,~&]\s*([월화수목금토일])", text):
        days.add(_WD_KO[m.group(1)])
        days.add(_WD_KO[m.group(2)])
    for ch, idx in _WD_KO.items():
        if ch + "요일" in text:
            days.add(idx)
    for ln in text.splitlines():  # 영어는 수업시간 줄에서만 (오탐 방지)
        low = ln.lower()
        if "class time" in low or "수업시간" in low or "class:" in low:
            for name, idx in _WD_EN:
                if re.search(r"\b" + name, low):
                    days.add(idx)
    return sorted(days)


def _extract_events(text: str, weekly: list[dict]) -> list[dict]:
    events = []
    seen = set()

    # (1) 주차표 안의 과제/시험/발표 표시 -> 주차 기준 이벤트 (날짜 미정)
    for wk in weekly:
        t = _classify(wk["topic"].lower())
        if t and t != "lecture":
            title = wk["topic"][:50]
            key = (title, wk["week"])
            if key not in seen:
                seen.add(key)
                events.append({"title": title, "type": t, "date": None,
                               "time": None, "week": wk["week"],
                               "weekday": find_weekday(wk["topic"]), "date_confirmed": False})

    # (2) 명시적 날짜가 있는 줄 -> 확정 이벤트
    for line in text.splitlines():
        low = line.lower()
        t = _classify(low)
        if not t:
            continue
        date_iso = None
        for pat in _DATE_PATTERNS:
            m = pat.search(line)
            if m:
                date_iso = _guess_md(int(m.group(1)), int(m.group(2)))
                if date_iso:
                    break
        if not date_iso:
            continue
        title = line.strip()[:50]
        key = (title, date_iso)
        if key in seen:
            continue
        seen.add(key)
        events.append({"title": title, "type": t, "date": date_iso,
                       "time": None, "week": None,
                       "weekday": find_weekday(line), "date_confirmed": True})

    return events


def heuristic_extract(text: str, filename: str | None = None) -> dict:
    """LLM 없이 패턴으로 과목 정보를 최대한 추출한다."""
    weekly = _extract_weekly(text)
    return {
        "name": _extract_name(text, filename),
        "name_en": "",
        "credits": _extract_credits(text),
        "instructor": "",
        "class_time": "",
        "meeting_weekdays": parse_meeting_weekdays(text),
        "grading": _extract_grading(text),
        "weekly": weekly,
        "events": _extract_events(text, weekly),
    }


def extract_course(pdf_path: str) -> dict:
    """PDF 경로를 받아 구조화된 과목 dict 반환 (하이브리드)."""
    from .pdf_parser import extract_text

    text = extract_text(pdf_path)
    if _has_api_key():
        try:
            data = extract_with_llm(text)
            if not data.get("name"):
                data["name"] = _extract_name(text, pdf_path)
            data["_extracted_by"] = "llm"
            return data
        except Exception as e:  # 호출 실패 시 휴리스틱으로 폴백
            print(f"[llm_extractor] LLM 호출 실패, 휴리스틱으로 폴백: {e}")
    data = heuristic_extract(text, pdf_path)
    data["_extracted_by"] = "heuristic"
    return data
