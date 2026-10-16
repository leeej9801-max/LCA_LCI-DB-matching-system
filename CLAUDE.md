# CLAUDE.md — LCI-Match

국가 LCI DB(ILCD)를 적재하고, 자동차 부품 BOM을 LCI 데이터셋에 매칭하는 보조 도구.
비상업 포트폴리오 프로젝트(에코에이블컨설팅 지원용). 계획은 대화가 아니라 **`docs/LCA/`** 에 있다.

## 작업 시작 전 (반드시 이 순서)

1. `docs/LCA/00-START.md` 를 읽는다. 현재 상태, 문서 지도, 작업 규칙이 있다.
2. `docs/LCA/_inbox/` 에 파일이 있으면 읽고, 내용을 본 문서에 반영한 뒤 `docs/LCA/archive/` 로 옮긴다.
3. `docs/LCA/decisions.md` 에서 확정된 결정과 열린 질문을 확인한다. 확정된 것을 뒤집지 않는다.
4. `docs/LCA/TASKS.md` 에서 이번 작업 조각을 고른다. 조각 하나 = 화면 하나 + 그 화면의 API 몇 개.

## 스택

- Backend: FastAPI, Python 3.12, uv (`Backend/`). 실행: `cd Backend && uv run fastapi dev main.py` (8000번 포트)
- Frontend: Vite 7 + React 19 (JavaScript, TypeScript 아님) + Bootstrap 5 + axios + react-router 8 (`Frontend/`). 실행: `cd Frontend && npm run dev`
- 별칭: `@`, `@pages`, `@styles`, `@assets`, `@hooks` (vite.config.js 참고)
- UI 문구는 한국어, 코드 식별자는 영어.

## 원칙

- AI는 후보 추천과 설명, **코드는 계산·검증**, 사람은 최종 판단. 숫자·단위 계산은 LLM이 하지 않는다.
- 환산이 끝나지 않은 행의 승인은 서버가 409로 거부한다.
- 측정하지 않은 값을 지어내지 않는다. 값이 없으면 null 또는 "—". 0이나 빈 문자열로 채우지 않는다.
- 국가 LCI DB 원본(ZIP, XML, 목록 xlsx)을 저장소에 넣지 않는다. 재배포 금지.
- 설계에 없는 API 필드·엔드포인트를 코드에서 먼저 만들지 않는다. **문서를 먼저 고치고** 코드를 맞춘다.

## 번호 체계 (문서·코드·커밋 어디서나 같은 번호를 쓴다)

- FR-xxx: 기능 (기능명세) · S1~S9: 화면 · A01~A20: API (API 명세서) · V1~V5: Veto 규칙 · M1~M11: 모듈

## 계약 변경 절차

1. API 명세서(`docs/LCA/spec/`)에서 필드·파라미터를 먼저 바꾼다.
2. 변경 이력에 날짜, 영향받는 A번호와 화면을 한 줄 적는다.
3. mock 픽스처(`docs/LCA/fixtures/`, `Frontend/src/api/mock/`)와 백엔드 Pydantic 모델을 함께 고친다. 한쪽만 고치지 않는다.

## 작업 끝낼 때

- `docs/LCA/TASKS.md` 의 해당 조각 상태를 갱신한다.
- 대화나 작업 중 새로 정해진 것은 `docs/LCA/decisions.md` 에 한 줄 추가한다.
- 커밋 메시지에 FR/A/S 번호를 넣는다. 예: `S4 데이터셋 탐색 화면과 A05·A06 mock 추가`
