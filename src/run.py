"""수집 → 분류 → data/*.json 저장. GitHub Actions에서 매일 실행.

- 수집기 하나가 실패해도 나머지는 진행하고, 실패한 소스는 이전 데이터를 유지.
- first_seen으로 신규 항목을 판별하고, 관련도 높은 신규 항목은 notify.md로 출력.
"""
import json
import os
import sys
import traceback
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "collectors")]

from classify import SOURCE_LABEL, classify, notice_no_kind  # noqa: E402
from common import KST, compute_status, missing_fields, today_kst  # noqa: E402
from dedupe import dedupe  # noqa: E402
import iris  # noqa: E402
import khidi  # noqa: E402
import kmdf  # noqa: E402
import boards  # noqa: E402

ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
FILES = {"notice": "notices.json", "notice_other": "notices_other.json",
         "history": "history.json",
         "forecast": "forecasts.json", "signal": "signals.json"}
JOBS = [
    ("IRIS 사업공고", "IRIS", "notice", iris.fetch_notices),
    ("IRIS 과거공고(관심부처)", "IRIS", "history", iris.fetch_history),
    ("IRIS 사업예고", "IRIS", "forecast", iris.fetch_forecasts),
    ("KHIDI 사업공고", "KHIDI", "notice", khidi.fetch_notices),
    ("KHIDI 공지", "KHIDI", "signal", khidi.fetch_signals),
    ("KMDF 공지", "KMDF", "signal", kmdf.fetch_signals),
    # 비R&D 게시판: 공고·신호가 섞여 나오므로 kind는 항목별(mixed)
    ("KHIDI 비R&D 사업공고", "KHIDIWEB", "mixed", boards.fetch_khidi_biz),
    ("NIPA 사업공고", "NIPA", "mixed", boards.fetch_nipa),
    ("보건복지부 공고", "MOHW", "mixed", boards.fetch_mohw),
]
ARCHIVE_DAYS = 30  # 마감 후 이 기간이 지나거나, 기간 없이 60일 지난 게시물은 history로


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def main():
    os.makedirs(DATA, exist_ok=True)
    profile = load(os.path.join(ROOT, "config", "profile.json"), {})
    today = today_kst().isoformat()
    prev = {k: {x["id"]: x for x in load(os.path.join(DATA, f), [])}
            for k, f in FILES.items()}
    first_run = not any(prev.values())

    state_path = os.path.join(DATA, "state.json")
    state = load(state_path, {})
    results = {k: {} for k in FILES}
    fresh = set()  # 이번 실행에서 실제 수집된 id
    status, errors = [], []
    for label, source, kind, fn in JOBS:
        kinds = list(FILES) if kind == "mixed" else [kind]
        ctx = {"prev": {i: x for k in kinds for i, x in prev[k].items()
                        if x["source"] == source},
               "state": state}
        try:
            items = fn(ctx)
            if not items:
                raise RuntimeError("0건 수집 (사이트 구조 변경 가능성)")
            for it in items:
                results[it["kind"]][it["id"]] = it
                fresh.add(it["id"])
            status.append({"job": label, "ok": True, "count": len(items)})
        except iris.Skip as e:  # 계획된 건너뛰기: 이전 데이터 유지
            status.append({"job": label, "ok": True, "count": 0,
                           "skipped": str(e)})
            for x in ctx["prev"].values():
                results[x["kind"]].setdefault(x["id"], x)
        except Exception as e:  # 실패한 소스는 이전 데이터 유지
            errors.append({"job": label, "error": f"{type(e).__name__}: {e}"})
            status.append({"job": label, "ok": False, "count": 0})
            traceback.print_exc()
            for x in ctx["prev"].values():
                results[x["kind"]].setdefault(x["id"], x)

    # 공고: 상태 재계산 → 중복 제거
    for kind in ("notice", "history"):
        for it in results[kind].values():
            it["status"] = compute_status(it["open_date"], it["close_date"],
                                          it["status"])
    results["notice"], dup_log = dedupe(results["notice"])

    # 오래된 게시판 공고는 history로 이동 (IRIS 과거공고와 같은 보관함)
    from datetime import timedelta
    cut = (today_kst() - timedelta(days=ARCHIVE_DAYS)).isoformat()
    cut_nodate = (today_kst() - timedelta(days=60)).isoformat()
    for i, it in list(results["notice"].items()):
        if it["source"] == "IRIS":
            continue
        old = ((it["close_date"] and it["close_date"] < cut)
               or (not it["close_date"] and (it["posted"] or "") < cut_nodate))
        if old:
            it["kind"] = "history"
            if not it["close_date"]:
                it["status"] = "마감(추정)"
            results["history"][i] = results["notice"].pop(i)

    # 출처·공고번호 형식 표시 + 분류
    for kind, items in results.items():
        for it in items.values():
            classify(it, profile)
            srcs = [it["source"]] + it["extra"].get("also_listed", [])
            it["origin"] = " + ".join(srcs)
            it["origin_label"] = " / ".join(SOURCE_LABEL.get(x, x) for x in srcs)
            if kind in ("notice", "history"):
                it["notice_no_kind"] = notice_no_kind(it["notice_no"])

    # 분야 밖 공고는 목록에서 분리(검증용 보관)
    other = {i: x for i, x in results["notice"].items() if not x["relevant"]}
    results["notice"] = {i: x for i, x in results["notice"].items()
                         if x["relevant"]}
    results["notice_other"] = other
    results["forecast"] = {i: x for i, x in results["forecast"].items()
                           if x["relevant"]}
    # 비R&D 게시판 항목은 신호·보관함에서도 분야 밖이면 분리
    for k in ("signal", "history"):
        for i, x in list(results[k].items()):
            if x["extra"].get("terms_only") and not x["relevant"]:
                results["notice_other"][i] = results[k].pop(i)

    # 병합되어 사라진 id도 "이미 본 것"으로 취급 (중복 알림 방지)
    seen_before = {k: set(v) | {m for x in v.values()
                                for m in x.get("extra", {}).get("merged_ids", [])}
                   for k, v in prev.items()}
    new_items = []
    missing = {}
    for kind, items in results.items():
        for it in items.values():
            if kind in ("notice", "history"):
                m = missing_fields(it)
                it["missing"] = m
                for k in m:
                    missing[k] = missing.get(k, 0) + 1
            old = prev[kind].get(it["id"])
            it["first_seen"] = old["first_seen"] if old else today
            if it["id"] in fresh:
                it["last_seen"] = today
            if (it["id"] not in seen_before[kind] and not first_run
                    and kind not in ("history", "notice_other")):
                new_items.append(it)
        ordered = sorted(items.values(),
                         key=lambda x: (x["score"], x.get("posted") or ""),
                         reverse=True)
        save(os.path.join(DATA, FILES[kind]), ordered)

    meta = {
        "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "jobs": status,
        "errors": errors,
        "counts": {k: len(v) for k, v in results.items()},
        "new_today": [x["id"] for x in new_items],
        "merged_duplicates": dup_log,
        "missing_required": missing,
    }
    save(os.path.join(DATA, "meta.json"), meta)
    save(state_path, state)

    # 알림 본문 (관련도 기준 이상 신규 항목 + 실패 내역)
    min_score = profile.get("notify_min_score", 50)
    hot = sorted([x for x in new_items
                  if x["score"] >= min_score or x.get("topics")],
                 key=lambda x: -x["score"])
    lines = []
    if hot:
        lines.append(f"## 신규 관련 항목 {len(hot)}건\n")
        kind_ko = {"notice": "공고", "forecast": "예고", "signal": "신호",
                   "history": "과거"}
        for x in hot[:30]:
            dl = f" · 마감 {x['close_date']}" if x.get("close_date") else ""
            tp = f" #{' #'.join(x['topics'])}" if x.get("topics") else ""
            lines.append(f"- [{kind_ko[x['kind']]}·{x['origin']}]{tp} **{x['title']}** "
                         f"({x['agency'] or x['ministry']}) · {x['score']}점{dl}  \n"
                         f"  {x['url']}")
    if errors:
        lines.append("\n## 수집 실패\n")
        lines += [f"- {e['job']}: {e['error']}" for e in errors]
    if lines:
        with open(os.path.join(ROOT, "notify.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    print(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
