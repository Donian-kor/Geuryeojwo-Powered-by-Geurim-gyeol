# Roadmap

그려줘(Geuryeojwo)의 진행 상황이다.
구조 설명은 [ARCHITECTURE.md](ARCHITECTURE.md) 를 본다.
여기 적는 내용은 **커밋과 테스트로 확인된 것**만 적는다.

- 기준 커밋: `4f14f67`
- pytest 85개 통과
- 앱 코드 28개 파일(테스트 포함)

## 1. 현재 상태

| 항목 | 상태 |
|---|---|
| ComfyUI 연동 | 동작 — `--api` 로 실행 중이면 사용 |
| 워크플로 → 이미지 생성 | 동작 — Qwen-Image 2.1 로 실측 확인 |
| 진행률 수신 | 동작 — 5→30→50→70→90→100% 매핑 확인 |
| 모델·샘플러 선택 | 동작 — `/models`, `/object_info` 에서 받음 |
| LoRA 강도 | 동작 — 슬라이더 값이 `strength_model` 로 주입됨 |
| 프롬프트 인핸서 | 동작 — 워크플로 안의 LLM 노드가 담당 |
| 기록·재생성 | 동작 — History 탭에서 1줄 목록, 클릭 1번으로 미리보기 |
| GUI 스레드 블로킹 | 해소 — 서버 조회는 백그라운드 스레드 |

## 2. 해결한 문제

각 항목은 회귀 테스트로 고정돼 있다. 주소를 `git show` 로 되돌리면
대상 테스트가 실패하는 것을 확인했다.

| 문제 | 조치 | 검증 |
|---|---|---|
| WebSocket 을 POST 뒤에 열어 완료 신호 유실 | WS 선연결 → POST → `prompt_id` 확보 순으로 변경 | `test_websocket_flow.py` (실제 소켓) |
| 남의 prompt 신호를 자기 완료로 오인 | `data.prompt_id` 가 내 것인 이벤트만 처리 | `test_websocket_flow.py` |
| 인핸서 OFF 인데 LLM 이 계속 호출됨 | 인핸서를 참조하는 모든 노드의 입력을 끊고 노드 자체를 payload 에서 제거 | `test_comfy_engine.py` |
| 기록에 원본 프롬프트만 남음 | `run_details=True` 로 history 를 받아 인핸서 출력 읽기, `original_prompt` / `prompt` 구분 | `test_comfy_engine.py` |
| 파일·세션 덮어쓰기(데이터 손실) | 인덱스를 파일 개수 + 1 이 아니라 **최대 번호 + 1** 로 | `test_output_session.py` |
| VRAM 없음에서 예외 | 포맷 전 None 여부 확인(3곳) | `test_comfy_engine.py` |
| 새로고침이 창을 2~10초 멈춤 | 상태·모델·샘플러 조회를 `ComfyInfoWorker` 스레드로 이동 | `test_non_blocking_refresh.py` |
| 이벤트 루프가 호출마다 새로 생김 | 엔진이 루프 1개를 소유해 재사용 (15회 호출 → 루프 1개) | 실제 생성 실측 |
| 새로고침하면 고른 모델이 리셋 | 목록을 다시 채워도 사용자의 선택을 되돌려 놓음 | `test_non_blocking_refresh.py` |
| 미설치 모델을 조용히 다른 모델로 대체 | 이름을 그대로 두고 빨간색 표시 + 경고 + 생성 차단 | `test_model_selection.py` |
| 세션 기록이 화면에 안 보임 | 날짜 그룹을 접던 동작 제거, 목록 1줄화 | `test_history_browser.py` |
| 세션 폴더명이 `194036-001` | 프롬프트에서 이름을 만듦(금지문자 제거·32자 절단) | `test_output_session.py` |
| 창을 닫은 뒤 워커 시그널 도착 | `_closing` 가드로 무시 | GUI 스모크 |
| 테스트가 실제 서버에 접속 | `conftest.py` + 픽스처에서 네트워크 차단, 27초 → 5초 | 전체 스위트 |
| 죽은 코드·미사용 import | `client.py` 의 `return` 뒤 코드, `processEvents`, 미사용 import 제거 | 전체 스위트 |
| 버전 문자열 `0.1.0` | `app.__init__.__version__` 을 단일 출처로 | `test_output_session.py` |
| README 가 잘못된 실행 명령 | `--api` 로 정정, 설정 스키마를 실제 코드에 맞춤 | — |

## 3. 남은 작업

### B7 — asyncio 수명 관리 (해결)

`asyncio.run` 이 `comfy_engine.py` 에 **9곳** 있었다. 엔진은 동기 facade 라
`ComfyClient`(비동기)를 매번 `asyncio.run` 으로 감쌌고, `asyncio.run` 은
호출마다 이벤트 루프를 새로 만들어 닫는다. 그래서 호출 횟수만큼
`httpx.AsyncClient` 가 새로 생기고 앞의 것들은 `aclose()` 되지 않은 채
GC 에 맡겨진다.

엔진이 이벤트 루프를 하나 소유하고 재사용하도록 바꿨다. GUI 스레드와
워커 스레드가 함께 쓸 수 있어 잠금으로 직렬화한다.

측정 (엔진 호출 15회):

| | 수정 전 | 수정 후 |
|---|---|---|
| 생성된 이벤트 루프 | 15 | **1** |
| `shutdown()` 후 닫힘 | — | 1/1 |

### 구조 이동 (아직 승인되지 않음)

- `app/comfy/` → `app/engine/comfy/`
- `main_window.py`(827줄) → `pages/ widgets/ controllers/ workers/`
- `app/gui/pages/` 등 자리표시자 폴더는 지금 코드가 없다

### 사소한 것

- `ModelInfoPanel` 이 긴 값(예: 워크플로 파일명)에서 글자가 겹쳐 보인다
- `outputs/` 파일명은 여전히 `img_001_seed999.png` 형태다.
  세션 폴더만 이름을 바꿨다
- `get_queue()` 는 정의돼 있으나 호출자가 없다
- `created_at` 이 초 단위라 같은 초에 만든 세션은 정렬 순서가 구분되지 않는다

## 4. 목표 구조 (v0.7)

목표와 현재의 차이는 [ARCHITECTURE.md §9](ARCHITECTURE.md) 에 적어 두었다.

```
app/engine/comfy/       ComfyUI 통신 전부
app/engine/workflow/    워크플로 파싱
app/engine/generation/  생성 오케스트레이션
app/engine/storage/     출력·세션
app/gui/pages/ widgets/ controllers/ workers/
```

**아직 도달하지 않았다.** 승인 대기 중이다.

## 5. 성공 기준 점검

| 기준 | 상태 |
|---|---|
| ComfyUI `--api` 서버 접속 | 충족 |
| 서버 미실행 시 안내 | 충족 |
| `/models` 로 설치 모델 목록 표시 | 충족 |
| 워크플로 JSON 추가만으로 기능 확장 | 충족 |
| 파라미터가 GUI 위젯에 자동 연결 | 충족 |
| 프롬프트 → 이미지 생성 | 충족 |
| 결과 PNG + JSON 저장 | 충족 |
| 인핸서 OFF 가 실제 실행 경로에서 우회 | 충족 |
| 원본/최종 프롬프트 구분 저장 | 충족 |
| WebSocket 이벤트 미유실 | 충족 |
| 파일·세션 ID 충돌 없음 | 충족 |
| VRAM 누락 시 GUI 정상 동작 | 충족 |
| GUI 네트워크 작업이 메인 스레드를 막지 않음 | 충족 |
| ComfyUI 통신이 단일 계층에 모임 | **미충족** — `app/comfy/` 에 있음 |
| GUI 가 pages/widgets/controllers/workers 로 구분됨 | **미충족** |
| 한 세션이 여러 이미지를 담음 | **미충족** — `GenerationResult` 에 단일 `image_path` |

## 6. 이번 판에서 하지 않은 것

- 구조 이동 (`app/comfy/` → `app/engine/comfy/`, `main_window.py` 분해) — 승인 대기 중
- `outputs/` 파일명 변경 — 기존 파일과 브라우저 glob 이 엮여 있어 별도 마이그레이션이 필요
- `ModelInfoPanel` 글자 겹침 — 시각 확인 필요
