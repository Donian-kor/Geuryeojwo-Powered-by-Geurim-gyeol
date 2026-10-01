# Geuryeojwo v0.2

**Local AI Image Studio — Powered by Geurim-gyeol**

클라우드 없이 내 PC에서 그림을 그리는 프로그램입니다.
이미지 생성과 VRAM 관리를 전부 **ComfyUI** 에 맡기고,
이 프로그램은 워크플로를 골라 값을 넣고 결과를 저장하는 역할만 합니다.

## 구조

```text
PySide6 GUI → Geurim-gyeol Engine → ComfyUI (HTTP/WebSocket) → 이미지
```

**Geurim-gyeol** 은 모델이 아니라 내부 엔진입니다.
워크플로 로드, 파라미터 주입, 진행률 표시, 결과 저장만 담당합니다.

### 더 이상 하지 않는 일

- ❌ torch / diffusers 로 모델을 직접 실행하지 않음
- ❌ VRAM 을 직접 관리하지 않음 (ComfyUI 가 전부 담당)
- ❌ 로컬 GGUF LLM 을 띄우지 않음
  (프롬프트 인핸싱은 워크플로 안의 노드가 처리합니다)

그래서 **CUDA 빌드 설치도 필요 없습니다.**

## 실행 방법

### 1. ComfyUI 를 먼저 실행

```bash
# ComfyUI 설치 폴더에서
python main.py --api --port 8188
```

`--api` 가 있어야 이 프로그램이 쓰는 REST/WebSocket API 가 열립니다.
기본 주소는 `http://127.0.0.1:8188` 입니다.
다른 주소를 쓰려면 `config/comfyui.json` 을 고치세요.

```json
{
  "host": "127.0.0.1",
  "port": 8188,
  "timeout_seconds": 300,
  "connect_timeout_seconds": 5
}
```

> `base_url` 키는 읽지 않습니다. 위 스키마(`host`/`port`)를 사용하세요.

### 2. 이 프로그램 실행

```bash
.venv\Scripts\python.exe main.py
```

ComfyUI 가 꺼져 있으면 상단에 경고 배너가 뜹니다.
실행한 뒤 `상태 새로고침` 을 누르면 다시 확인합니다.

### 자동 실행 (선택)

매번 ComfyUI 를 먼저 여는 대신, 이 프로그램이 자동으로 띄우게 할 수 있습니다.

```json
{
  "auto_launch": true,
  "launch_command": "C:\\ComfyUI\\venv\\Scripts\\python.exe main.py",
  "launch_working_dir": "C:\\ComfyUI",
  "launch_wait_seconds": 90
}
```

| 항목 | 설명 |
|---|---|
| `launch_command` | 실행할 명령. `--api` 와 `--port` 는 자동으로 붙습니다 |
| `launch_working_dir` | 실행 폴더. ComfyUI 폴더를 지정하세요 |
| `launch_wait_seconds` | 응답을 기다리는 초. 기본 90초 |

**경로에 공백이 있으면 그 부분만 따옴표로 감싸세요.**

```json
"launch_command": "\"C:\\Program Files\\ComfyUI\\python.exe\" main.py"
```

이 프로그램이 띄운 ComfyUI 는 종료할 때 자동으로 정리됩니다.
사용자가 직접 실행한 ComfyUI 는 건드리지 않습니다.

## 워크플로 사용하기

`workflows/` 폴더의 JSON 파일 하나가 워크플로 하나입니다.

```text
workflows/
└── qwen-image-2.1.json
```

### ComfyUI 에서 그대로 내보내기

ComfyUI 화면에서 `Workflow → Export (API)` 로 저장하면 바로 사용할 수 있습니다.
`parameters` 맵이 없어도 프로그램이 자동으로 조작 가능한 값을 찾아냅니다
(프롬프트, negative, 해상도, steps, CFG, seed, sampler 등).

### parameters 맵을 직접 지정하기

자동 인식이 마음에 안 들면 이렇게 쓸 수 있습니다.

```json
{
  "name": "표시 이름",
  "description": "설명",
  "output_node": "8",
  "prompt": { "...": "ComfyUI API 형식 그대로" },
  "parameters": {
    "positive": { "node": "14", "input": "prompt", "label": "프롬프트" },
    "width":    { "node": "5",  "input": "width", "kind": "int" },
    "steps":    { "node": "6",  "input": "steps", "kind": "int" }
  }
}
```

`kind` 는 `text` / `int` / `float` / `combo` 입니다.
여기에 없는 입력은 GUI에서 자동으로 비활성화됩니다.

## 샘플러 선택

Generation 영역의 **Sampler** / **Scheduler** 드롭다운은
ComfyUI 에서 직접 받아온 선택지입니다 (`KSampler` 노드 기준).

- 워크플로가 `sampler_name` 또는 `scheduler` 입력을 가지면 활성화됩니다
- 선택하지 않으면 워크플로에 적힌 기본값이 그대로 쓰입니다
- ComfyUI 응답이 없으면 워크플로 기본값만 표시합니다

## 폴더 구조

```text
app/
├── comfy/            ComfyUI API 클라이언트와 워크플로 로더
│   ├── client.py     HTTP/WebSocket 통신
│   ├── config.py     접속 설정
│   └── workflow.py   워크플로 파싱 · 값 주입 · 파라미터 자동 인식
├── engine/
│   ├── comfy_engine.py   엔진 (GUI 가 호출하는 동기 façade)
│   ├── output/           출력 이미지 + JSON 저장
│   └── session/          생성 이력 기록
└── gui/               PySide6 화면

workflows/         워크플로 JSON
outputs/           생성된 이미지 (날짜별 폴더)
sessions/          생성 이력
config/            comfyui.json, theme_config.json
```

## 설정

| 파일 | 용도 |
|---|---|
| `config/comfyui.json` | ComfyUI 접속 주소와 타임아웃 |
| `config/theme_config.json` | 다크/라이트 테마 |

## 테스트

```bash
.venv\Scripts\python.exe -m pytest -q
```

네트워크에 연결하지 않고 동작합니다.

## 요구 환경

- Python 3.10 이상
- ComfyUI (별도 설치, GPU 환경에 맞게 설치)
- 아래 패키지

```bash
pip install -r requirements.txt
```

`torch`, `diffusers`, `transformers`, `llama-cpp-python` 은 필요 없습니다.

## v0.7 Architecture

The GUI is being migrated toward feature-based modules under `app/gui/pages/`, reusable components under `app/gui/widgets/`, controllers under `app/gui/controllers/`, and background workers under `app/gui/workers/`. ComfyUI integration is isolated under `app/engine/comfy/`.
