"""공통 유틸: HTTP 세션, 공통 스키마, 날짜 처리."""
import re
import time
from datetime import datetime, timedelta, timezone

import requests

KST = timezone(timedelta(hours=9))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
DELAY = 0.7  # 요청 간 대기(초). 서버 부담 최소화.


def today_kst():
    return datetime.now(KST).date()


def session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    return s


def polite_get(s, url, **kw):
    time.sleep(DELAY)
    r = s.get(url, timeout=30, **kw)
    r.raise_for_status()
    return r


def polite_post(s, url, **kw):
    time.sleep(DELAY)
    r = s.post(url, timeout=30, **kw)
    r.raise_for_status()
    return r


def norm_date(v):
    """'2026.10.16', '2026/10/16', '2026-10-16', epoch(ms) → 'YYYY-MM-DD'."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000, KST).date().isoformat()
    m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", str(v))
    if not m:
        return None
    y, mo, d = map(int, m.groups())
    return f"{y:04d}-{mo:02d}-{d:02d}"


def clean(text):
    if text is None:
        return ""
    text = str(text).replace("？", "-")  # IRIS 공고번호의 깨진 하이픈
    return re.sub(r"\s+", " ", text).strip()


# 공고(notice/history) 필수 필드: 공고명, 공고번호, 공고일자, 공고상태, 공고유형,
# 소관부처, 전문기관, 접수기간(시작·마감)
REQUIRED = ["title", "notice_no", "posted", "status", "type", "ministry",
            "agency", "open_date", "close_date"]


def item(*, id, source, kind, title, url, ministry="", agency="", notice_no="",
         type="", status="", posted=None, open_date=None, close_date=None,
         extra=None):
    """공통 스키마. 모든 수집기는 이 형태로 반환.

    kind: notice(사업공고) | history(과거 공고) | forecast(사업예고)
          | signal(수요조사·설명회 등 공지)
    """
    return {
        "id": id,
        "source": source,
        "kind": kind,
        "title": clean(title),
        "notice_no": clean(notice_no),
        "type": clean(type),
        "ministry": clean(ministry),
        "agency": clean(agency),
        "status": clean(status),
        "posted": posted,
        "open_date": open_date,
        "close_date": close_date,
        "url": url,
        "extra": extra or {},
    }


def compute_status(open_date, close_date, fallback=""):
    """접수기간 기준으로 상태를 다시 계산. 원천 사이트 상태값은 신뢰하지 않음."""
    t = today_kst().isoformat()
    if open_date and t < open_date:
        return "접수예정"
    if close_date and t > close_date:
        return "마감"
    if open_date or close_date:
        return "접수중"
    return fallback or "확인필요"


def missing_fields(it):
    return [k for k in REQUIRED if not it.get(k)]
