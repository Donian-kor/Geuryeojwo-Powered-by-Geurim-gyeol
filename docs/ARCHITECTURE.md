# Architecture

그려줘(Geuryeojwo)의 구조 설명서다.
아키텍처 목표와 **현재 구현**을 함께 적는다. 구현과 다른 부분은
코드 기준이 아니라 목표이므로 §9 에 따로 모은다.

- 기준 커밋: `4f14f67`
- 마지막 검증: pytest 85개 통과 (아키텍처 쪽 코드 전수 확인)

## 1. 왜 ComfyUI 를 쓰는지

이 프로그램의 목적은 모델 지원 범위가 아니라
"AI 이미지 생성의 복잡성을 사용자에게 보여주지 않는다" 는 것이다.

직접 모델을 실행하지 않는 이유는 과거 기획 단계에서 측정했다.

1. **신규 모델 지원 속도** — ComfyUI 는 모델 발표와 같은 주에 지원한다.
2. **양자화 포맷의 비공개성** — ComfyUI 배포본 가중치는 `comfy_quant` 패킹을 쓴다.
   Qwen-Image 2.1 은 텐서 841개 중 192개가 NVFP4 로 패킹돼 있다.
3. **직접 로드 불가** — `from_single_file` / `from_pretrained` 경로가 실제로 실패한다.

이 결정을 뒤집은 전제("외부 런타임 의존 0")는 유효하지 않다.

## 2. 프로젝트 개요

| 항목 | 값 |
|---|---|
| 제품 | 그려줘 v0.2 (Geuryeojwo) |
| 엔진 | 그림결 (Geurim-gyeol) v0.2 |
| 런타임 | ComfyUI (외부 프로세스, HTTP/WebSocket) |
| 언어 / GUI | Python 3.x / PySide6 |
| 버전 단일 출처 | `app/__init__.py` 의 `__version__` = `0.7.0` |
| 대상 OS | Windows / macOS / Linux |

## 3. 아키텍처

```
┌──────────────────────────────────────────┐
│           그려줘 v0.2 (PySide6)           │
│  Generate │ Model │ History              │
└────────────────┬─────────────────────────┘
                 │ HTTP + WebSocket (127.0.0.1:8188)
                 ▼
┌──────────────────────────────────────────┐
│           그림결 v0.2 (Engine)            │
│  GeurimGyeolEngine  — 생성 오케스트레이션  │
│  Workflow / infer_parameters             │
│  ComfyClient      — HTTP/WebSocket        │
│  OutputManager / SessionManager          │
└────────────────┬─────────────────────────┘
                 │ POST /prompt
                 ▼
┌──────────────────────────────────────────┐
│         ComfyUI (외부 프로세스)           │
│  모델 로딩 · 샘플링 · VAE · 메모리         │
│  프롬프트 인핸서 LLM 호출                 │
└────────────────┬─────────────────────────┘
                 │ GET /view
                 ▼
               PNG 결과
```

**이 프로그램이 하는 일** — 사용자 입력 수집, 워크플로 JSON 생성·제출,
진행률 수신, 결과 정리·저장, 서버 상태 표시.

**하지 않는 일(ComfyUI 담당)** — 가중치 해석, 샘플링, 양자화,
VRAM 스와핑, 프롬프트 확장.

## 4. 역할 경계

| 담당 | 내용 |
|---|---|
| ComfyUI | 모델 실행, VRAM 관리, 프롬프트 확장(인핸서 노드) |
| 그림결 엔진 | 워크플로 파싱, 파라미터 매핑, 생성 오케스트레이션, 기록 |
| GUI | 입력, 선택, 표시, 기록 열람 |

프롬프트 확장은 워크플로 안의 노드(`QwenImage21PromptEnhancerT8` 등)가
담당한다. GUI 는 스위치 하나만 노출하고, 끄면 그 노드를 실행 그래프에서
제거한다(§7).

## 5. ComfyUI 연동 인터페이스

### 5.1 실행 조건

```
python main.py --api --port 8188
```

`--api` 가 없으면 이 프로그램이 쓰는 API 가 열리지 않는다.
기본적으로 사용자가 직접 실행하며, 이미 실행 중이면 재사용한다.
`config/comfyui.json` 의 `auto_launch` 를 `true` 로 켜면 이 프로그램이 띄운다.

### 5.2 설정 파일 `config/comfyui.json`

실제로 읽는 키 (`app/comfy/config.py`):

```json
{
  "host": "127.0.0.1",
  "port": 8188,
  "timeout_seconds": 300,
  "connect_timeout_seconds": 5,
  "auto_launch": false,
  "launch_command": "",
  "launch_working_dir": "",
  "launch_wait_seconds": 90,
  "model_folders": ["checkpoints", "diffusion_models", "vae",
                    "loras", "text_encoders"]
}
```

`base_url` 은 **읽는 키가 아니라** `host` + `port` 로부터 계산하는
파생 속성이다. 설정 파일에 넣어도 무시된다.

### 5.3 사용하는 API (코드 실측)

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/system_stats` | VRAM · 장치 정보 |
| GET | `/models` | 모델 폴더 목록 |
| GET | `/models/{folder}` | 폴더별 모델 목록 |
| GET | `/object_info[/{node}]` | sampler · scheduler 선택지 |
| GET | `/queue` | 대기열 — **호출자 없음** |
| POST | `/prompt` | 워크플로 제출 |
| WS | `/ws?clientId=` | 진행률 수신 |
| GET | `/history/{prompt_id}` | 실행 결과 |
| GET | `/view` | 이미지 다운로드 |
| POST | `/interrupt` | 실행 중단 |
| POST | `/free` | 모델 언로드 |

`/models` 는 질의 문자열이 아니라 **경로로** 폴더를 붙인다
(`?folder=...` 가 아니다). `get_all_models()` 는 `model_folders` 의 각 폴더를
순차 호출해 하나의 dict 로 합친다.

### 5.4 POST /prompt

```json
{"prompt": {"6": {"class_type": "KSampler", "inputs": {...}}},
 "client_id": "<uuid>"}
```

링크는 `["출발 노드 id", 출력 슬롯]` 배열이다.
`node_errors` 가 비어 있지 않으면 `ComfyUIError` 로 승격해
메시지를 그대로 사용자에게 전달한다.

### 5.5 WebSocket

실행 순서는 고정이다.

```
WebSocket 연결 → POST /prompt → prompt_id 확보 → 이벤트 수신
```

**연결을 먼저 여는 이유**: 반대 순서면 실행이 빠른 워크플로에서
`executing` + `node=null` 완료 신호가 연결 전에 지나가고,
이미 끝난 작업이 `timeout_seconds` 만큼 멈춘 뒤 타임아웃으로 오탐된다.

수신한 메시지는 `data.prompt_id` 가 자신의 것인 이벤트만 처리한다.
같은 ComfyUI 를 다른 프로그램이 쓰는 중일 때 남의 완료 신호로
오인하지 않기 위해서다. `status` / `queue` 는 대상 지정이 없어 통과시킨다.

`progress` 의 `value` / `max` 를 10~90% 구간으로 매핑한다.

### 5.6 자동 실행 규칙

- `launch_command` 에 `--api` · `--port` 가 없으면 자동으로 붙인다(중복 금지)
- 이 프로그램이 띄운 프로세스만 종료한다 — 사용자가 직접 실행한 ComfyUI 는 건드리지 않는다
- 종료 시 `POST /free` 로 모델을 먼저 내린 뒤 terminate, 실패 시 kill
- 대기는 **백그라운드 스레드**에서 수행한다(§7)

## 6. 워크플로 관리

### 6.1 파일 형식

`workflows/` 의 JSON 을 읽는다. 현재 파일 2개.

```json
{
  "name": "표시 이름",
  "description": "설명",
  "output_node": "8",
  "prompt": { "...ComfyUI API 형식..." },
  "parameters": {
    "<파라미터명>": {"node": "6", "input": "steps"}
  }
}
```

- `prompt` 키가 **없으면 문서 전체를 워크플로로 본다**
  → ComfyUI 화면의 Export (API) 결과를 그대로 넣어도 읽힌다
- `parameters` 가 비어 있으면 자동 추론(§6.2)을 쓴다
- `name` 이 없으면 파일명이 표시명이 된다

### 6.2 자동 추론 규칙 (`infer_parameters`)

`class_type` 이름이 아니라 **데이터 흐름**을 따른다.

| 대상 | 규칙 |
|---|---|
| 프롬프트 | `prompt`/`text`/`positive` 입력 중 **링크(배열)가 아닌 값**을 가진 것. KSampler 로 가는 경로가 가장 짧은 노드 |
| 샘플러 파라미터 | `seed`/`steps`/`cfg`/`denoise`/`sampler_name`/`scheduler` — `class_type`이 `KSampler`/`Sampler`/`KSamplerAdvanced` 로 시작 **AND** SaveImage/PreviewImage 에서 거슬러 올라가 만나는 샘플러 |
| 모델 | `unet_name`→`diffusion_models`, `ckpt_name`→`checkpoints`, `clip_name`→`text_encoders`, `vae_name`→`vae`, `lora_name`→`loras` |
| 스칼라 | `seed` `steps` `width` `height` `batch_size` `resolution` `max_output_chars` `cfg` `denoise` `guidance` `strength_model` `strength_clip` `sampler_name` `scheduler` |

프롬프트 인핸서 노드는 `class_type` 에 `TextEncode` 가 없어도
프롬프트를 실제로 받으므로 후보가 된다. 인핸서와 KSampler 가 모두
`seed` 를 가질 때는 KSampler 쪽만 선택된다.

### 6.3 값 주입 규칙

- 맵의 **key 이름은 자유**다. 조회·주입은 `spec.input`(ComfyUI 입력 이름) 기준
- **링크로 연결된 입력은 덮어쓰지 않는다** — 사용자가 넣은 값이 조용히 버려지는 것을 막는다
- 워크플로 복사본을 만들어 수정하므로 원본 파일은 바뀌지 않는다

### 6.4 활성 워크플로

활성 워크플로는 **메모리에만** 있다. 재시작하면 파일명 순 첫 번째로
되돌아간다. 설정 파일에 저장하지 않는다.

### 6.5 모델 선택

ComfyUI 모델 폴더를 직접 읽지 않고 `/models/{folder}` 로 이름을 받는다.
ComfyUI 의 `extra_model_paths.yaml`, 심볼릭 링크, 여러 경로가 그대로 반영된다.

워크플로가 해당 입력을 가지고 있을 때만 드롭다운을 활성화한다.
ComfyUI 응답이 없으면 워크플로 기본값 하나만 표시한다.

**워크플로가 지정한 모델이 목록에 없으면 다른 파일로 대체하지 않는다.**
목록에 없는 이름을 그대로 넣고 빨간색 + 툴팁으로 표시하며, 경고 문구를
Model 탭에 띄우고 생성을 막는다. 대체하면 사용자는 자신이 무엇을
생성했는지 알 수 없게 된다.

### 6.6 판정 로직의 위치

모델 설치 여부와 위젯 값의 키 변환은 `app/comfy/workflow.py` 의 순수
함수다. `main_window.py` 는 위젯 값을 읽어 넘기고 색과 문구만 그린다.

| 함수 | 하는 일 |
|---|---|
| `input_of` | 위젯 키 → ComfyUI 입력 이름 |
| `model_folder` | 파라미터의 `kind` 에서 ComfyUI 폴더 이름 |
| `installed_models` | 그 폴더에 설치된 파일 목록 |
| `missing_models` | 선택 중 미설치된 항목 |
| `collect_extra` | 위젯 값 → {파라미터 키: 값} |

전부 `dict` 와 `str` 만 주고받는다. PySide6 를 import 하지 않으므로
GUI 없이 검증된다 — `tests/test_workflow_rules.py` 가 그 증거다.

## 7. 생성 흐름

```
1. 워크플로 목록 로드 (workflows/ 스캔 + 파라미터 추론)
2. 백그라운드 워커가 ComfyUI 상태·모델·샘플러 목록 조회
3. 워크플로 선택 → 파라미터 위젯 활성화/비활성화
4. 사용자 입력 (프롬프트·모델·파라미터)
5. 샘플러/모델/LoRA 값을 extra 로 수집
6. 워크플로 JSON 생성 (parameters 주입)
7. 인핸서 스위치가 꺼졌으면 인핸서 노드 실행 그래프에서 제거
8. WebSocket 연결 → POST /prompt → progress 수신
9. 완료 대기 (executing, node=null, prompt_id 일치)
10. GET /history/{prompt_id} → GET /view
11. PNG + JSON 저장 → 세션 기록 → History 목록 갱신
```

진행률 매핑: `0%` 준비 / `5%` 제출 / `10~90%` 샘플링 / `100%` 완료.

**스레드 규칙**

| 스레드 | 하는 일 |
|---|---|
| GUI | 위젯 갱신, 입력 |
| `ComfyInfoWorker` | `/system_stats` · `/models` · `/object_info` 조회 |
| `Worker` | 생성 전체 (`generate` + 이미지 저장 + 세션 기록) |

ComfyUI 조회는 GUI 스레드에서 하지 않는다. 창이 뜨는 속도부터
`[상태 새로고침]` 응답까지 네트워크 대기를 지연시킨다.
목록은 `self._comfy_models` / `self._comfy_samplers` 캐시로 읽는다.

창을 닫은 뒤 도착하는 워커 시그널은 `self._closing` 가드로 무시한다.

## 8. 저장 구조

```
outputs/YYYY-MM-DD/
  img_001_seed1234.png
  img_001_seed1234.json      ← png/json 한 쌍

sessions/YYYY-MM-DD/
  <프롬프트에서 만든 이름>/
    session.json
    001.png
    001.json
```

- 출력 인덱스는 **최대 번호 + 1** 이다 (파일 개수 + 1 이 아니다).
  중간 파일이 지워져도 살아있는 파일을 덮어쓰지 않는다.
- 세션 폴더명은 프롬프트에서 만든다. Windows 금지 문자 제거,
  공백 정리, 32자 절단. 같은 이름이 있으면 `-2`, `-3` … 을 붙인다.
- 세션 정렬은 폴더 이름이 아니라 `session.json` 의 `created_at` 이다.
  (`created_at` 은 초 단위라 같은 초에 만든 세션은 순서가 구분되지 않는다)
- 기록에는 `original_prompt`(사용자 원문)와 `prompt`(실제 사용된 최종값)를
  구분해 남긴다.

## 9. 디렉토리 구조

### 현재 구현 (실측)

```
app/
  __init__.py               버전 상수
  comfy/
    client.py      444줄    ComfyClient · SystemInfo · extract_text_outputs
    config.py      186줄    ComfyUIConfig
    workflow.py    354줄    Workflow · ParameterSpec · infer_parameters · collect_extra
  engine/
    comfy_engine.py 571줄  GeurimGyeolEngine · GenerationRequest/Result
    health.py        88줄  UsageLevel · Thresholds · ram/vram/gpu/cpu_level
    output/manager.py 172줄  OutputManager · OutputMetadata · next_index
    session/manager.py 258줄 SessionManager · SessionMetadata · _slugify
  gui/
    main_window.py  1075줄  MainWindow · ModelInfoPanel · _paint_usage
    session_browser.py 427줄 HistoryBrowser
    gpu_usage.py    163줄  GpuUsageReader (nvidia-smi 상주)
    theme/manager.py 193줄  ThemeManager

workflows/     ComfyUI API 형식 워크플로
config/        comfyui.json · theme_config.json
outputs/       날짜별 결과
sessions/      날짜별 생성 기록
logs/
```

GUI 는 탭 3개다 — `Generate` / `Model` / `History`.
`Model` 탭에 워크플로 선택 · 모델 4종 · LoRA · 요약이 있고,
LoRA 강도 슬라이더는 `Generation` 프레임 안에서 파라미터와 함께 다룬다.

`History` 탭은 이미지 한 장이 한 줄이다(썸네일 + 프롬프트 + seed + 시각).
세션에 이미지가 여러 장인 경우에만 첫 줄 아래에 자식 행이 생긴다.

### 목표 구조 (아직 도달하지 않음) — 여기가 현재와 다르다

`app/comfy/` → `app/engine/comfy/`, `main_window.py` 를
`pages/ widgets/ controllers/ workers/` 로 분리하는 안이 있다.
**아직 승인·구현되지 않았다.**

`app/gui/pages/ widgets/ controllers/ workers/`,
`app/engine/generation/ storage/ comfy/` 는 **목표 구조를 표현하기 위해
만든 자리표시자 폴더이며 실제 코드는 없다.** `app/gui/page_manager.py`,
`app/engine/generation/result.py`, `app/engine/storage/identity.py`,
`app/engine/comfy/compatibility.py` 도 정의되어 있으나 어디서도
import 하지 않는다.

## 10. 의존성

```
PySide6 >= 6.6,<7     GUI
Pillow  >= 10,<13     이미지 처리
httpx    >= 0.27      HTTP
websockets >= 12.0    WebSocket
psutil   >= 5.9       RAM/CPU 표시
pytest   >= 8         테스트
```

이 프로그램은 GPU 를 직접 쓰지 않는다. PyTorch 와 CUDA 빌드 설치 책임은
ComfyUI 처이다. 프라인드라브리를 비한 외부 의존성은 위 목로이 전부다.

## 11. 테스트

`tests/` 6개 파일, 85개.

| 파일 | 개수 | 다루는 것 |
|---|---|---|
| `test_comfy_engine.py` | 47 | 워크플로 파싱, 값 주입, 메타데이터, 생성 |
| `test_gpu_usage.py` | 27 | nvidia-smi 파싱, 사용률·VRAM 동시 조회, 부재 대응 |
| `test_health.py` | 19 | 자원별 경고 단계와 표기 (GUI 없음) |
| `test_output_session.py` | 17 | 저장 · 인덱스 충돌 · 폴더명 · 버전 |
| `test_status_bar.py` | 15 | 갱신 주기 · CPU 블로킹 · 단계 색 · ModelInfo 일치 |
| `test_history_browser.py` | 14 | 기록 1줄 목록, 썸네일, 클릭 1번 미리보기 |
| `test_workflow_rules.py` | 11 | 모델 설치 판정 · 값 조립 (GUI 없음) |
| `test_model_selection.py` | 6 | 미설치 모델 표시와 생성 차단 |
| `test_websocket_flow.py` | 4 | 실제 소켓으로 WS 순서 · prompt_id 필터 |
| `test_non_blocking_refresh.py` | 4 | 새로고침이 GUI 스레드를 막지 않음 |
| **합계** | **164** | |

`conftest.py` 는 `QT_QPA_PLATFORM=offscreen` 만 기본 설정해
GUI 테스트를 화면 없이 돌린다.

**네트워크를 막는 장치는 없다.** 서버에 닿지 않는 것은 각 테스트가
`monkeypatch` 로 `get_system_info` · `model_options` · `generate` 등을
직접 대체해서이다. 실측 — 스위트 164개 실행 중 ComfyUI PID 불변,
8188 포트로의 TCP 연결 0건. 다만 테스트를 새로 추가하면서 이 관례를
빼먹으면 사용자의 서버를 건드릴 수 있다. 실제 생성 검증이 필요하면
pytest 가 아니라 `tools/smoke_generate.py` 를 쓴다.

## 12. 프로젝트 성격

> "ComfyUI 는 그림결의 필수 구성요소다"

그림결과 ComfyUI 는 한 쌍의 프로세스로 동작하고 HTTP 로 통신한다.
사용자에게는 하나의 프로그램으로 보이지만 안에서는 역할이 나뉜다.

사용자가 대신 감당하는 것 — 워크플로 JSON 을 `workflows/` 에 넣기,
모델 파일을 ComfyUI 모델 폴더에 두기, 자신의 프롬프트 고치기.

설계상 감수하는 부분 — 워크플로가 워크플로를 담는 구조(인핸서 안에 LLM 설정,
LoRA 안에 모델 이름)가 그대로 드러난다. JSON 을 여는 것이 곧 설정을 하는
것이라 복잡성을 숨기는 목표와는 어느 정도 어긋난다. ComfyUI 라는 선택의 대가다.




