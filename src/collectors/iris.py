"""IRIS(범부처통합연구지원시스템) 수집기.

- 사업공고: /contents/retrieveBsnsAncmBtinSituList.do (POST, JSON)
- 사업예고: /contents/retrieveAncmPrntcList.do (POST, JSON) → 선제 신호
공식 API가 아닌 화면 내부 JSON이므로 사이트 개편 시 깨질 수 있음.
"""
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
PHASES = {"ancmIng": "접수중", "ancmPre": "접수예정", "ancmEnd": "마감"}
ENDED_LOOKBACK_DAYS = 60
MAX_PAGES = 40


def _post_json(s, url, referer, data):
    r = polite_post(s, url, data=data, headers={
        "X-Requested-With": "XMLHttpRequest", "Referer": referer})
    return r.json()


def fetch_notices():
    s = session()
    polite_get(s, LIST_VIEW)  # 세션 쿠키 확보
    cutoff = (today_kst() - timedelta(days=ENDED_LOOKBACK_DAYS)).isoformat()
    out = {}
    for phase, label in PHASES.items():
        page = 1
        while page <= MAX_PAGES:
            d = _post_json(s, LIST_JSON, LIST_VIEW,
                           {"ancmPrg": phase, "pageIndex": page, "pageUnit": 100})
            rows = d.get("listBsnsAncmBtinSitu") or []
            stop = False
            for r in rows:
                posted = norm_date(r.get("ancmDe"))
                if phase == "ancmEnd" and posted and posted < cutoff:
                    stop = True
                    continue
                aid = r.get("ancmId")
                out[f"iris-{aid}"] = item(
                    id=f"iris-{aid}", source="IRIS", kind="notice",
                    title=r.get("ancmTl"), url=DETAIL.format(aid),
                    ministry=r.get("blngGovdSeNm") or r.get("blngGovdSe"),
                    agency=r.get("sorgnNm"), notice_no=r.get("ancmNo"),
                    status=r.get("rcveSttSeNmLst") or label, posted=posted,
                    open_date=norm_date(r.get("rcveStrDe")),
                    close_date=norm_date(r.get("rcveEndDe")),
                    extra={"phase": label,
                           "type": r.get("pbofrTpSeNmLst") or ""})
            info = d.get("paginationInfo") or {}
            if stop or not rows or page >= int(info.get("totalPageCount") or 1):
                break
            page += 1
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
