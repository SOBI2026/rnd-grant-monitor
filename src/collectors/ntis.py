"""NTIS 국가R&D 통합공고 수집기 (공개 페이지, 인증키 불필요).

IRIS와 달리 공고를 RFP(세부과제) 단위로 나눠 싣고, 수요조사·사전공고도 포함.
- 목록: /rndgate/eg/un/ra/mng.do?searchStatusList=P,B (접수예정·접수중)
- 상세: /rndgate/eg/un/ra/view.do?roRndUid=… (부처, 공고기관, 공고일, 공고유형, 사업명, 금액)
상세는 처음 본 공고만 조회하고 이후에는 이전 값을 재사용.
"""
import re
from html import unescape

from common import clean, item, norm_date, polite_get, session

BASE = "https://www.ntis.go.kr"
LIST = BASE + "/rndgate/eg/un/ra/mng.do?searchStatusList=P,B&pageUnit=100&pageIndex={}"
VIEW = BASE + "/rndgate/eg/un/ra/view.do?roRndUid={}"
DELAY = 1.5
NO_RE = re.compile(r"[가-힣A-Za-z·\s]{2,40}?공고\s*제\s*\d{4}\s*[-－]\s*\d+\s*호")


def _txt(h):
    return clean(unescape(re.sub(r"<[^>]+>", " ", h or "")))


def _field(html, label):
    m = re.search(r"<span>\s*" + label + r"\s*:\s*</span>(.*?)</li>", html, re.S)
    return _txt(m.group(1)) if m else ""


def _rows(html):
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        m = re.search(r"fn_view\('(\d+)'", tr)
        if not m:
            continue
        tds = [_txt(td) for td in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        t = re.search(r'title="([^"]*)"', tr[tr.find("fn_view"):])
        # [체크박스, 순번, 현황, 공고명, 부처명, 접수일, 마감일, D-day]
        out.append({"uid": m.group(1), "status": tds[2] if len(tds) > 2 else "",
                    "title": unescape(t.group(1)) if t else (tds[3] if len(tds) > 3 else ""),
                    "ministry": tds[4] if len(tds) > 4 else "",
                    "open": norm_date(tds[5]) if len(tds) > 5 else None,
                    "close": norm_date(tds[6]) if len(tds) > 6 else None})
    return out


def _detail(s, uid):
    html = polite_get(s, VIEW.format(uid), delay=DELAY).text
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
    no = NO_RE.search(_txt(body))
    return {
        "ministry": _field(body, "부처명"),
        "agency": _field(body, "공고기관명"),
        "posted": norm_date(_field(body, "공고일")),
        "type": _field(body, "공고유형"),          # 본공고 / 사전공고 / 수요조사
        "form": _field(body, "공고형태"),          # 통합공고 / 개별공고
        "business": _field(body, "사업명"),
        "amount": _field(body, "공고금액"),
        "notice_no": clean(no.group(0)) if no else "",
    }


def fetch_notices(ctx=None, pages=5):
    prev = (ctx or {}).get("prev", {})
    s = session()
    rows = []
    for p in range(1, pages + 1):
        got = _rows(polite_get(s, LIST.format(p), delay=DELAY).text)
        rows += got
        if len(got) < 100:
            break
    out = []
    for r in rows:
        iid = f"ntis-{r['uid']}"
        old = prev.get(iid)
        if old and old["extra"].get("detail_ok"):
            d = {k: old["extra"].get("d_" + k, "") for k in
                 ("ministry", "agency", "posted", "type", "form", "business",
                  "amount", "notice_no")}
        else:
            try:
                d = _detail(s, r["uid"])
                d_ok = True
            except Exception:
                d, d_ok = {}, False
            else:
                d_ok = bool(d.get("agency") or d.get("posted"))
            d = {**d, "_ok": d_ok}
        ok = d.pop("_ok", True)
        kind = "signal" if "수요조사" in (d.get("type") or r["title"]) else "notice"
        out.append(item(
            id=iid, source="NTIS", kind=kind, title=r["title"],
            url=VIEW.format(r["uid"]),
            ministry=d.get("ministry") or r["ministry"],
            agency=d.get("agency", ""), notice_no=d.get("notice_no", ""),
            type=d.get("type", ""), status=r["status"],
            posted=d.get("posted") or None,
            open_date=r["open"], close_date=r["close"],
            extra={"business": d.get("business", ""), "amount": d.get("amount", ""),
                   "form": d.get("form", ""), "detail_ok": ok,
                   **{"d_" + k: v for k, v in d.items()}}))
    return out


# ── 과거 공고(마감) ─────────────────────────────────────────────────────
# 목록만 사용(상세 조회 없음): 공고명·부처·접수일·마감일. 분야 키워드로 검색해
# 13개월치를 모으고, 이후에는 이미 아는 공고가 나오면 멈춤(증분).
HIST_LIST = (BASE + "/rndgate/eg/un/ra/mng.do?searchStatusList=Y&pageUnit=100"
             "&searchKeyword={}&pageIndex={}")
HIST_KEYWORDS = ["바이오", "신약", "의약", "제약", "백신", "세포", "유전자", "항체",
                 "재생", "의료", "보건", "헬스", "임상", "질환", "진단", "치료",
                 "감염", "암", "한의약", "의사과학자"]
HIST_DAYS = 400
HIST_PAGE_CAP = 6


def fetch_history(ctx=None):
    from datetime import timedelta
    from urllib.parse import quote

    from common import today_kst
    prev = (ctx or {}).get("prev", {})
    cutoff = (today_kst() - timedelta(days=HIST_DAYS)).isoformat()
    s = session()
    out = {i: x for i, x in prev.items() if (x.get("open_date") or "") >= cutoff}
    for kw in HIST_KEYWORDS:
        for p in range(1, HIST_PAGE_CAP + 1):
            rows = _rows(polite_get(s, HIST_LIST.format(quote(kw), p),
                                    delay=DELAY).text)
            old = known = 0
            for r in rows:
                iid = f"ntis-{r['uid']}"
                if not r["open"] or r["open"] < cutoff:
                    old += 1
                    continue
                if iid in prev:
                    known += 1
                kind = "history"
                out[iid] = item(
                    id=iid, source="NTIS", kind=kind, title=r["title"],
                    url=VIEW.format(r["uid"]), ministry=r["ministry"],
                    type="수요조사" if "수요조사" in r["title"] else "",
                    status="마감", posted=r["open"], open_date=r["open"],
                    close_date=r["close"],
                    extra={"posted_from": "접수일", "search_kw": kw})
            if len(rows) < 100 or old == len(rows) or known == len(rows):
                break
    return list(out.values())
