"""KMDF(범부처의료기기연구개발사업단) 공지 수집기 → 선제 신호. HTML 목록 파싱."""
import re

from common import clean, item, norm_date, polite_get, session

BASE = "https://www.kmdf.org"
ROW = re.compile(
    r'href="/notice/view/id/(\d+)"[^>]*>(.*?)</a>.*?aria-title="등록일">([^<]+)<',
    re.S)


def fetch_signals(pages=2):
    s = session()
    out = {}
    for page in range(1, pages + 1):
        url = BASE + "/notice" + (f"/page/{page}" if page > 1 else "")
        try:
            html = polite_get(s, url).text
        except Exception:
            if page == 1:
                raise
            break
        rows = ROW.findall(html)
        for nid, title, date in rows:
            out[f"kmdf-{nid}"] = item(
                id=f"kmdf-{nid}", source="KMDF", kind="signal",
                title=clean(re.sub(r"<[^>]+>", " ", title)),
                url=f"{BASE}/notice/view/id/{nid}",
                ministry="범부처", agency="범부처의료기기연구개발사업단",
                posted=norm_date(date))
        if not rows:
            break
    return list(out.values())
