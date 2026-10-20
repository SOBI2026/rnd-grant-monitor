"""공통 유틸: HTTP 세션, 공통 스키마, 날짜 처리."""
import re
import time
from datetime import datetime, timedelta, timezone

import requests

KST = timezone(timedelta(hours=9))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
DELAY = 0.7  # 요청 간 기본 대기(초)
RETRIES = 2   # 타임아웃·5xx 재시도 횟수 (대기 20초, 40초)


def today_kst():
    return datetime.now(KST).date()


def session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    return s


def _call(fn, url, delay, **kw):
    last = None
    for attempt in range(RETRIES + 1):
        time.sleep(delay if attempt == 0 else 20 * attempt)
        try:
            r = fn(url, timeout=30, **kw)
            if r.status_code >= 500:
                raise requests.HTTPError(f"{r.status_code}", response=r)
            r.raise_for_status()
            return r
        except (requests.ConnectionError, requests.Timeout,
                requests.HTTPError) as e:
            last = e
            if isinstance(e, requests.HTTPError) and e.response is not None \
                    and e.response.status_code < 500:
                raise
    raise last


def polite_get(s, url, delay=DELAY, **kw):
    return _call(s.get, url, delay, **kw)


def polite_post(s, url, delay=DELAY, **kw):
    return _call(s.post, url, delay, **kw)


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


def parse_deadline(title, posted):
    """제목 속 마감 표기 추출: '(~10.23.(금)', '(~11월 30일', '(10.16(금), 18:00까지)', '~10/23'.
    게시일보다 앞서면 다음 해로 간주."""
    if not title or not posted:
        return None
    pats = [r"~\s*(\d{1,2})\s*[./]\s*(\d{1,2})",
            r"~\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일",
            r"\(\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?\s*\([월화수목금토일]\)[^)]*까지",
            r"(\d{1,2})\s*월\s*(\d{1,2})\s*일[^)]*까지",
            r"(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?\s*\([월화수목금토일]\)[^)]*마감"]
    for p in pats:
        m = re.search(p, title)
        if m:
            mo, d = int(m.group(1)), int(m.group(2))
            if not (1 <= mo <= 12 and 1 <= d <= 31):
                continue
            y = int(posted[:4])
            cand = f"{y:04d}-{mo:02d}-{d:02d}"
            if cand < posted:
                cand = f"{y + 1:04d}-{mo:02d}-{d:02d}"
            return cand
    return None
