# rnd-grant-monitor

제약·바이오·디지털헬스·의료기기 분야 정부 R&D 과제 모니터링. 1단계는 보건복지부 중심.

## 구조

```
GitHub Actions(매일 06:50 KST) → src/run.py → data/*.json → GitHub Pages 화면
```

| 소스 | 방식 | 종류 |
|---|---|---|
| IRIS 사업공고 | 화면 내부 JSON | notice |
| IRIS 사업예고 | 화면 내부 JSON | forecast (선제 신호) |
| KHIDI 공지 | 화면 내부 JSON | signal (수요조사·설명회) |
| KMDF 공지 | HTML 목록 | signal |

## 데이터 (`data/`)

- `notices.json` 사업공고 · `forecasts.json` 사업예고 · `signals.json` 공지 신호
- `meta.json` 마지막 실행 시각, 소스별 건수, 실패 내역, 신규 항목

공통 필드: `id, source, kind, title, ministry, agency, notice_no, status, posted, open_date, close_date, url, domains, matched, score, first_seen, last_seen, extra`

## 설정

`config/profile.json`의 키워드로 분야 태깅과 적합도 점수(0~100)를 계산. 공개 저장소이므로 민감한 정보는 넣지 않음.

## 알림

관련도 `notify_min_score` 이상 신규 항목 또는 수집 실패 시 GitHub Issue 생성 → 등록 이메일로 알림.
