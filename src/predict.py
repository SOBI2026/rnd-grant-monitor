"""과거 공고 → 사업(시리즈) 단위 묶기 → 다음 공고 시점 예측.

방법(단순·설명 가능한 규칙):
1) 제목 정규화: 연도·차수·재공고/연장/수정·RFP 괄호·'공고/공모/안내' 등을 지워 사업명 키를 만듦
   예) '2026년도 바이오·의료기술개발 사업 신규과제 제4차 공모' → '바이오의료기술개발사업'
2) 같은 부처 + 같은 키 = 하나의 사업. 접수 시작일이 21일 이내로 붙은 공고는 같은 회차로 묶음
   (RFP 분할, 재공고, 연장공고 등)
3) 예측: 각 회차를 1년 뒤로 옮김(작년 동기 반복 가정). 오늘 이후 12개월 안의 것만 표시
   - 같은 사업이 13개월 안에 2회 이상이면 '연 n회 반복'으로 신뢰도 상향
   - IRIS 사업예고에 같은 사업이 있으면 근거에 추가
결과: data/predictions.json (간트차트 화면에서 사용)
"""
import re
from datetime import date, timedelta

ROUND_GAP_DAYS = 21
DROP_WORDS = [
    "통합 재공고", "통합재공고", "통합",
    "신규지원 대상과제", "신규지원대상과제", "신규지원 대상", "신규과제", "신규사업",
    "연구개발과제", "대상과제", "통합공고", "통합 공고", "개별공고", "재공고", "재공모",
    "추가공고", "추가 공고", "연장공고", "연장 공고", "수정공고", "수정 공고", "정정공고",
    "변경공고", "시행계획", "공고문", "공고", "공모", "안내", "모집", "접수", "신규",
    "본공고", "사전공고", "지원계획", "수정", "연장", "정정",
]


def series_key(title):
    t = title or ""
    t = re.sub(r"_.*$", " ", t)  # NTIS RFP 접미사('_(RFP명)', '_1. 일반형' 등) 제거 → 사업 단위
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]|「|」|『|』|<[^>]*>", " ", t)
    t = re.sub(r"\d{4}\s*년도?|\(\s*\d{4}\s*\)|'\d{2}년?", " ", t)
    t = re.sub(r"제?\s*\d+\s*차(\s*\d+\s*차)?", " ", t)
    t = re.sub(r"\s+", "", t)
    for w in sorted({w.replace(" ", "") for w in DROP_WORDS}, key=len, reverse=True):
        t = t.replace(w, "")
    t = re.sub(r"[^가-힣A-Za-z0-9]", "", t)
    return t


def _d(s):
    return date.fromisoformat(s) if s else None


def _shift_year(d, n=1):
    try:
        return d.replace(year=d.year + n)
    except ValueError:  # 2월 29일
        return d.replace(year=d.year + n, day=28)


def build(history, notices, forecasts, today, domains_of):
    """history/notices: 공고 리스트, forecasts: IRIS 사업예고, domains_of: item→분야 리스트"""
    pool = {}
    for it in list(history) + list(notices):
        if not it.get("open_date") or it.get("kind") == "signal":
            continue
        if it.get("type") == "수요조사" or "수요조사" in it["title"]:
            continue
        key = series_key(it["title"])
        if len(key) < 4:
            continue
        pool.setdefault(key, []).append(it)

    fc_keys = {}
    for f in forecasts:
        k = series_key(f["title"])
        if len(k) >= 4:
            fc_keys.setdefault(k, []).append(f)

    series = []
    horizon = today + timedelta(days=365)
    for key, items in pool.items():
        items.sort(key=lambda x: x["open_date"])
        mins = sorted({m.strip() for it in items
                       for m in (it.get("ministry") or "기타").split(",")})
        ministry = mins[0] if len(mins) == 1 else "다부처(" + "·".join(mins) + ")"
        rounds = []
        for it in items:
            od = _d(it["open_date"])
            if rounds and (od - rounds[-1]["start"]).days <= ROUND_GAP_DAYS:
                r = rounds[-1]
                r["items"].append(it)
                cd = _d(it.get("close_date"))
                if cd and (not r["end"] or cd > r["end"]):
                    r["end"] = cd
            else:
                rounds.append({"start": od, "end": _d(it.get("close_date")),
                               "items": [it]})
        doms = sorted({d for it in items for d in domains_of(it)})
        agencies = sorted({it.get("agency") for it in items if it.get("agency")})
        n = len(rounds)
        fc = [f for k, fs in fc_keys.items() if k in key or key in k for f in fs]
        preds = []
        for r in rounds:
            ps = _shift_year(r["start"])
            pe = _shift_year(r["end"]) if r["end"] else ps + timedelta(days=30)
            # 이미 올해 같은 시기에 공고가 났으면(=현재 회차) 예측에서 제외
            if ps <= today or ps > horizon:
                continue
            if any(abs((x["start"] - ps).days) <= 45 for x in rounds):
                continue
            basis = [f"{r['start'].year}년 {r['start'].month}월 공고 반복"]
            conf = "중" if n >= 2 else "하"
            if fc:
                basis.append("IRIS 사업예고 등재")
                conf = "상" if n >= 2 else "중"
            preds.append({"start": ps.isoformat(), "end": pe.isoformat(),
                          "confidence": conf, "basis": basis})
        series.append({
            "key": key,
            "name": _display_name(items),
            "ministry": ministry,
            "agencies": agencies,
            "domains": doms,
            "rounds_per_year": n,
            "rounds": [{
                "start": r["start"].isoformat(),
                "end": r["end"].isoformat() if r["end"] else None,
                "items": [{"id": x["id"], "title": x["title"], "url": x.get("url"),
                           "open_date": x.get("open_date"),
                           "close_date": x.get("close_date"),
                           "notice_no": x.get("notice_no", ""),
                           "source": x.get("origin") or x.get("source")}
                          for x in r["items"]],
            } for r in rounds],
            "predictions": preds,
            "forecast_refs": [{"title": f["title"], "year": f["extra"].get("year"),
                               "expected": f["extra"].get("expected")} for f in fc[:3]],
        })
    series.sort(key=lambda s: (s["ministry"], min(r["start"] for r in s["rounds"])))
    upcoming = sorted(
        ({"name": s["name"], "ministry": s["ministry"], "domains": s["domains"],
          "agencies": s["agencies"], **p} for s in series for p in s["predictions"]),
        key=lambda x: x["start"])
    return {"generated": today.isoformat(), "series": series, "upcoming": upcoming,
            "method": "작년 동기 반복 가정 + IRIS 사업예고 대조. 신뢰도: 상(연 2회 이상·예고 등재), "
                      "중(연 2회 이상 또는 예고 등재), 하(13개월 내 1회)."}


def _display_name(items):
    """사람이 읽을 사업명: 가장 짧은 원제목에서 연도·차수만 정리."""
    t = min((re.sub(r"_.*$", "", x["title"]) for x in items), key=len)
    t = re.sub(r"^\s*\(?[^)]*공고\)\s*", "", t) if t.startswith("(") else t
    t = re.sub(r"\d{4}\s*년도?\s*", "", t)
    t = re.sub(r"제?\s*\d+\s*차\s*", "", t)
    return re.sub(r"\s+", " ", t).strip()
