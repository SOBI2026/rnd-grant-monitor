"""분야 태깅 + 적합도 점수(키워드 규칙 기반). 근거 키워드를 함께 저장."""
import re

SIGNAL_TYPES = [
    ("수요조사", ["수요조사", "기술수요"]),
    ("설명회", ["설명회", "매칭데이", "간담회"]),
    ("선정결과", ["선정", "결과"]),
    ("사전공고", ["사전공고", "사전공시", "예고", "RFP"]),
]


def _hits(text, words):
    found = []
    for w in words:
        if re.fullmatch(r"[A-Za-z]+", w):
            if re.search(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])", text):
                found.append(w)
        elif w in text:
            found.append(w)
    return found


def classify(it, profile):
    text = " ".join([it["title"], it["extra"].get("content", ""),
                     it["extra"].get("field", ""), it["extra"].get("purpose", "")])
    domains, matched = [], []
    for name, words in profile["domains"].items():
        h = _hits(text, words)
        if h:
            domains.append(name)
            matched += h
    interest = _hits(text, profile["interests"])
    excluded = bool(_hits(it["title"], profile["exclude"]))

    ministries = [it["ministry"]] + it["extra"].get("co_ministries", [])
    agencies = [it["agency"]] + it["extra"].get("co_agencies", [])
    focus_org = (any(a in profile["focus_agencies"] for a in agencies)
                 or any(f in m for m in ministries
                        for f in profile["focus_ministries"]))

    # 보건의료 관련성 게이트: 보건 기관이 아니면 보건 용어가 있어야 점수 인정
    health = bool(_hits(text, profile.get("health_terms", [])))
    relevant = focus_org or health

    score = 0
    if focus_org:
        score += 35
    elif health:
        score += 20
    score += min(len(domains), 2) * 15
    score += min(len(interest), 3) * 10
    if not relevant:
        score = min(score, 15)
        domains = []
    if excluded:
        score = min(score, 10)
    score = min(score, 100)

    it["domains"] = domains
    it["matched"] = sorted(set(matched + interest))
    it["focus_org"] = focus_org
    it["health"] = relevant
    it["score"] = score
    if it["kind"] == "signal":
        it["signal_type"] = next(
            (t for t, ws in SIGNAL_TYPES if _hits(it["title"], ws)), "일반공지")
    return it
