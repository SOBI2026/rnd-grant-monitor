"""주 1회(월 10:00) 요약 알림 본문 생성 → digest.md

지난 알림 이후 변화만 모아 한 통으로 보냄. GitHub Issue로 올리면 등록 이메일로 전달.
섹션: 마감 임박 / 신규 공고 / 신규 신호 / 관심 주제 / 다가오는 예상 공고 / 수집 상태
수동 실행(workflow_dispatch)도 같은 형식. 마지막 발송일은 data/digest_state.json에 기록.
"""
import json
import os
import re
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import today_kst  # noqa: E402

ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
SITE = "https://sobi2026.github.io/rnd-grant-monitor/"
SRC = {"NTIS": "NTIS", "IRIS": "IRIS", "KHIDI": "KHIDI R&D포털", "KHIDIWEB": "KHIDI",
       "MOHW": "복지부", "NIPA": "NIPA", "KMDF": "KMDF"}


def load(name, default):
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def md(s):
    return str(s or "").replace("|", "／").replace("\n", " ")


def src(x):
    return " + ".join(SRC.get(s, s) for s in (x.get("origin") or x["source"]).split(" + "))


def dday(d, today):
    if not d:
        return ""
    n = (date.fromisoformat(d) - today).days
    return "D-day" if n == 0 else (f"D-{n}" if n > 0 else "")


def period(x):
    a, b = x.get("open_date"), x.get("close_date")
    return f"{(a or '?')[5:]}~{(b or '?')[5:]}"


def links(x):
    """원문 링크: 대표 출처 + 병합된 다른 출처(IRIS 등). htdream 첫 화면 링크는 제외."""
    out = {}
    if x.get("url"):
        out[x["source"]] = x["url"]
    for k, v in (x.get("extra", {}).get("links") or {}).items():
        out.setdefault(k, v)
    out = {k: v for k, v in out.items() if v and v.rstrip("/") != "https://www.htdream.kr"}
    return " · ".join(f"[{SRC.get(k, k)}]({v})" for k, v in out.items()) or "—"


def short(x, n=60):
    t = md(x["title"])
    return t if len(t) <= n else t[:n - 1] + "…"


def link(x, n=48):
    t = md(x["title"])
    t = t if len(t) <= n else t[:n - 1] + "…"
    return f"[{t}]({x['url']})" if x.get("url") else t


def build(today, since):
    notices = load("notices.json", [])
    signals = load("signals.json", [])
    preds = load("predictions.json", {}).get("upcoming", [])
    meta = load("meta.json", {})
    out = [f"> {since.isoformat()} 이후 변화 · 전체 화면: {SITE}", ""]

    # 1) 마감 임박: 접수중 + 7일 이내 마감
    soon = sorted((x for x in notices if x["status"] == "접수중" and x.get("close_date")
                   and 0 <= (date.fromisoformat(x["close_date"]) - today).days <= 7),
                  key=lambda x: x["close_date"])
    out.append(f"## ⏰ 마감 임박 (7일 이내) {len(soon)}건")
    if soon:
        out += ["| D-day | 공고 | 부처 · 기관 | 접수기간 | 원문 |", "|---|---|---|---|---|"]
        out += [f"| **{dday(x['close_date'], today)}** | {short(x)} | {md(x['ministry'])} · {md(x['agency'])} | {period(x)} | {links(x)} |"
                for x in soon]
    else:
        out.append("없음")

    # 2) 신규 공고 (마감 제외). 같은 공고의 RFP 여러 건은 한 줄로 묶음
    raw = [x for x in notices if (x.get("first_seen") or "") > since.isoformat()
           and x["status"] != "마감"]
    groups = {}
    for x in raw:
        base = x["title"].split("_(")[0].split("_")[0].strip()
        groups.setdefault((base, x["ministry"]), []).append(x)
    new = []
    for (base, _), xs in groups.items():
        xs.sort(key=lambda x: x.get("close_date") or "9")
        head = dict(xs[0])
        if len(xs) > 1:
            rfps = [re.sub(r"^\d{4}\)\(", "", x["title"].rsplit("_(", 1)[1]).rstrip(")")
                    if "_(" in x["title"] else "" for x in xs]
            head["title"] = f"{base} — RFP {len(xs)}건"
            head["rfps"] = rfps
            head["rfp_items"] = xs
            head["domains"] = sorted({d for x in xs for d in (x.get("domains") or [])})
            head["close_date"] = xs[0].get("close_date")
        new.append(head)
    new.sort(key=lambda x: (x["status"] != "접수중", x.get("close_date") or "9"))
    out += ["", f"## 🆕 신규 공고 {len(new)}건"]
    if new:
        out += ["| 상태 | 공고 | 분야 | 부처 · 기관 | 접수기간 | 원문 |", "|---|---|---|---|---|---|"]
        out += [f"| {md(x['status']).replace('게시중(기간 확인 필요)', '기간확인')} | {short(x, 70)} | "
                f"{', '.join(x.get('domains') or [])} | {md(x['ministry'])} · {md(x['agency'])} | "
                f"{period(x)} {dday(x.get('close_date'), today)} | {links(x)} |"
                + ("".join(f"\n|  | └ {md(r)[:70]} |  |  |  | {links(rx)} |"
                           for r, rx in list(zip(x.get("rfps", []), x.get("rfp_items", [])))[:8]))
                for x in new[:25]]
        if len(new) > 25:
            out.append(f"외 {len(new) - 25}건은 화면에서 확인")
    else:
        out.append("없음")

    # 3) 신규 신호 (수요조사·설명회·사전공고 등)
    sig = sorted((x for x in signals if (x.get("first_seen") or "") > since.isoformat()
                  and x.get("signal_type", x.get("type")) != "일반공지"
                  and not x["title"].lstrip().startswith(("[교육]", "[행사]"))),
                 key=lambda x: x.get("posted") or "", reverse=True)
    out += ["", f"## 📡 신규 신호 (수요조사 · 설명회 등) {len(sig)}건"]
    if sig:
        out += ["| 게시일 | 구분 | 제목 | 기관 | 원문 |", "|---|---|---|---|---|"]
        out += [f"| {(x.get('posted') or '')[5:]} | {md(x.get('signal_type') or x.get('type') or '공지')} | "
                f"{short(x, 60)} | {md(x.get('agency') or x['ministry'])} | {links(x)} |" for x in sig[:15]]
    else:
        out.append("없음")

    # 4) 관심 주제 (혁신형 제약·의료기기, 디지털헬스): 신규만
    topic = [x for x in new + sig if x.get("topics")]
    if topic:
        out += ["", "## ⭐ 관심 주제"]
        out += [f"- #{' #'.join(x['topics'])} {short(x, 60)} — {links(x)}" for x in topic]

    # 5) 다가오는 예상 공고: 오늘~45일
    up = [p for p in preds
          if 0 <= (date.fromisoformat(p["start"]) - today).days <= 45]
    out += ["", f"## 🔮 다가오는 예상 공고 (45일 이내) {len(up)}건",
            "작년 같은 시기 공고 기준 추정. 신뢰도 상 = 연 2회 이상 반복 + IRIS 사업예고 등재"]
    if up:
        out += ["| 예상 시기 | 사업 | 부처 | 신뢰도 | 작년 공고 |", "|---|---|---|---|---|"]
        out += [f"| {p['start'][5:]}~{p['end'][5:]} | {md(p['name'])} | {md(p['ministry'])} | {p['confidence']} | "
                f"{' · '.join(f'[{SRC.get(r["source"].split(" + ")[0], "원문")}]({r["url"]})' for r in p.get('last_refs', [])[:2]) or '—'} |"
                for p in up[:20]]
    else:
        out.append("없음")

    # 6) 수집 상태
    bad = [j["job"] for j in meta.get("jobs", []) if not j.get("ok")]
    out += ["", "## 수집 상태",
            f"마지막 수집 {md(meta.get('updated_at', '')[:16]).replace('T', ' ')} · "
            + ("모든 출처 정상" if not bad else "실패: " + ", ".join(bad) + " (이전 데이터로 표시 중)")]
    return "\n".join(out) + "\n", len(soon) + len(new) + len(sig)


def main():
    today = today_kst()
    st = load("digest_state.json", {})
    since = date.fromisoformat(st["last_sent"]) if st.get("last_sent") else today - timedelta(days=7)
    body, n = build(today, since)
    wd = "월화수목금토일"[today.weekday()]
    title = f"과제 레이더 {today.strftime('%m/%d')}({wd}) · 마감임박·신규 {n}건"
    with open(os.path.join(ROOT, "digest.md"), "w", encoding="utf-8") as f:
        f.write(body)
    with open(os.path.join(ROOT, "digest_title.txt"), "w", encoding="utf-8") as f:
        f.write(title)
    if "--dry-run" not in sys.argv:
        with open(os.path.join(DATA, "digest_state.json"), "w", encoding="utf-8") as f:
            json.dump({"last_sent": today.isoformat()}, f)
    print(title)
    print(body)


if __name__ == "__main__":
    main()
