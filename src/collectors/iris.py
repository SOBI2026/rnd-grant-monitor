"""IRIS(범부처통합연구지원시스템) 수집기.

- 사업공고: /contents/retrieveBsnsAncmBtinSituList.do (POST, JSON)
- 사업예고: /contents/retrieveAncmPrntcList.do (POST, JSON) → 선제 신호
공식 API가 아닌 화면 내부 JSON이므로 사이트 개편 시 깨질 수 있음.
"""
import re
from datetime import timedelta

from common import (item, norm_date, polite_get, polite_post, session,
                    today_kst)

BASE = "https://www.iris.go.kr"
LIST_VIEW = BASE + "/contents/retrieveBsnsAncmBtinSituListView.do"
LIST_JSON = BASE + "/contents/retrieveBsnsAncmBtinSituList.do"
PRNTC_VIEW = BASE + "/contents/retrieveAncmPrntcListView.do"
PRNTC_JSON = BASE + "/contents/retrieveAncmPrntcList.do"
DETAIL = BASE + "/contents/retrieveBsnsAncmView.do?ancmId={}"

# ancmIng=접수중, ancmPre=접수예정, ancmEnd=마감
RECENT_END_DAYS = 30      # 공고 목록에 남길 최근 마감 공고
HISTORY_DAYS = 400        # 예측용 과거 공고 (관심 부처만)
PRE_LOOKBACK_DAYS = 120   # 접수예정은 오래된 미정리 글이 많아 최근 게시분만
MAX_PAGES = 80
# 관심 부처 코드 (IRIS 검색조건 blngGovdSe)
FOCUS_GOVD = {"AR4012": "보건복지부", "AR4014": "식품의약품안전처",
              "AR4933": "질병관리청", "AR4999": "범부처"}
# 연구자 대상 행정 접수·테스트 글 제외
NOISE = re.compile(r"연차실적|실적계획서|단계평가|보고서\s*접수|협약변경|^\s*test\s*$|테스트",
                   re.I)


def _noise(title):
    t = title or ""
    return bool(NOISE.search(t)) or len(re.findall(r"[가-힣]", t)) < 5


def _post_json(s, url, referer, data):
    r = polite_post(s, url, data=data, headers={
        "X-Requested-With": "XMLHttpRequest", "Referer": referer})
    return r.json()


def _to_item(r, kind):
    aid = r.get("ancmId")
    return item(
        id=f"iris-{aid}", source="IRIS", kind=kind,
        title=r.get("ancmTl"), url=DETAIL.format(aid),
        ministry=r.get("blngGovdSeNm") or r.get("blngGovdSe"),
        agency=r.get("sorgnNm"), notice_no=r.get("ancmNo"),
        type=r.get("pbofrTpSeNmLst") or "",
        status=r.get("rcveSttSeNmLst") or "",
        posted=norm_date(r.get("ancmDe")),
        open_date=norm_date(r.get("rcveStrDe")),
        close_date=norm_date(r.get("rcveEndDe")),
        extra={"raw_status": r.get("rcveSttSeNmLst") or "",
               "raw_phase": r.get("rcveStt") or ""})


def _crawl(s, params, kind, posted_cutoff=None, stop_when_old=False):
    """페이지를 끝까지 넘기며 수집. stop_when_old면 한 페이지 전체가
    cutoff 이전일 때 중단(목록이 공고일 내림차순이라는 전제)."""
    out = {}
    page = 1
    while page <= MAX_PAGES:
        d = _post_json(s, LIST_JSON, LIST_VIEW, {**params, "pageIndex": page})
        rows = d.get("listBsnsAncmBtinSitu") or []
        old = 0
        for r in rows:
            posted = norm_date(r.get("ancmDe"))
            if posted_cutoff and (not posted or posted < posted_cutoff):
                old += 1
                continue
            if _noise(r.get("ancmTl")):
                continue
            it = _to_item(r, kind)
            out[it["id"]] = it
        info = d.get("paginationInfo") or {}
        if not rows or page >= int(info.get("totalPageCount") or 1):
            break
        if stop_when_old and old == len(rows):
            break
        page += 1
    return out


def _cut(days):
    return (today_kst() - timedelta(days=days)).isoformat()


def fetch_notices():
    """접수중·접수예정(전 부처) + 최근 30일 마감(전 부처)."""
    s = session()
    polite_get(s, LIST_VIEW)  # 세션 쿠키 확보
    out = {}
    out.update(_crawl(s, {"ancmPrg": "ancmIng"}, "notice"))
    out.update(_crawl(s, {"ancmPrg": "ancmPre"}, "notice",
                      posted_cutoff=_cut(PRE_LOOKBACK_DAYS)))
    out.update(_crawl(s, {"ancmPrg": "ancmEnd"}, "notice",
                      posted_cutoff=_cut(RECENT_END_DAYS), stop_when_old=True))
    return list(out.values())


def fetch_history():
    """관심 부처의 과거 마감 공고(약 13개월). 반복 사업 시점 예측용."""
    s = session()
    polite_get(s, LIST_VIEW)
    out = {}
    for code in FOCUS_GOVD:
        out.update(_crawl(s, {"ancmPrg": "ancmEnd", "blngGovdSeArr": code},
                          "history", posted_cutoff=_cut(HISTORY_DAYS),
                          stop_when_old=True))
    return list(out.values())


def fetch_forecasts():
    s = session()
    polite_get(s, PRNTC_VIEW)
    out = {}
    page = 1
    while page <= 80:
        d = _post_json(s, PRNTC_JSON, PRNTC_VIEW,
                       {"pageIndex": page, "pageUnit": 100})
        rows = d.get("listAncmPrntc") or []
        for r in rows:
            if str(r.get("bsnsYy") or "0") < str(today_kst().year):
                continue  # 지난 연도 예고 제외
            no = r.get("bsnsPrntcNo")
            out[f"iris-prntc-{no}"] = item(
                id=f"iris-prntc-{no}", source="IRIS", kind="forecast",
                title=r.get("ancmPrntcTl"), url=PRNTC_VIEW,
                ministry=r.get("blngGovdSe"), agency=r.get("sorgnNm"),
                status=r.get("bsnsSpchClSeNm") or "",
                posted=norm_date(r.get("regDt")),
                extra={
                    "year": r.get("bsnsYy"),
                    "content": (r.get("bsnsCn") or "")[:800],
                    "purpose": (r.get("bsnsPursCn") or "")[:500],
                    "field": (r.get("sprtFildCn") or "")[:500],
                    "budget_min": r.get("sprtMinRsctAm"),
                    "budget_max": r.get("sprtMxRsctAm"),
                    "period": r.get("sprtPridSe"),
                    "expected": r.get("bsnsSpchClSeNm"),
                })
        info = d.get("paginationInfo") or {}
        if not rows or page >= int(info.get("totalPageCount") or 1):
            break
        page += 1
    return list(out.values())
