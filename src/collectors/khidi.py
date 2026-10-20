"""KHIDI 보건의료R&D포털(htdream) 공지 수집기 → 선제 신호.

기술수요조사, 사업설명회, 선정공고 등이 올라옴. 사업공고 자체는 IRIS로 수집.
"""
from common import item, norm_date, polite_get, polite_post, session

BASE = "https://www.htdream.kr"
BBS_JSON = BASE + "/mypage/selectComtnbbsListAjax.do"
BOARD_URL = BASE + "/"


def fetch_signals(pages=3):
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
