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


def item(*, id, source, kind, title, url, ministry="", agency="", notice_no="",
         status="", posted=None, open_date=None, close_date=None, extra=None):
    """공통 스키마. 모든 수집기는 이 형태로 반환.

    kind: notice(사업공고) | forecast(사업예고) | signal(수요조사·설명회 등 공지)
    """
    return {
        "id": id,
        "source": source,
        "kind": kind,
        "title": clean(title),
        "ministry": clean(ministry),
        "agency": clean(agency),
        "notice_no": clean(notice_no),
        "status": clean(status),
        "posted": posted,
        "open_date": open_date,
        "close_date": close_date,
        "url": url,
        "extra": extra or {},
    }
