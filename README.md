# rnd-grant-monitor

제약·바이오·디지털헬스·의료기기 분야 정부 R&D 과제 모니터링. 1단계는 보건복지부 중심.

## 구조

```
GitHub Actions(매일 06:50 KST) → src/run.py → data/*.json → GitHub Pages 화면
                 (월·금 10:00 KST) → src/digest.py → 요약 메일
```

| 소스 | 방식 | 종류 |
|---|---|---|
| NTIS 국가R&D통합공고 | 공개 HTML (RFP 단위) | notice·signal (수요조사) |
| IRIS 사업공고 | 화면 내부 JSON | notice (공고번호 보완) |
| IRIS 사업예고 | 화면 내부 JSON | forecast (선제 신호) |
| KHIDI 공지 | 화면 내부 JSON | signal (수요조사·설명회) |
| KMDF 공지 | HTML 목록 | signal |
| KHIDI 대표사이트 사업공고 | HTML 목록 | 비R&D notice·signal |
| NIPA 사업공고 | HTML 목록 | 비R&D notice (헬스 관련만) |
| 보건복지부 공지(공고) | HTML 목록 | 비R&D notice (혁신형 제약 등) |

## 데이터 (`data/`)

- `notices.json` 현재 공고(접수중·예정·최근 마감) · `history.json` 과거 13개월 공고 · `forecasts.json` IRIS 사업예고 · `signals.json` 수요조사·설명회 등
- `predictions.json` 사업별 공고 회차와 다음 공고 예상 시점 (간트차트용, `src/predict.py`)
- `notices_other.json` 분야 밖으로 분류된 공고 (검증용)
- `meta.json` 마지막 실행 시각, 소스별 건수, 실패 내역, 신규 항목

공통 필드: `id, source, kind, title, ministry, agency, notice_no, status, posted, open_date, close_date, url, domains, matched, score, first_seen, last_seen, extra`

## 화면

GitHub Pages: https://sobi2026.github.io/rnd-grant-monitor/ — 공고 일정·예측(간트), 현재 공고, 신호·사업예고.
수집(`collect`) 성공 후 `pages` 워크플로가 `web/` + `data/`를 배포.

## 예측 방법

과거 공고를 사업 단위로 묶고(연도·차수·RFP 접미사 제거), 각 회차를 1년 뒤로 옮겨 예상 시점으로 표시.
신뢰도: 상(13개월 내 2회 이상 + IRIS 사업예고 등재), 중(둘 중 하나), 하(1회).

## 설정

`config/profile.json`의 키워드로 분야 태깅과 적합도 점수(0~100)를 계산. 공개 저장소이므로 민감한 정보는 넣지 않음.

## 알림

매주 월·금 10:00 KST 요약 1통 (`notify.yml` → `src/digest.py` → GitHub Issue → 등록 이메일).
구성: 마감 임박(7일) · 신규 공고(RFP 묶음) · 신규 신호(수요조사·설명회) · 관심 주제 · 45일 내 예상 공고 · 수집 상태.
수시 발송: Actions › notify › Run workflow. 수집은 매일 06:50 KST(화면 갱신용, 알림 없음).
