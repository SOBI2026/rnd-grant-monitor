"""KHIDI 보건의료R&D포털(htdream) 수집기.

- 진행중 사업공고: 메인 페이지 HTML (IRIS에 없는 KHIDI 자체 공고 보완)
- 공지(기술수요조사, 설명회, 선정공고): 내부 JSON → 선제 신호
"""
import re

from common import clean, item, norm_date, polite_get, polite_post, session

BASE = "https://www.htdream.kr"
BBS_JSON = BASE + "/mypage/selectComtnbbsListAjax.do"
BOARD_URL = BASE + "/"
PBAN = re.compile(
    r'class="state">([^<]+)<.*?마감일\s*([\d-]+).*?'
    r"fn_selectBsnsPbanView\('(\d+)'[^>]*>(.*?)</a>.*?"
    r"공고번호</span>([^<]*)<.*?공고기간</span>\s*([\d-]+)~([\d-]+)",
    re.S)


def _infer_type(title):
    """KHIDI 화면에는 공고유형이 없어 제목으로 추정."""
    for key, label in [("사업단장", "사업단장 공모"), ("지정공모", "지정공모"),
                       ("품목지정", "품목지정"), ("정책지정", "정책지정"),
                       ("자유공모", "자유공모"), ("신규지원", "신규과제 공모"),
                       ("신규과제", "신규과제 공모")]:
        if key in title:
            return label + " (추정)"
    return ""


def fetch_notices(ctx=None):
    s = session()
    html = polite_get(s, BASE + "/").text
    out = {}
    for state, _close, pid, title, no, start, end in PBAN.findall(html):
        title = re.sub(r"<[^>]+>", "", title)
        no = clean(no)
        ministry = "보건복지부"
        if "공고" not in no:  # 공고번호 칸에 부처명만 적힌 경우
            ministry, no = (no or ministry), ""
        out[f"khidi-pban-{pid}"] = item(
            id=f"khidi-pban-{pid}", source="KHIDI", kind="notice",
            title=title, url=BOARD_URL,
            ministry=ministry, agency="한국보건산업진흥원",
            notice_no=no, type=_infer_type(title), status=clean(state),
            posted=norm_date(start), open_date=norm_date(start),
            close_date=norm_date(end),
            extra={"phase": "접수중" if "진행" in state else clean(state),
                   "pbanId": pid})
    return list(out.values())


def fetch_signals(ctx=None, pages=3):
    s = session()
    polite_get(s, BASE + "/")
    out = {}
    for page in range(1, pages + 1):
        r = polite_post(s, BBS_JSON, data={"pageIndex": page},
                        headers={"X-Requested-With": "XMLHttpRequest",
                                 "Referer": BASE + "/"})
        rows = (r.json() or {}).get("resultList") or []
        for x in rows:
            no = x.get("invvNoticeSeqno")
            out[f"khidi-{no}"] = item(
                id=f"khidi-{no}", source="KHIDI", kind="signal",
                title=x.get("invvNoticeTtl"), url=BOARD_URL,
                ministry="보건복지부", agency="한국보건산업진흥원",
                status=x.get("ctgrDsncNm") or "",
                posted=norm_date(x.get("rgstDt")),
                extra={"seq": no})
        if not rows:
            break
    return list(out.values())
