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
# IRIS는 페이지당 10건 고정, 공고일 내림차순. 짧은 시간 요청이 몰리면 접속 차단.
IRIS_DELAY = 2.5          # IRIS 요청 간격(초)
RECENT_END_DAYS = 30      # 공고 목록에 남길 최근 마감 공고
HISTORY_DAYS = 400        # 예측용 과거 공고 (관심 부처만)
PRE_LOOKBACK_DAYS = 120   # 접수예정은 오래된 미정리 글이 많아 최근 게시분만
PAGE_CAP = 15             # 한 목록당 하루 최대 페이지
BACKFILL_PAGES = 10       # 과거 공고 백필: 조회당 하루 추가 페이지
ALL_BACKFILL_PAGES = 40   # 전 부처 조회 백필: 하루 추가 페이지(약 400건)
FORECAST_WEEKDAY = 0      # 사업예고 전체 갱신 요일(월)
# 관심 부처 코드 (IRIS 검색조건 blngGovdSe)
FOCUS_GOVD = {"AR4012": "보건복지부", "AR4014": "식품의약품안전처",
              "AR4933": "질병관리청", "AR4999": "범부처"}
# 과거 공고 추가 조회: 관심 전문기관 + 공고명 키워드(부처 무관)
FOCUS_SORGN = {"10023": "국가신약개발재단", "10021": "범부처의료기기연구개발사업단",
               "10022": "범부처재생의료기술개발사업단", "10032": "국립암센터"}
HISTORY_KEYWORDS = ["바이오", "신약", "의약품", "백신", "세포", "유전자", "항체",
                    "재생의료", "의료기기", "헬스케어", "디지털헬스", "임상"]
# 연구자 대상 행정 접수·테스트 글 제외
NOISE = re.compile(r"연차실적|실적계획서|단계평가|보고서\s*접수|협약변경|^\s*test\s*$|테스트",
                   re.I)


class Skip(Exception):
    """이번 실행에서는 수집하지 않음(이전 데이터 유지)."""


def _noise(title):
    t = title or ""
    return bool(NOISE.search(t)) or len(re.findall(r"[가-힣]", t)) < 5


def _post_json(s, url, referer, data):
    r = polite_post(s, url, delay=IRIS_DELAY, data=data, headers={
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


def _page(s, params, page):
    d = _post_json(s, LIST_JSON, LIST_VIEW, {**params, "pageIndex": page})
    rows = d.get("listBsnsAncmBtinSitu") or []
    total = int((d.get("paginationInfo") or {}).get("totalPageCount") or 1)
    return rows, total


def _crawl(s, params, kind, cutoff=None, known=None, start=1, cap=PAGE_CAP):
    """start 페이지부터 수집. 다음 중 하나면 중단:
    한 페이지가 전부 cutoff 이전 / 전부 이미 아는 공고(증분) / cap 도달 / 마지막 페이지.
    반환: (항목 dict, 마지막으로 읽은 페이지, 끝까지 도달 여부)"""
    out, page, last = {}, start, start - 1
    while page < start + cap:
        rows, total = _page(s, params, page)
        last = page
        old = seen = 0
        for r in rows:
            posted = norm_date(r.get("ancmDe"))
            if cutoff and (not posted or posted < cutoff):
                old += 1
                continue
            if known is not None and f"iris-{r.get('ancmId')}" in known:
                seen += 1
            if _noise(r.get("ancmTl")):
                continue
            it = _to_item(r, kind)
            out[it["id"]] = it
        if not rows or page >= total or old == len(rows):
            return out, last, True
        if known is not None and seen == len(rows):
            return out, last, False
        page += 1
    return out, last, False


def _cut(days):
    return (today_kst() - timedelta(days=days)).isoformat()


def fetch_notices(ctx):
    """접수중·접수예정(전 부처) + 최근 30일 마감(전 부처)."""
    s = session()
    polite_get(s, LIST_VIEW)  # 세션 쿠키 확보
    out = {}
    out.update(_crawl(s, {"ancmPrg": "ancmIng"}, "notice")[0])
    out.update(_crawl(s, {"ancmPrg": "ancmPre"}, "notice",
                      cutoff=_cut(PRE_LOOKBACK_DAYS))[0])
    out.update(_crawl(s, {"ancmPrg": "ancmEnd"}, "notice",
                      cutoff=_cut(RECENT_END_DAYS))[0])
    return list(out.values())


def fetch_history(ctx):
    """과거 마감 공고(약 13개월). 반복 사업 시점 예측용.
    관심 부처 + 관심 전문기관 + 공고명 키워드(바이오·신약 등, 부처 무관)로 조회.
    매일: 1페이지부터 이미 아는 공고까지(증분). 백필 미완료면 이어서 몇 페이지 더."""
    s = session()
    polite_get(s, LIST_VIEW)
    prev = ctx["prev"]
    known = set(prev)
    out = dict(prev)  # 과거 공고는 누적 보관
    state = ctx["state"].setdefault("history_backfill", {})
    cutoff = _cut(HISTORY_DAYS)
    queries = ([(c, {"blngGovdSeArr": c}) for c in FOCUS_GOVD]
               + [(f"sorgn:{c}", {"sorgnIdArr": c}) for c in FOCUS_SORGN]
               + [(f"kw:{k}", {"bsnsTl": k}) for k in HISTORY_KEYWORDS]
               # 전 부처 마감 공고: 과기부·산업부 등 바이오 사업을 빠짐없이 잡기 위함.
               # 양이 많아 하루 ALL_BACKFILL_PAGES씩 나눠 채움. 분야 필터는 run.py에서.
               + [("all", {})])
    for code, q in queries:
        params = {"ancmPrg": "ancmEnd", **q}
        st = state.get(code)
        if st and st.get("unsupported"):
            continue
        if st is None and "bsnsTl" in q:
            # 공고명 검색이 실제로 적용되는지 첫 페이지로 확인
            rows, _ = _page(s, params, 1)
            hit = sum(q["bsnsTl"] in (r.get("ancmTl") or "") for r in rows)
            if rows and hit < len(rows) / 2:
                state[code] = {"unsupported": True}
                continue
        if st is not None:  # 백필을 시작한 조회만 증분 수집
            new, _, _ = _crawl(s, params, "history", cutoff=cutoff, known=known)
            out.update(new)
        st = state.setdefault(code, {"next_page": 1, "done": False})
        if not st["done"]:
            got, last, done = _crawl(
                s, params, "history", cutoff=cutoff, start=st["next_page"],
                cap=ALL_BACKFILL_PAGES if code == "all" else BACKFILL_PAGES)
            out.update(got)
            st.update(next_page=last + 1, done=done)
    # 보관 기간 지난 항목 정리
    return [x for x in out.values() if (x.get("posted") or "") >= cutoff]


def fetch_forecasts(ctx):
    """사업예고(약 600건, 60페이지)는 변동이 적어 주 1회 전체 갱신."""
    if ctx["prev"] and today_kst().weekday() != FORECAST_WEEKDAY:
        raise Skip("주 1회(월요일) 갱신")
    s = session()
    polite_get(s, PRNTC_VIEW)
    out = {}
    page = 1
    while page <= 80:
        d = _post_json(s, PRNTC_JSON, PRNTC_VIEW, {"pageIndex": page})
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
