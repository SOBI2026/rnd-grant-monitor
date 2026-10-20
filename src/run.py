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

from classify import classify  # noqa: E402
from common import KST, today_kst  # noqa: E402
import iris  # noqa: E402
import khidi  # noqa: E402
import kmdf  # noqa: E402

ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
FILES = {"notice": "notices.json", "forecast": "forecasts.json",
         "signal": "signals.json"}
JOBS = [
    ("IRIS 사업공고", "IRIS", "notice", iris.fetch_notices),
    ("IRIS 사업예고", "IRIS", "forecast", iris.fetch_forecasts),
    ("KHIDI 사업공고", "KHIDI", "notice", khidi.fetch_notices),
    ("KHIDI 공지", "KHIDI", "signal", khidi.fetch_signals),
    ("KMDF 공지", "KMDF", "signal", kmdf.fetch_signals),
]


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

    results = {k: {} for k in FILES}
    fresh = set()  # 이번 실행에서 실제 수집된 id
    status, errors = [], []
    for label, source, kind, fn in JOBS:
        try:
            items = fn()
            if not items:
                raise RuntimeError("0건 수집 (사이트 구조 변경 가능성)")
            for it in items:
                results[kind][it["id"]] = it
                fresh.add(it["id"])
            status.append({"job": label, "ok": True, "count": len(items)})
        except Exception as e:  # 실패한 소스는 이전 데이터 유지
            errors.append({"job": label, "error": f"{type(e).__name__}: {e}"})
            status.append({"job": label, "ok": False, "count": 0})
            traceback.print_exc()
            for x in prev[kind].values():
                if x["source"] == source:
                    results[kind].setdefault(x["id"], x)

    new_items = []
    for kind, items in results.items():
        for it in items.values():
            old = prev[kind].get(it["id"])
            it["first_seen"] = old["first_seen"] if old else today
            if it["id"] in fresh:
                it["last_seen"] = today
            classify(it, profile)
            if not old and not first_run:
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
    }
    save(os.path.join(DATA, "meta.json"), meta)

    # 알림 본문 (관련도 기준 이상 신규 항목 + 실패 내역)
    min_score = profile.get("notify_min_score", 50)
    hot = sorted([x for x in new_items if x["score"] >= min_score],
                 key=lambda x: -x["score"])
    lines = []
    if hot:
        lines.append(f"## 신규 관련 항목 {len(hot)}건\n")
        kind_ko = {"notice": "공고", "forecast": "예고", "signal": "신호"}
        for x in hot[:30]:
            dl = f" · 마감 {x['close_date']}" if x.get("close_date") else ""
            lines.append(f"- [{kind_ko[x['kind']]}] **{x['title']}** "
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
