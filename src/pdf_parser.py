"""PDF -> 텍스트 추출 모듈.

강의계획서 PDF에서 평문 텍스트를 뽑아낸다. 이 텍스트는 llm_extractor.py가
구조화(JSON)하는 입력으로 사용된다.
"""
from __future__ import annotations

try:
    import pdfplumber
except ImportError:  # pdfplumber 미설치 시 친절한 안내
    pdfplumber = None


def extract_text(pdf_path: str) -> str:
    """PDF 파일에서 전체 텍스트를 추출해 하나의 문자열로 반환."""
    if pdfplumber is None:
        raise RuntimeError(
            "pdfplumber 가 설치되어 있지 않습니다. `pip install -r requirements.txt` 를 실행하세요."
        )
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return "\n".join(pages)


if __name__ == "__main__":
    import sys

    print(extract_text(sys.argv[1])[:2000])
