"""공고 중복 제거.

출처 우선순위: NTIS(RFP 단위) > IRIS(공고번호·상세) > KHIDI(htdream) > KHIDI 대표사이트 > 복지부 > 기타
1) 같은 출처 안: 같은 공고번호+핵심제목, 또는 같은 전체 제목+접수기간 → 하나로
2) 출처 간: 핵심 제목(연도·괄호 제외)이 같거나 한쪽이 다른 쪽을 포함하고 접수기간이 겹치면
   낮은 우선순위 항목을 높은 쪽(여러 개면 모두)에 병합. 예) IRIS 공고 1건 → NTIS RFP 5건에 병합
병합 시 높은 쪽을 남기고, 빈 필드(공고번호 등)·기관·부처·원문 링크를 보완.
"""
import re

FILL = ["notice_no", "type", "posted", "open_date", "close_date", "ministry",
        "agency"]
PRI = {"NTIS": 0, "IRIS": 1, "KHIDI": 2, "KHIDIWEB": 3, "MOHW": 4}


def core(title):
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]|「|」|『|』", "", title or "")
    t = re.sub(r"(공고\s*)?안내$", "", t.strip())
    return re.sub(r"[\s·,.\-_~]", "", t).lower()


def core_noyear(title):
    return re.sub(r"^\d{4}년도?", "", core(title))


def full(title):
    return re.sub(r"[\s·,.\-_~&()\[\]]", "", title or "").lower()


def no_key(no):
    no = re.sub(r"\s", "", no or "")
    return no if re.search(r"제\d{4}-?\d+호", no) else ""


def _overlap(a, b):
    a1, a2 = a.get("open_date"), a.get("close_date")
    b1, b2 = b.get("open_date"), b.get("close_date")
    if not (a1 and a2 and b1 and b2):
        return True
    return a1 <= b2 and b1 <= a2


def _pri(it):
    return PRI.get(it["source"], 9)


def _rank(it):
    # 출처 우선 → 최신 게시(연장·수정 공고) → 늦은 마감 → 채워진 필드 수
    return (-_pri(it), it.get("posted") or "", it.get("close_date") or "",
            len([k for k in FILL if it.get(k)]))


def _merge(keep, drop):
    ex = keep["extra"]
    ex.setdefault("also_listed", [])
    if drop["source"] not in ex["also_listed"] and drop["source"] != keep["source"]:
        ex["also_listed"].append(drop["source"])
    ex.setdefault("links", {})
    ex["links"].setdefault(drop["source"], drop.get("url"))
    for k, field in (("co_agencies", "agency"), ("co_ministries", "ministry")):
        v = drop.get(field)
        if v and v != keep.get(field):
            ex.setdefault(k, [])
            if v not in ex[k]:
                ex[k].append(v)
    for k in FILL:
        if not keep.get(k) and drop.get(k):
            keep[k] = drop[k]
    ex.setdefault("merged_ids", [])
    if drop["id"] not in ex["merged_ids"]:
        ex["merged_ids"].append(drop["id"])


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

    # 1) 같은 출처 안 중복
    groups = {}
    for it in alive.values():
        k = no_key(it.get("notice_no"))
        if k:
            groups.setdefault(("no", it["source"], k, core(it["title"])), []).append(it)
        groups.setdefault(("t", it["source"], full(it["title"]),
                           it.get("open_date"), it.get("close_date")), []).append(it)
    for key, g in list(groups.items()):
        absorb(g, "같은 공고번호" if key[0] == "no" else "같은 제목·접수기간")

    # 2) 출처 간 병합 (우선순위 낮은 것부터 높은 쪽으로)
    for o in sorted(alive.values(), key=lambda x: -_pri(x)):
        if o["id"] not in alive or _pri(o) == 0:
            continue
        oc = core_noyear(o["title"])
        if len(oc) < 10:
            continue
        hits = [x for x in alive.values()
                if _pri(x) < _pri(o) and _overlap(o, x)
                and (core_noyear(x["title"]).startswith(oc)
                     or oc.startswith(core_noyear(x["title"])))]
        if not hits:
            continue
        top = min(_pri(h) for h in hits)
        hits = [h for h in hits if _pri(h) == top]
        # 괄호 속 세부 RFP명까지 같은 항목이 있으면 그쪽에만 병합 (공고번호 오배정 방지)
        exact = [h for h in hits if full(h["title"]) == full(o["title"])]
        if exact:
            hits = exact
        for h in hits:
            _merge(h, o)
        alive.pop(o["id"], None)
        log.append({"kept": ",".join(h["id"] for h in hits), "dropped": o["id"],
                    "reason": "출처 간 동일 공고", "title": o["title"][:60]})
    return alive, log
