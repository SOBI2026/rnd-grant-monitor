"""비R&D 사업공고 게시판 수집기 (HTML 목록 파싱).

- KHIDI 대표사이트 사업공고: 헬스케어·의료기기·제약 지원사업, 혁신형 제약 포상 등
- NIPA 사업공고: 디지털·AI 지원사업 (헬스 관련만 목록에 남김)
- 보건복지부 공지사항(분류=공고): 혁신형 제약기업 인증 등 부처 공고
게시판 글이라 공고번호·유형·접수기간이 없는 경우가 많음 → 제목에서 마감일 추정.
"""
import re
from html import unescape

from common import (clean, item, norm_date, parse_deadline, polite_get,
                    session)

KHIDI = "https://www.khidi.or.kr"
NIPA = "https://www.nipa.kr"
MOHW = "https://www.mohw.go.kr"


def _txt(h):
    return clean(unescape(re.sub(r"<[^>]+>", " ", h or "")))


def _type_from_title(t):
    for key, label in [("인증", "인증"), ("포상", "포상"), ("수요조사", "수요조사"),
                       ("입주", "입주기업 모집"), ("전시", "전시·행사 참가"),
                       ("박람회", "전시·행사 참가"), ("포럼", "전시·행사 참가"),
                       ("공모", "공모"), ("모집", "참여기업 모집"),
                       ("지원사업", "지원사업")]:
        if key in t:
            return label + " (추정)"
    return "비R&D 사업"


def _no_from_title(t):
    m = re.search(r"\[(\d{4}-\d+호)\]", t)
    return m.group(1) if m else ""


def _board_item(src, sid, title, url, posted, ministry, agency, extra=None,
                open_date=None, close_date=None, type_=None):
    close_date = close_date or parse_deadline(title, posted)
    kind = "signal" if "수요조사" in title else "notice"
    ex = {"category": "비R&D", "terms_only": True, "deadline_from":
          "신청기간" if open_date else ("제목 추정" if close_date else "")}
    ex.update(extra or {})
    return item(id=f"{src.lower()}-{sid}", source=src, kind=kind, title=title,
                url=url, ministry=ministry, agency=agency,
                notice_no=_no_from_title(title),
                type=type_ or _type_from_title(title), status="게시중(기간 확인 필요)",
                posted=posted, open_date=open_date, close_date=close_date,
                extra=ex)


KHIDI_ROW = re.compile(
    r'<td class="num">\s*((?:<span[^>]*>)?[^<]*?(?:</span>)?)\s*</td>\s*<td class="ellipsis">\s*'
    r'<a href="(/board/view\?[^"]*linkId=(\d+)[^"]*)"[^>]*title="([^"]*)".*?'
    r'<td>[^<]*</td>\s*<td>(\d{4}-\d{2}-\d{2})</td>', re.S)


def fetch_khidi_biz(ctx=None, pages=3):
    s = session()
    out = {}
    for p in range(1, pages + 1):
        html = polite_get(s, f"{KHIDI}/board?menuId=MENU01108&pageNum={p}").text
        rows = KHIDI_ROW.findall(html)
        for num, href, lid, title, date in rows:
            it = _board_item("KHIDIWEB", lid, unescape(title),
                             KHIDI + unescape(href).split("&maxIndex")[0],
                             norm_date(date), "보건복지부", "한국보건산업진흥원",
                             {"pinned": "공지" in num})
            out[it["id"]] = it
        if not rows:
            break
    return list(out.values())


NIPA_ROW = re.compile(
    r'<a href="(/home/2-2/(\d+))">(.*?)</a>.*?'
    r'<span class="box bluebox">([^<]*)</span>\s*<span class="bco">\s*신청기간\s*:\s*'
    r'([\d-]+)[^~]*~\s*([\d-]+).*?<span class="bco">([^<]*)</span>\s*</td>\s*<td>\s*'
    r'<span class="bco">(\d{4}-\d{2}-\d{2})</span>', re.S)


def fetch_nipa(ctx=None, pages=3):
    s = session()
    out = {}
    for p in range(1, pages + 1):
        html = polite_get(s, f"{NIPA}/home/2-2?curPage={p}").text
        rows = NIPA_ROW.findall(html)
        for href, nid, title, biz, start, end, _writer, date in rows:
            title = _txt(re.sub(r"<!--.*?-->", "", title, flags=re.S))
            it = _board_item("NIPA", nid, title, NIPA + href, norm_date(date),
                             "과학기술정보통신부", "정보통신산업진흥원",
                             {"business": clean(biz)},
                             open_date=norm_date(start), close_date=norm_date(end),
                             type_="비R&D 사업")
            out[it["id"]] = it
        if not rows:
            break
    return list(out.values())


MOHW_ROW = re.compile(
    r'data-label="분류">([^<]*)</td>\s*<td[^>]*data-label="제목">\s*'
    r'<a href="([^"]*list_no=(\d+)[^"]*)"[^>]*>(.*?)</a>.*?'
    r'data-label="등록일">(\d{4}-\d{2}-\d{2})<', re.S)
MOHW_LIST = MOHW + "/board.es?mid=a10501010100&bid=0003&act=list"


def fetch_mohw(ctx=None, pages=8):
    """복지부 공지사항 중 '공고'만. 최근 몇 페이지 + '혁신형' 검색 결과(인증 이력)."""
    s = session()
    out = {}
    urls = [f"{MOHW_LIST}&nPage={p}" for p in range(1, pages + 1)]
    urls.append(f"{MOHW_LIST}&keyField=TITLE&keyWord=%ED%98%81%EC%8B%A0%ED%98%95")
    for url in urls:
        html = polite_get(s, url, delay=1.5).text
        for cat, href, lid, title, date in MOHW_ROW.findall(html):
            if clean(cat) != "공고":
                continue
            title = re.sub(r"^\s*새글\s*", "", _txt(title))
            it = _board_item("MOHW", lid, title,
                             MOHW + unescape(href).split("&tag")[0],
                             norm_date(date), "보건복지부", "보건복지부",
                             {"strict": True})
            out[it["id"]] = it
    return list(out.values())
