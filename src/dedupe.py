"""공고 중복 제거.

1) 같은 공고번호  2) 같은 핵심 제목 + 같은 접수기간
3) 출처가 다른데(IRIS·KHIDI) 핵심 제목이 같고 접수기간이 겹침 → IRIS 항목에 병합
병합 시 IRIS 항목을 남기고, 다른 출처의 기관·부처·빈 필드를 보완.
"""
import re

FILL = ["notice_no", "type", "posted", "open_date", "close_date", "ministry",
        "agency"]


def core(title):
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]|「|」|『|』", "", title or "")
    t = re.sub(r"(공고\s*)?안내$", "", t.strip())
    return re.sub(r"[\s·,.\-_~]", "", t).lower()


def core_noyear(title):
    return re.sub(r"^\d{4}년도?", "", core(title))


def no_key(no):
    no = re.sub(r"\s", "", no or "")
    return no if re.search(r"제\d{4}-?\d+호", no) else ""


def _overlap(a, b):
    a1, a2 = a.get("open_date"), a.get("close_date")
    b1, b2 = b.get("open_date"), b.get("close_date")
    if not (a1 and a2 and b1 and b2):
        return True
    return a1 <= b2 and b1 <= a2


def _rank(it):
    # IRIS 우선 → 최신 게시(연장·수정 공고) → 늦은 마감 → 채워진 필드 수
    return (it["source"] == "IRIS", it.get("posted") or "",
            it.get("close_date") or "", len([k for k in FILL if it.get(k)]))


def _merge(keep, drop):
    ex = keep["extra"]
    ex.setdefault("also_listed", [])
    if drop["source"] not in ex["also_listed"] and drop["source"] != keep["source"]:
        ex["also_listed"].append(drop["source"])
    for k, field in (("co_agencies", "agency"), ("co_ministries", "ministry")):
        v = drop.get(field)
        if v and v != keep.get(field):
            ex.setdefault(k, [])
            if v not in ex[k]:
                ex[k].append(v)
    for k in FILL:
        if not keep.get(k) and drop.get(k):
            keep[k] = drop[k]
    ex.setdefault("merged_ids", []).append(drop["id"])


def dedupe(items):
    """items: {id: item} → ({id: item}, 병합 로그)"""
    alive = dict(items)
    log = []

    def absorb(group, reason):
        group = [x for x in group if x["id"] in alive]
        if len(group) < 2:
            return
        group.sort(key=_rank, reverse=True)
        keep = group[0]
        for d in group[1:]:
            _merge(keep, d)
            alive.pop(d["id"], None)
            log.append({"kept": keep["id"], "dropped": d["id"],
                        "reason": reason, "title": keep["title"][:60]})

    # 1) 공고번호
    by_no = {}
    for it in alive.values():
        k = no_key(it.get("notice_no"))
        if k:
            by_no.setdefault(k + core(it["title"]), []).append(it)
    for g in list(by_no.values()):
        absorb(g, "같은 공고번호")

    # 2) 핵심 제목 + 접수기간
    by_t = {}
    for it in alive.values():
        by_t.setdefault((core(it["title"]), it.get("open_date"),
                         it.get("close_date")), []).append(it)
    for g in list(by_t.values()):
        absorb(g, "같은 제목·접수기간")

    # 3) 출처 간 병합: 핵심 제목(연도 제외)이 같거나 한쪽이 다른 쪽을 포함
    #    우선순위 IRIS > KHIDI(htdream) > KHIDIWEB > MOHW > 기타 쪽으로 흡수
    pri = {"IRIS": 0, "KHIDI": 1, "KHIDIWEB": 2, "MOHW": 3}
    others = sorted([x for x in alive.values() if x["source"] != "IRIS"],
                    key=lambda x: -pri.get(x["source"], 9))
    for o in others:
        if o["id"] not in alive:
            continue
        oc = core_noyear(o["title"])
        if len(oc) < 10:
            continue
        hits = [x for x in alive.values()
                if x["source"] != o["source"]
                and pri.get(x["source"], 9) < pri.get(o["source"], 9)
                and _overlap(o, x)
                and (core_noyear(x["title"]).startswith(oc)
                     or oc.startswith(core_noyear(x["title"])))]
        for h in hits:
            _merge(h, o)
        if hits:
            alive.pop(o["id"], None)
            log.append({"kept": ",".join(h["id"] for h in hits),
                        "dropped": o["id"], "reason": "출처 간 동일 공고",
                        "title": o["title"][:60]})
    return alive, log
