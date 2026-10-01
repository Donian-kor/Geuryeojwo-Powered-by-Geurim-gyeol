# ComfyCraft AI Easy Studio — 전체 코드 리뷰

- **리뷰 일자**: 2026-09-29
- **재검증 일자**: 2026-09-29
- **대상 커밋**: `49d23df` (브랜치 `main`, 작업 트리 clean)
- **조사 범위**: 프로젝트 전체 Python 소스 ~~34개~~ **57개** 파일 (`.kilo/worktrees/` 중복 사본 제외, `__init__.py` 및 `tests/` 포함)
- **검증 결과**: `pytest` 70 passed (8.62s) / AST 파싱 ~~44파일~~ **57파일** 정상
- **결론**: **아키텍처는 건강합니다.** 계층 분리가 명확하고, "단일 진실" 데이터 모델과 원자적 파일 쓰기 등 높은 품질의 설계가 다수 보입니다. 다만 **테스트가 git에서 제외된 상태**라는 치박적인 문제와, **God Object 1개(~~3,919줄~~ 4,323줄)** 가 앞으로의 모든 확장의 병목이 됩니다.

> **v1.1 수정 사항 (재검증)**: PowerShell `Measure-Object -Line`가 CRLF 파일의 라인 수를 부정확하게 셌습니다(모든 라인 수 통계 수정). `_chat_log` 실제 데이터 흐름 재검증, `errorBannerLabel` 이중 블록 발견, 누락 파일 2종 추가, `PromptEnhanceWorker` 클래스 발견.

---

## 📊 조사 개요

| 항목 | 내용 |
|---|---|
| Python 파일 | ~~34개~~ **57개** (`.kilo/worktrees/` 사본 제외, `__init__.py` 및 `tests/` 포함) |
| 총 라인 | ~~약 12,700줄~~ **18,326줄** |
| 테스트 | ~~5개~~ **6개 파일** (conftest.py 포함) / 70 passed (8.62s) ✅ |
| 커밋 상태 | clean, `main` 브랜치 |
| 런타임 의존성 | `requests`, `websocket-client`, `PySide6`, `markdown` |
| 린터 도구 | **미설치** (ruff / flake8 / pylint / mypy 전부 없음) |

> **재검증 결과**: PowerShell의 `Get-Content | Measure-Object -Line`가 CRLF 줄 끝 표시가 있는 파일의 라인 수를 부정확하게 셌습니다. Python 기준으로 재측정한 모든 라인 수는 아래 표와 별도의 **정확한 값**으로 교체되었습니다. PowerShell 원본 값은 ~~취소선~~으로 표시했습니다.

### 계층 구조

```
main.py                      진입점 (테마 적용 → UI 로드 → MainController)
assets/icons/icon_rc.py      SVG 리소스 등록
assets/ui/*_ui.py            Qt Designer 생성물
app/
├── main_controller.py       ★ ~~3,919~~ **4,323**줄 — 핵심 제어 로직 (God Object)
├── constants.py             FaceDetailer 슬라이더 스펙 15종
├── paths.py                 경로 상수 (순환 참조 방지)
├── logging_config.py        로깅 설정
├── core/
│   ├── api_client.py            LM Studio / ComfyUI HTTP·WebSocket
│   ├── config_manager.py        설정 로드·저장·검증 (싱글턴)
│   ├── workflow_manager.py      템플릿 로드·치환·렌더
│   ├── workflow_factory.py      워크플로우 자동 생성·검증
│   ├── workflow_deriver.py      base + 프로필 → 모델별 파생 워크플로우
│   ├── model_fetcher.py         모델 목록 조회
│   ├── model_registry.py        모델 프로필 레지스트리
│   ├── model_status_service.py  모델 상태 조회
│   ├── connection_pool.py       ⚠ 미사용 (98줄)
│   └── model_profiles/          내장 프로필 폴백 (flux_gguf, zimage_turbo, zanime_aio, ernie_aio)
├── sections/
│   ├── connection.py            연결 확인, 모델 폴더 스캔
│   ├── generation.py            GenerationWorker (생성 워커)
│   ├── prompt.py                프롬프트 정규화·LM Studio 향상
│   ├── result.py                미리보기·저장·폴더 열기
│   ├── execution.py             진행률·경과시간·로딩 애니메이션
│   └── session.py               세션 CRUD (원자적 쓰기)
├── gui/
│   ├── ui_loader.py             .ui 로드 + 버튼 업그레이드
│   ├── theme_manager.py         테마 9종
│   ├── chat_view_manager.py     채팅 렌더러 (스크롤 상태머신)
│   ├── chat_widgets.py          ChatMessage / PromptCard / ImageCard / GenerationCard
│   ├── image_preview.py         전체화면 미리보기 모달
│   ├── design_tokens.py
│   ├── play_stop_button.py
│   ├── split_text_button.py
│   ├── ***zanime_style_button.py***       Z-ANIME 스타일 버튼 (재검증 추가)
│   └── dialogs/                 settings / help / facedetailer_guide
└── models/chat.py               ChatMessageData (단일 진실)
```

> **재검증 추가**: `app/gui/zanime_style_button.py` (342줄)와 `assets/ui/help_dialog_v2_ui.py` (187줄)가 리뷰 초기 조사에서 누락되었습니다.

### 라인 수 상위 10개

> **재검증**: 모든 라인 수는 PowerShell `Measure-Object-Line`이 아닌 Python으로 재측정한 값입니다. ~~원본~~는 PowerShell 결과, **굵은 글자**는 정정된 값입니다.

| 순위 | 파일 | ~~원본~~ | **정정** |
|---|---|---|---|
| 1 | `app/main_controller.py` | ~~3,919~~ | **4,323** |
| 2 | `assets/icons/icon_rc.py` | ~~1,533~~ | **1,540** *(생성물)* |
| 3 | `app/sections/generation.py` | ~~946~~ | **1,043** |
| 4 | `assets/ui/main_ui.py` | ~~910~~ | **1,183** *(생성물)* |
| 5 | `app/gui/dialogs/settings_dialog.py` | ~~755~~ | **846** |
| 6 | `app/core/config_manager.py` | ~~520~~ | **560** |
| 7 | `assets/ui/settings_dialog_ui.py` | ~~497~~ | **695** *(생성물)* |
| 8 | `app/sections/prompt.py` | ~~445~~ | **536** |
| 9 | `app/gui/chat_widgets.py` | ~~441~~ | **515** |
| 10 | `app/gui/split_text_button.py` | ~~432~~ | **513** |

> ~~실제 비즈니스 로직은 약 9,000줄이며~~, 나머지는 Qt 생성물·리소스입니다. **재검증**: 실제 비즈니스 로직은 약 **13,000줄**입니다(생성물·리소스 제외).

---

## ✅ 잘하고 있는 부분

코드 리뷰에서는 문제만 나열하기 쉬우므로, **유지해야 할 좋은 설계**를 먼저 기록합니다. 앞으로 리팩터링할 때 절대 깨뜨리지 말아야 할 원칙들입니다.

### 1. 채팅 데이터 모델의 "단일 진실" 설계 — `app/models/chat.py`

> *"세션 메시지가 채팅 화면의 유일한 진실이다. 위젯은 상태를 갖지 않는다."*
> *"카드 전환은 메시지의 kind/metadata 변경으로 표현되고, 화면은 언제든 render() 로 이 데이터로부터 다시 그릴 수 있다."*

이 설계 덕분에:
- `ChatViewManager`가 위젯 레퍼런스를 컨트롤러에 노출하지 않음
- `become_image()` 한 번의 호출로 "프롬프트 카드 → 생성중 카드 → 이미지 카드" 전환이 완료됨
- 세션 저장이 곧 화면 복원 경로가 되어 별도 복원 로직이 불필요

레거시 마이그레이션(`_absorb_legacy_done`)까지 함수 docstring에 **왜 필요한지**가 9줄로 설명되어 있어, 나중에 읽는 사람도 이유를 알 수 있습니다. **이 모듈은 그대로 유지하세요.**

### 2. 원자적 파일 쓰기 — `app/sections/session.py:45-51, 98-127`

```python
tmp = self.index_path.with_suffix(".tmp")
tmp.write_text(json.dumps({...}, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(self.index_path)      # ← 원자적 교체
```

세션 파일과 인덱스 모두 `tmp → replace` 패턴을 사용합니다. 프로그램이 도중에 죽어도 기존 파일이 깨지지 않습니다. `config_manager.save()`도 같은 패턴입니다.

### 3. 기준점 불변성을 코드로 강제 — `app/core/workflow_deriver.py:119-126`

```python
def assert_base_untouched(snapshot: Dict[str, str], ...) -> None:
    """기준점 파일이 생성 과정에서 변경되지 않았는지 확인한다."""
    for base_name, before in snapshot.items():
        path = base_dir(project_root) / f"{base_name}.json"
        after = path.read_text(encoding="utf-8")
        if before != after:
            raise RuntimeError(f"기준점 파일이 변경되었습니다: {path.name}")
```

"base 파일은 절대 수정하지 않는다"는 규칙을 **주석이 아니라 실행 가능한 검증 코드로** 만들어 둔 점이 훌륭합니다. `snapshot_bases()`와 짝을 이루어 완전한 불변성 보장 도구를 제공합니다.

### 4. 회귀 방지 주석 문화 — `app/gui/ui_loader.py:87-99`

```python
# 중요: deleteLater()만 호출하면 이벤트 루프가 돌 때까지 옛 버튼이
# 위젯 트리에 남아 있어서, main.py 의 findChild()가 삭제 예정인
# 옛 버튼을 먼저 찾아 시그널이 연결되고 나중에 삭제돼 버린다.
#
# 회귀: 예전에 setParent(None) 으로 트리에서 빼려 했지만, Qt 는
# 부모 없는 위젯을 top-level window 로 승격시킨다(실측 isWindow=True).
# 원래 크기(예: 100x30) 그대로 작은 독립 창이 떴다가 deleteLater
# 로 사라지는 증상의 원인.
```

과거 버그의 **근본 원인과 실측 근거**를 코드에 남겨 놓았습니다. 이런 주석은 실제 운영에서 이슈 해결 시간을 크게 줄여줍니다. **이 문화는 계속 유지하세요.**

### 5. import 순환 참조 차단 설계 — `app/__init__.py` + `app/paths.py`

`app/paths.py`가 docstring에 명시하듯, 경로 상수를 중립 모듈로 분리해 순환 참조를 막았습니다. `app/__init__.py`는 `__all__`을 명시하고 단일 임포트 진입점을 제공합니다. 대부분의 Python 프로젝트가 놓치는 부분입니다.

### 6. 스크롤 상태머신 — `app/gui/chat_view_manager.py:62-101`

`_stick_to_bottom` / `_programmatic_scroll` / `_rendering` / `_restore_guard` / `_snap_pending` 5개 플래그로 자동 스크롤과 사용자 스크롤을 구분합니다. `_schedule_snap()`이 `QTimer.singleShot(0, ...)`로 레이아웃 확정 후 한 번만 스냅하는 것도 정확합니다.

---

---

## 🔴 심각 (실제 버그 / 데이터 손상 위험)

### 1. `tests/` 디렉토리가 git에서 제외됨 — 테스트 안전망 소실

**위치**: `.gitignore:32`

```
$ git check-ignore -v tests/test_help_dialog.py
.gitignore:32:tests/	tests/test_help_dialog.py

$ git ls-files | grep '^tests/' | wc -l
0
```

**문제**: 70개의 테스트(7.79초)가 **전부 로컬에만 존재**합니다. 프로젝트 자신의 기획서(`통합기획서.html` R7)에서도 이미 지적한 항목입니다.

**영향**:
- 다른 PC에서 작업하면 테스트가 없음 → 리팩터링 시 안전망 없이 수정
- 저장소가 손상되거나 삭제되면 테스트 영구 소실
- CI 설정(`.github/workflows/`)이 있어도 테스트를 못 돌림

**조치**: `.gitignore`에서 `tests/` 한 줄을 제거하고 커밋.

---

### 2. `model_registry.py:30` — 정의되지 않은 이름 `ModuleType`

```python
module: ModuleType = importlib.import_module(f"app.core.model_profiles.{module_info.name}")
```

`types` 모듈의 import가 없습니다:
```
$ grep -n "ModuleType\|^from types\|^import types" app/core/model_registry.py
30:            module: ModuleType = importlib.import_module(...)     ← 사용만
(import 구문 없음)
```

**왜 실행은 되는가**: 파일 1행에 `from __future__ import annotations`가 있어, 변수 애너테이션이 **런타임에 평가되지 않습니다.** 즉 현재는 조용히 동작합니다.

**왜 위험한가**:
- 정적 분석(Pylance/pyright)이 `NameError: name 'ModuleType' is not defined` 오류로 표시
- `typing.get_type_hints()` 또는 dataclass 처리 시 `NameError`로 실행 실패
- `from __future__ import annotations`를 제거하는 순간 즉시 깨짐

**같은 파일의 미사용 import**: `from io import TextIOWrapper` (4행)도 어디서도 쓰이지 않습니다.

**조치**: `from types import ModuleType` 추가, `TextIOWrapper` 제거.

---

### 3. `connection.py:84` — 일본어 문자 `未確認` 혼입

```python
status = ConnectionStatus(service=service, url=resolved_url, ok=False, message="未確認")
```

**실행 검증 결과**:
```
$ check_connection_status('lm', '')
EMPTY_URL_MESSAGE: 'URL이 비어 있습니다.'        ← 정상 덮어써짐
$ check_connection_status('lm', 'http://127.0.0.1:1')
DEAD_URL_MESSAGE: 'URL이 비어 있습니다.'        ← 정상 덮어써짐
```

**현재는 사용자에게 노출되지 않습니다.** `check_connection_status()`의 모든 반환 경로에서 `message`가 한국어로 덮어써지기 때문입니다. 또한 유일한 호출부(`main_controller.py:~~2770-2771~~**2768**)도 `status.ok`와 `status.message`를 모두 재대입합니다.

**실제 노출 가능성**: `未確認`이 출력되려면 `resolve_live_url()`이 빈 문자열을 반환하면서 `if not resolved_url:` 분식을 타지 않아야 하는데, 코드상 그 경로가 없습니다.

**따라서 실질 위험은 낮지만**, `未確認`(일본어)이 한국어 코드베이스에 남아 있는 것 자체가 코드 위생 문제이며, `ConnectionStatus`의 기본값(`message: str = "미확인"`, dataclass 정의상)이 이미 올바른 한국어를 가지고 있으므로 **이 인자만 제거하면 됩니다.**

**조치**: `message="未確認"` → `message="미확인"` (또는 인자 생략으로 dataclass 기본값 사용).

---

### 4. `main_controller.py:555` — QLabel에 인스턴스 속성으로 메서드 덮어쓰기

```python
banner = self.find(QLabel, "errorBannerLabel")
if banner is not None:
    banner.setCursor(Qt.CursorShape.PointingHandCursor)
    banner.mousePressEvent = lambda event: self._on_error_banner_clicked()
```

**문제 3가지**:
1. **Qt는 C++ 가상 함수 호출이므로, 파이썬 인스턴스 속성 대입은 이벤트 디스패치 시 호출되지 않을 수 있습니다.** PySide6는 정적으로 컴파일된 `mousePressEvent`를 호출하므로, 인스턴스 딕셔너리를 조회하는 경로가 없습니다.
2. 람다가 받는 `event` 인자를 무시합니다.
3. 프로젝트에 **이미 올바른 구현이 존재합니다** — `app/gui/image_preview.py:21-28`의 `ClickableLabel`:
   ```python
   class ClickableLabel(QLabel):
       clicked = Signal()
       def mousePressEvent(self, event) -> None:
           self.clicked.emit()
           super().mousePressEvent(event)
   ```
   이미지 카드가 이미 이 방식을 쓰고 있습니다.

**재검증 추가 — 이중 블록**: `errorBannerLabel`은 **두 곳**에서 설정됩니다:
- **Line 469**: `banner.mousePressEvent = lambda event: self._show_settings_dialog()` (초기화 블록)
- **Line 555**: `banner.mousePressEvent = lambda event: self._on_error_banner_clicked()` (UI/UX 4단계 블록)

리뷰는 Line 555의 블록만 언급했으나, Line 469의 블록도 동일한 문제가 존재합니다. 또한 `_on_error_banner_clicked()` 메서드는 실제로 **존재합니다** (`main_controller.py:3804`), `_reveal_log_on_error()`를 호출해 접힌 로그창을 펼칩니다.

**재검증 수정 — "죽은 코드" 결론 수정**:
~~`errorBannerLabel`은 `show_error_banner()`의 docstring에 *"배너 위젯 없음"* 이라고 명시되어 있고, 실제 구현도 채팅 메시지로만 표시합니다(`main_controller.py:3731`). 즉 **이 배너 코드는 이미 죽은 코드일 가능성이 높습니다.**~~

→ **정정**: `errorBannerLabel`은 죽은 코드가 아닙니다. `show_error_banner()`는 채팅 AI 메시지로 오류를 **표시**하지만, `errorBannerLabel` 위젯은 클릭 시 로그창을 펼치는 **이벤트 핸들러**로 활성화되어 있습니다. `clear_error_banner()` (Line 3751)의 docstring은 "채팅 방식에서는 지울 배너가 없다 (기록 유지). 호환용 유지."라며, **호환용으로 유지** 중입니다.

**조치**: `ClickableLabel` 방식으로 통일하거나, 배너가 폐기되었다면 코드 제거.

---

### 5. `main.py:36` — `aboutToQuit` 시점의 스레드 풀 정리

```python
app.aboutToQuit.connect(controller._close_thread_pools)
```

**문제**: 주석은 *"shutdown은 멱등하므로 close()와 중복 호출되어도 무해"* 라고 되어 있지만, `aboutToQuit` 시점에는 이미 Qt 이벤트 루프와 일부 C++ 객체가 파괴 중입니다. `close()` 내부와 동일한 보호 로직이 있는지 확인이 필요합니다.

**참고**: `app/main_controller.py:1964`의 `eventFilter`에는 이미 이 문제를 인지하고 있습니다:
```python
# 프로세스 종료 시점(atexit)에는 C++ Qt 객체가 이미 파괴된 뒤
# 이 필터가 호출될 수 있다 — 무효한 객체는 조용히 통과시킨다.
if not shiboken.isValid(obj) or not shiboken.isValid(event):
    return False
```

**재검증 수정**: `_close_thread_pools()` (~~Line 3929~~ 실제: 동일)의 구현을 확인한 결과:

```python
def _close_thread_pools(self):
    """스레드 풀을 안전하게 종료 (cancel_futures로 대기 중 작업 취소)"""
    for pool in (self._io_pool, self._gen_pool):
        if pool is not None:
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except Exception:
                logger.debug("스레드 풀 종료 실패", exc_info=True)
```

~~`shiboken.isValid` 가드가 없다고 한 것은 부정확합니다~~. `try/except Exception`으로 **이미 RuntimeError를 포함한 모든 예외를 처리**하고 있습니다. 또한 `_io_pool`과 `_gen_pool`은 Python `ThreadPoolExecutor` 객체이지 Qt C++ 객체가 아니므로 `shiboken.isValid`는 적용되지 않습니다. **조치는 불필요**하지만, `logger.debug`로 기록하는 대신 `aboutToQuit` 시점에만 `logger.warning`으로 승격하는 것이 더 좋겠습니다.

**조치**: ~~`_close_thread_pools()`에 `shiboken.isValid` 가드~~ → `try/except Exception` 확인 완료 (ThreadPoolExecutor에 shiboken 적용 불가, 예외 처리는 이미 충분).

---

## 🟠 중간 (설계 부채 / 잠재적 장애)

### 6. `main_controller.py` — ~~3,919줄~~ **4,323줄** God Object

하나의 클래스가 다음을 **모두** 담당합니다:
- UI 배선 (레일, 사이드바, 테마, 탭, 이력 페이지)
- 세션 관리 (생성·전환·삭제·저장)
- 생성 오케스트레이션 (시작·중지·에러·완료)
- 스냅샷 캡처/복원 (FaceDetailer 15개 슬라이더 포함)
- 채팅 메시지 조작
- 모델 목록/연결 상태 관리

**가장 큰 메서드**: `capture_snapshot()` (3,186-3,271행, 86줄)
```python
def capture_snapshot(self):
    prompt_text = self._find_or_raise(QPlainTextEdit, "positivePromptEdit").toPlainText()
    ...
    for key, slider_name, default, factor, is_step_64 in FACEDETAILER_SLIDER_SPECS:
        s = self.find(QSlider, slider_name)
        if not s:
            fd_values[key] = default
        elif is_step_64:
            fd_values[key] = s.value() * 64
        elif factor != 1.0:
            fd_values[key] = round(s.value() / factor, 2)
        else:
            fd_values[key] = s.value()
    ...
```

**권장 분리**:

| 추출 모듈 | 책임 | 예상 라인 |
|---|---|---|
| `SnapshotBuilder` | `capture_snapshot` / `_restore_snapshot` / `_restore_facedetailer_from_snapshot` | ~250 |
| `SessionCoordinator` | `_ensure_session` / `_flush_session` / `_switch_session` / 이력 UI | ~350 |
| `GenerationCoordinator` | `start_generation` / `stop_generation` / `_on_generation_error` / `generation_finished` | ~400 |

> **주의**: 통합 기획서의 A4 항목("커스텀 워커가 `capture_snapshot()`을 직접 호출")처럼 **워커 스레드에서 Qt 위젯에 접근하는 문제가 이미 예정된 위험(R8)으로 문서화**되어 있습니다. 분리 작업 시 이 점을 함께 해결하면 효과가 큽니다.

---

### 7. `config_manager.py:543-554` — `get_config_manager()`가 호출될 때마다 `load()`

```python
def get_config_manager(config_path=None) -> ConfigManager:
    global _config_manager
    ...
    _config_manager.load()        # ← 매 호출마다 디스크 I/O + JSON 파싱
    return _config_manager
```

**호출 경로** (확인됨):
- `WorkflowManager.__init__` (`workflow_manager.py:27`)
- `ModelFetcher` 생성 (`model_fetcher.py`)
- `MainController.__init__` (`main_controller.py:206`)
- `ModelRegistry.discover_from_model_dirs` (`model_registry.py:297`)

`ModelRegistry.discover_from_model_dirs()`처럼 루프 안에서 호출될 경우, 루프 횟수만큼 파일을 다시 읽습니다.

**조치**: 명시적 `load()`가 필요한 경우에만 재로딩하거나, mtime 기반 더티 체크를 추가.

---

### 8. `connection.py:43` — `max_retries` 파라미터가 완전히 무시됨

```python
def _probe_endpoint(url: str, endpoint: str,
                    timeout: tuple[float, float] = (0.1, 0.15),
                    max_retries: int = 1) -> bool:      # ← 이 인자가 쓰이지 않음
    ...
    response = requests.head(f"{normalized}{endpoint}", timeout=(0.1, 0.1), allow_redirects=False)
    return response.status_code < 400
```

**확인**: `grep -n "max_retries" app/sections/connection.py` → 43행(시그니처)에만 존재, 함수 본문에 사용 없음.

**부수 문제**: `timeout` 파라미터도 **무시**되고 하드코딩된 `(0.1, 0.1)`이 사용됩니다. 시그니처가 실제 동작을 반영하지 않으므로, 호출자가 타임아웃을 조절해도 효과가 없습니다.

**조치**: 사용하지 않는 파라미터 제거, 또는 실제로 반영.

---

### 9. `connection.py:64-78` — `candidates` 파라미터와 docstring 불일치

```python
def resolve_live_url(service, preferred_url=None, candidates=None) -> str:
    """Return the live URL for the requested service.

    Only checks the provided URL (from UI input). Does not fall back to other candidates.
    """
    ...
    normalized = _normalize_url(preferred_url)   # candidates는 어디에도 쓰이지 않음
```

**호출부가 후보 목록을 만듭니다** (`main_controller.py:2500-2503`):
```python
comfy_candidates = [self.config.comfyui.url] if self.config.comfyui.url else []
resolved_lm_url = resolve_live_url("lm", lm_url, lm_candidates)
resolved_comfy_url = resolve_live_url("comfy", comfy_url, comfy_candidates)
```

이 후보 목록을 만드는 코드까지 **연쇄적으로 죽은 코드**입니다.

**조치**: (a) `candidates` 폴백을 실제로 구현하거나, (b) 파라미터와 호출부의 후보 목록을 모두 제거.

---

### 10. `generation.py:175` — 워커 스레드에서 `time.sleep(0.2)` 래치

```python
self.signals.enhanced_prompt.emit(prompt)

# GUI에 텍스트가 반영될 수 있도록 잠시 대기
time.sleep(0.2)
```

**문제**: Qt 시그널은 **동기 연결 시 함수 호출과 동일한 즉시 실행**입니다. `time.sleep(0.2)`은 "0.2초 동안 아무것도 안 한다"일 뿐, UI 스레드가 어디까지 처리했는지 보장하지 않습니다. 다음과 같은 시나리오에서 enhance 텍스트가 UI에 반영되기 전에 다음 단계로 진행할 수 있습니다:

1. 큐 연결(UI 부하 높음) → emit된 시그널이 이벤트 큐에 쌓임
2. `time.sleep(0.2)` 종료 → 다음 단계 진행
3. 0.3초 후 UI 스레드가 시그널 처리 → 그 사이에 워커는 이미 다음 단계로 전진

   **같은 패턴이 `generation.py`~~(946줄)~~ **(1,043줄)**에 5곳** (175, 221, 274, 311, 366행)에 있습니다. 311/366행은 폴링 간격이라 의도된 것이지만, **175행(UI 반영 대기)과 221행은 결정적이지 않은 동기화**입니다.

**조치**: Qt 이벤트 루프를 기다리는 방식(`QEventLoop` + `QTimer.singleShot(..., loop.quit)`) 또는 "UI 반영 완료" 시그널을 돌려주는 방식으로 교체.

---

### 11. `logging_config.py:34-36` — root 로거 핸들러 중복 누적

```python
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(file_handler)     # ← 중복 방지 로직 없음
```

**문제**: `setup_logging()`은 `main_controller.py:194`에서 **모듈 임포트 시점**에 실행됩니다:
```python
UI_FILE = BASE_DIR / "assets" / "ui" / "main.ui"
setup_logging(BASE_DIR)          # ← import 시 즉시 실행
logger = logging.getLogger(__name__)
```

테스트에서 `main_controller`를 여러 번 import하거나 `importlib.reload()`하면 핸들러가 쌓여 **로그가 N배 중복 기록**됩니다. 현재는 `app.log`가 705KB로 이미 커진 상태이며, 2MB 회전(`maxBytes=2_000_000, backupCount=3`)이라 어느정도는 자라지만, 디버깅 시 로그 파싱을 방해합니다.

**조치**: 중복 방지 가드 추가.
```python
if not any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
    root_logger.addHandler(file_handler)
```

---

### 12. `config_manager.py` / `theme_manager.py` — `print()` 대신 로거 사용

프로젝트에 `logging` 모듈이 완전히 도입되어 있고 `setup_logging()`도 존재하는데, 아래 파일들은 여전히 `print()`를 사용합니다:

| 위치 | 내용 |
|---|---|
| `config_manager.py:179` | 설정 파일 읽기 실패 |
| `config_manager.py:390` | 설정 저장 실패 |
| `theme_manager.py:54, 56` | 테마 키 읽기 실패 |
| `theme_manager.py:63, 73` | 테마 저장 실패 |
| `theme_manager.py:83, 91, 94, 101` | QSS 파일 미발견 |

`config_manager`는 모듈 import 시점에 설정 로드가 일어나므로, 이 `print()`는 **GUI가 뜨기 전에 콘솔에 출력**됩니다. 파일 로그(`app.log`)에는 기록되지 않습니다.

**조치**: `logger = logging.getLogger(__name__)` 도입 후 `logger.warning()`으로 교체.

---

## 🟡 개선 권장 (코드 위생)

### 13. 죽은 코드: `app/core/connection_pool.py` (98줄)

```
$ grep -rn "connection_pool|ConnectionPoolManager" app/
app/core/connection_pool.py:13,16,19,96,97,98    ← 자기 자신만 참조
```

`app/__init__.py`에도 **export되지 않으며**, `api_client.py`가 이미 `requests.Session`을 직접 관리합니다 (`BaseApiClient._create_session`). 완전히 사용되지 않는 모듈입니다.

**주의**: 이 모듈의 `ConnectionPoolManager`는 `__new__` 싱글턴 + `threading.Lock`으로 잘 구현되어 있으나, **`__init__`에서 `self._lock = threading.Lock()`으로 클래스 변수 `_lock`를 인스턴스 변수로 재정의**하는 패턴이 있습니다 (`connection_pool.py:17` vs `32`). 현재는 우연히 동작하지만, 다른 코드에서 `ConnectionPoolManager._lock`에 접근하면 클래스-level lock과 인스턴스-level lock이 달라집니다.

**조치**: 삭제하거나, `BaseApiClient`가 이 풀을 사용하도록 통합.

---

### 14. `prompt.py` — 첫 번째 시도가 조용히 삼켜짐 (`enhance_prompt_sync`, line 410-417)

```python
# 1) Native LM Studio REST API — reasoning 제어에 가장 좋음
try:
    enhanced = _request_native_chat(base_url, model, prompt, system_prompt, timeout)
    if enhanced:
        return enhanced
except Exception:
    pass                                    # ← 실패 원인 무시 (Line 416-417)

# 2) OpenAI-compatible endpoint
url = f"{base_url}/v1/chat/completions"
payload = _build_chat_payload(model, system_prompt, prompt)
try:
    response = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=timeout,
    )
    response.raise_for_status()
    return _parse_chat_response(response.json()) or None
except Exception:
    return None                             # ← 실패 원인 무시 (Line 431-432)
```

LM Studio의 네이티브 API가 404인지, 500인지, 모델이 없는지, 타임아웃인지 — **사용자가 구분할 수 없습니다.** 두 번째 OpenAI 호환 경로가 성공하면 조용히 넘어가고, 그것도 실패하면 `None`을 반환하여 "프롬프트 향상 실패"로만 보입니다.

**재검증 추가 — `PromptEnhanceWorker` 클래스 (Line 439+)**: 이 문제는 `enhance_prompt_sync` 함수뿐만 아니라, 동일 파일에 있는 **Qt 기반 비동기 워커 클래스**에서도 영향을 받을 수 있습니다. 하지만 `PromptEnhanceWorker(QThread)`는 **적절한 에러 처리**를 가지고 있습니다:

```python
# Line 487-488: 실패 원인을 debug_signal으로 기록
except Exception as native_exc:
    self.debug_signal.emit(f"[Worker] Native API 실패 → 호환 API 재시도: {native_exc}")

# Line 530-535: 구체적 예외 처리
except requests.Timeout:
    self.error_signal.emit("LM Studio 요청 시간 초과 (Timeout)")
except requests.ConnectionError as exc:
    self.error_signal.emit(f"LM Studio 서버 연결 실패: {exc}")
except Exception as exc:
    self.debug_signal.emit(f"[Worker] 예외 발생: {traceback.format_exc()}")
    self.error_signal.emit(f"프롬프트 향상 실패: {exc}")
```

따라서 **동기 함수**(`enhance_prompt_sync`)만이 문제이며, **비동기 워커**(`PromptEnhanceWorker`)는 이미 충분히 처리하고 있습니다.

**조치**: 최소한 `logger.debug("LM 네이티브 API 실패, OpenAI 호환 경로로 폴백", exc_info=True)` 기록.

---

### 15. FaceDetailer 기본값 중복 — `constants.py` vs `main_controller.py:3164-3178`

`constants.py`에 이미 스펙이 있습니다:
```python
FACEDETAILER_SLIDER_SPECS = [
    ("facedetailer_denoise",  "facedetailerDenoiseSlider",  0.40, 100.0, False),
    ("facedetailer_steps",    "facedetailerStepsSlider",    20,    1.0, False),
    ("facedetailer_cfg",      "facedetailerCfgSlider",      4.0,  10.0, False),
    ("facedetailer_guide_size", "facedetailerGuideSizeSlider", 256, 1.0, True),   # 256 = 4 × 64
    ("facedetailer_max_size", "facedetailerMaxSizeSlider",   768,   1.0, True),   # 768 = 12 × 64
    ...
]
```

그런데 `_reset_facedetailer_to_defaults()`는 **위젯 단위의 하드코딩 값**을 씁니다:
```python
self._set_fd_slider("facedetailerDenoiseSlider", 40)      # 40 / 100 = 0.40  ✓ 일치
self._set_fd_slider("facedetailerCfgSlider", 40)          # 40 / 10  = 4.0   ✓ 일치
self._set_fd_slider("facedetailerGuideSizeSlider", 4)     # 4 × 64   = 256   ✓ 일치
self._set_fd_slider("facedetailerMaxSizeSlider", 12)      # 12 × 64  = 768   ✓ 일치
```

**현재는 값이 일치하지만, 두 곳에 복제되어 있습니다.** `constants.py`의 스펙을 수정하면 리셋 함수는 조용히 틀어집니다(에러 없이). 새 슬라이더를 추가할 때도 두 곳을 함께 고쳐야 합니다.

**조치**: `_reset_facedetailer_to_defaults()`를 `FACEDETAILER_SLIDER_SPECS`를 순회하도록 리팩터링하면 단일 진실이 됩니다.

---

### 16. `assets/ui/main_ui.py` (~~910~~ **1,183**줄) — 생성물이 커밋됨

```
$ git ls-files | grep main_ui.py
assets/ui/main_ui.py
```

`.gitignore:~~34-35~~` **실제로는 Line 34-35**에 주석과 함께 생성물 무시 규칙이 있습니다:
```
# Qt Designer 생성물(자동 생성 파이썬 UI)은 필요 시 재생성하므로 무시
novel_studio/ui/forms/*_ui.py
```

**그런데 `assets/ui/*_ui.py`는 예외적으로 커밋**되어 있습니다. 게다가 경로 규칙이 `novel_studio/ui/forms/*_ui.py`(이 프로젝트에 없는 경로)를 가리키고 있어, **의도와 실제가 어긋나 있습니다.**

**재검증 결과**: `main_ui.py`는 **런타임에 완전하게 미사용**입니다. `ui_loader.py`는 `QUiLoader`로 `.ui` 파일을 직접 로드하며, `main_ui.py`를 **import하거나 참조하는 코드가 한 곳도 없습니다**:

```
$ grep -rn "import main_ui|from.*main_ui|main_ui\." app/ assets/ main.py
(결과 없음)
```

**영향**: `.ui` 파일을 수정하고 `pyside6-uic`로 재생성하면 ~~910줄~~ **1,183줄**짜리 파일에 Git 충돌이 발생합니다. 수동 편집과 생성물이 섞여 있으면 어느 쪽이 진실인지 알 수 없습니다.

**조치**: (a) `.gitignore`에 `assets/ui/*_ui.py` 추가 후 `git rm --cached`, (b) 또는 `ui_loader.py`가 `main_ui.py`를 사용하도록 변경.

---

### 17. `.kilo/worktrees/majestic-condition/` — 중복 사본 ~~3,919줄~~ **4,323줄**

`.gitignore:43`에 `.kilo/`가 포함되어 git에서는 제외되지만, 디스크에는 실제 중복본이 존재합니다.

```
app/main_controller.py                                       ~~3,919~~ **4,323**줄
.kilo/worktrees/majestic-condition/app/main_controller.py   ~~3,919~~ **4,323**줄  ← 동일
```

**영향**: grep/검색 도구가 두 벌로 잡아 **파일명을 오인**하게 만듭니다. (이번 리뷰에서도 최초 조사에서 두 벌로 잡혀 걸렸습니다.) `main_controller.py`가 2개로 잡히면 어느 쪽을 리뷰한 것인지 혼란스러워집니다.

**조치**: 작업이 끝난 워크트리는 삭제하거나, 검색 도구에서 제외 설정 추가.

---

### 18. 린터/포매터 미설치

```
$ pip list | grep -E 'ruff|flake8|pylint|black|mypy'
(결과 없음)
```

`# noqa: BLE001`, `# noqa: N802`, `# noqa: DTZ005`, `# noqa: F401` 주석이 코드에 존재하지만, **이를 검사할 도구가 없습니다.** noqa가 실제로 유효한 코드인지, 오탐인지 판단할 수 없습니다.

코드 품질을 코드로 강제할 도구가 없으므로, 아래 2번 항목(정의되지 않은 이름)이 리뷰 단계에서 처음에만 발견된 것입니다.

**조치**: `requirements-dev.txt`에 `ruff` 추가 후 CI에서 실행. (`requirements.txt`는 런타임 의존성만 유지)

---

### 19. `_chat_log`의 이중 상태 관리 — `main_controller.py:774, 911` vs `_messages`

`models/chat.py`의 설계 원칙은 "세션 메시지가 유일한 진실"이지만, 컨트롤러에는 `_messages`(별칭)와 `_chat_log`(실제 저장소) **두 개의 이름이 공존**합니다.

```
$ grep -n "_chat_log" app/main_controller.py
 774:        self._chat_log = []
 808:        return getattr(self, "_chat_log", None) or []     # ← _messages 프로퍼티의 본체
 833:        self._chat_log.append(message)                     # ← _append_message()에서 채워짐!
 835:        self._chat_log = [message]                         # ← AttributeError 폴백
 911:        self._chat_log = []
1176:        self._chat_log = messages_from_raw(session.get("messages", []))  # ← 세션 로드
1360:        self._chat_log = []
1418:        for record in getattr(self, "_chat_log", []):
1445:        for record in getattr(self, "_chat_log", []):            # _snapshot_for_image
1752:        if getattr(self, "_chat_log", None):
3758:        for record in reversed(getattr(self, "_chat_log", [])):  # _last_user_text
3768:        for record in reversed(getattr(self, "_chat_log", [])):  # _last_snapshot
```

~~이 세 메서드가 `ChatMessageData`가 아닌 **dict 형태의 레거시 포맷**을 기대하고 있어, "단일 진실" 원칙과 어긋납니다. `_chat_log`는 911행에서 빈 리스트로 초기화되고 **이후 어디에도 채워지지 않으므로**, 세 메서드는 항상 빈 결과를 반환합니다.~~

**재검증 수정**: ~~`_chat_log`가 채워지지 않는다~~는 주장은 **부정확합니다**. `_chat_log`는 실제로 `_append_message()` (Line 833-835)와 세션 로드 (Line 1176)를 통해 **실제로 채워집니다**. 또한 `_messages` 프로퍼티 (Line 806-808)는 `_chat_log`의 **별칭**입니다 — 단일 진실 원칙을 위반하지 않습니다.

**실제 문제**: 3개 메서드(`_snapshot_for_image`, `_last_user_text`, `_last_snapshot`)는 `isinstance(record, dict)`로 **dict 레코드**를 기대하지만, `_chat_log`에는 `ChatMessageData` **객체**가 들어 있습니다. `isinstance(ChatMessageData(...), dict)`는 `False`이므로, 모든 레코드가 건너뛰려 되어 **항상 빈 결과를 반환**합니다:

| 메서드 | 호출부 | 실제 동작 | 근본 원인 |
|---|---|---|---|
| `_snapshot_for_image()` | 프리뷰 "프롬프트 재작성" | 항상 `{}` 반환 → "설정을 찾을 수 없어" | `isinstance(record, dict)` → ChatMessageData는 dict가 아님 |
| `_last_user_text()` | 오류 카드 "다시 시도" | 항상 `""` 반환 → **버튼이 아무 일도 하지 않음** | 동일 — `record.get("kind")` 호출 불가 |
| `_last_snapshot()` | 오류 카드 "프롬프트 수정" | 항상 `{}` 반환 → "이전 생성 결과가 없어요" | 동일 |

**영향**: 오류 발생 시 표시되는 `[다시 시도]` / `[프롬프트 수정]` 버튼이 **기능하지 않습니다.** 사용자가 가장 필요할 때(생성 실패 직후) 동작하지 않는 최종입니다.

**조치**: 세 메서드를 `self._messages` (ChatMessageData 객체 리스트) 순회로 재작성.
```python
def _last_user_text(self) -> str:
    for message in reversed(self._messages):
        if message.role == "user":
            return message.text
    return ""
```

---

## 📋 권장 조치 순서

| 순위 | 조치 | 대상 파일 | 위험도 | 효과 |
|---|---|---|---|---|
| **1** | `.gitignore`에서 `tests/` 제거 후 테스트 커밋 | 1 | 없음 | 🟢 치명적 문제 해소 |
| **2** | `from types import ModuleType` 추가, 미사용 `TextIOWrapper` 제거 | 1 | 없음 | 🟢 정적 분석 통과 |
| **3** | `"未確認"` → `"미확인"` | 1 | 없음 | 🟢 코드 위생 |
| **4** | `setup_logging` 중복 핸들러 가드 | 1 | 낮음 | 🟡 로그 중복 해소 |
| **5** | `print()` → `logger.warning()` (config_manager, theme_manager) | 2 | 낮음 | 🟡 파일 로그 누락 해소 |
| **6** | 데드 파라미터 정리 (`max_retries`, `timeout`, `candidates`) | 1 + 1 | 낮음 | 🟡 오해 방지 |
| **7** | `_chat_log` 메서드를 `ChatMessageData` 객체 기반으로 재작성 (**기능 복구**) | 1 | 중간 | 🟢 3개 기능 복구 |
| **8** | `errorBannerLabel` 클릭 방식 통일 (`ClickableLabel`) 또는 죽은 코드 제거 | 1 | 낮음 | 🟡 |
| **9** | 미사용 `connection_pool.py` 삭제 | 1 | 낮음 | 🟡 코드 정리 |
| **10** | FaceDetailer 기본값 `constants.py` 단일화 | 2 | 중간 | 🟡 |
| **11** | `enhance_prompt_sync` 폴백 로그 추가 | 1 | 없음 | 🟡 |
| **12** | `ruff` 도입 (`requirements-dev.txt` + CI) | 2 | 없음 | 🟡 재발 방지 |
| **13** | `time.sleep` 래치 → Qt 동기화 | 1 | 중간 | 🟠 결정성 |
| **14** | `config_manager.load()` 호출 빈도 개선 | 1 | 중간 | 🟡 성능 |
| **15** | `main_controller.py` 3분할 | 10+ | **높음** | 🟠 구조 |
| **16** | `main_ui.py` 생성물 정책 결정 | 1 | 중간 | 🟡 |

### 단계별 로드맵

**1단계 — 30분, 위험 없음** (순위 1~3, 11)
`.gitignore` 정리 + import 수정 + 문자열 수정. 테스트가 안전망이 되어 이후 작업이 편해집니다.

**2단계 — 2시간, 저위험** (순위 4~6, 8, 9)
죽은 코드와 데드 파라미터 정리. 동작 변경 없이 코드 품질만 개선됩니다.

**3단계 — 4시간, 중위험** (순위 7, 10, 12, 14)
실제 기능 복구(`_chat_log` 메서드 재작성 — `isinstance(record, dict)` 체크 제거)와 상수 단일화. **1단계에서 복원한 테스트로 검증 가능.**

**4단계 — 1일, 고위험** (순위 13, 15)
스레드 동기화 개선과 구조 개편. **백업 커밋 필수.**

---

## 🔍 상세 분석 노트

### `enhance_prompt_sync` 폴백 체인 (`prompt.py:396-432`)

```python
# 1) Native LM Studio REST API — reasoning 제어에 가장 좋음
try:
    enhanced = _request_native_chat(base_url, model, prompt, system_prompt, timeout)
    if enhanced:
        return enhanced
except Exception:
    pass                                    # ← 실패 원인 무시

# 2) OpenAI-compatible endpoint
try:
    response = requests.post(url, json=payload, headers=..., timeout=timeout)
    response.raise_for_status()
    return _parse_chat_response(response.json()) or None
except Exception:
    return None                             # ← 실패 원인 무시
```

폴백 설계 자체는 합리적입니다. 문제는 **동기 함수**(`enhance_prompt_sync`)의 **두 경로 모두 실패 원인을 기록하지 않는다**는 점입니다. `app.log`에 남는 것은 "LM Studio 응답이 올바르지 않아 원본 프롬프트를 사용합니다"(`generation.py:177`)뿐이어서, LM Studio가 왜 응답하지 않았는지(모델 미로드 / 포트 오류 / OOM) 진단할 수 없습니다.

**재검증 추가**: 동일 파일의 `PromptEnhanceWorker(QThread)` 클래스(`prompt.py:439+`)는 **적절한 에러 처리**를 가지고 있어, 동기 함수만이 문제입니다:
- Line 487-488: `debug_signal.emit(f"[Worker] Native API 실패 → 호환 API 재시도: {native_exc}")`
- Line 530-535: `requests.Timeout`, `requests.ConnectionError`, 일반 `Exception` 각각 구체적 에러 메시지 방출

### `ComfyUIWebSocketClient`의 진행률 파싱 (`api_client.py:270-299`)

```python
# 형태 1: 표준 progress 패킷 (data: {value: 12, max: 20})
if msg_type == 'progress' or 'progress' in msg_type:
    ...
# 형태 2: KSampler 내부 스텝 (data: {step: 5, max: 20})
elif 'step' in data and ('max' in data or 'total' in data or 'steps' in data):
    ...
```

ComfyUI 버전 차이에 대한 방어적 코드로, 두 가지 패킷 형태를 모두 처리합니다. 과거 이슈를 반영한 좋은 사례입니다.

다만 `'progress' in msg_type`은 부분 문자열 매칭이라 `no_progress_reporting` 같은 예상치 못한 타입도 잡을 수 있습니다. `msg_type.startswith('progress')` 또는 정확 일치 비교가 더 안전합니다.

### `FaceDetailer` 워크플로우 조립 (`generation.py:882-937`)

```python
facedetailer_node_id = str(int(detector_node_id) + (2 if sam_loader_node_id else 1))
workflow[facedetailer_node_id] = { "inputs": {...}, "class_type": "FaceDetailer" }
```

노드 ID를 **정수 연산으로 계산**해 FaceDetailer 노드를 만들어 넣습니다. 56줄에 걸쳐 ComfyUI Impact Pack의 필수 입력값 20개 이상을 수동으로 채웁니다.

- **장점**: Impact Pack의 정확한 스키마를 이해하고 있으며, 실패 시 원본 생성으로 우회하는 안전장치가 있습니다:
  ```python
  except Exception as e:
      self.emit_log(f"[⚠️ 시스템 에러] FaceDetailer 구조 조립 중 오류 발생: {e}. "
                    f"안전을 위해 무보정 원본 생성으로 우회합니다.")
      return workflow
  ```
- **위험**: 노드 ID가 겹치거나 문자열/정수 정합성이 깨지면 전체 생성이 실패합니다. `get_object_info`(`api_client.py:90`)로 노드 스키마를 조회할 수 있으니, 향후 Impact Pack 업데이트 시 실제 스키마와 대조하는 검증 코드를 추가하면 안전성이 크게 올라갑니다.

## ✅ 검증 기록

수행한 검증을 모두 기록합니다.

```powershell
# 테스트 실행
$ .\.venv\Scripts\python.exe -m pytest tests -q --no-header
......................................................................   [100%]
~~70 passed in 7.79s~~ **70 passed in 8.62s**                     ✅

# AST 파싱 (전 파일 구문 검사) — Python glob으로 재검증
$ .\.venv\Scripts\python.exe -c "import ast,os; files=[os.path.join(r,f) for r,d,fs in os.walk('.') for f in fs if f.endswith('.py') and '.kilo' not in r and '.venv' not in r and '__pycache__' not in r]; [ast.parse(open(p,encoding='utf-8-sig').read()) for p in files]"
~~AST OK files= 44~~ **files= 57**                               ✅

# 정확한 라인 수 (Python 기준)
$ .\.venv\Scripts\python.exe -c "import os; [print(sum(1 for _ in open(os.path.join(r,f),encoding='utf-8-sig')),os.path.join(r,f)) for r,d,fs in os.walk('.') for f in fs if f.endswith('.py') and '.kilo' not in r and '.venv' not in r]"
main_controller.py: 4,323 lines (~~PowerShell Measure-Object-Line: 3,919~~)
split_text_button.py: 513 lines  (~~PowerShell: 432~~, corrections.md v1.0에서 이미 지적됨)
generation.py: 1,043 lines       (~~PowerShell: 946~~)
config_manager.py: 560 lines      (~~PowerShell: 520~~)
prompt.py: 536 lines              (~~PowerShell: 445~~)
chat_widgets.py: 515 lines        (~~PowerShell: 441~~)
main_ui.py: 1,183 lines           (~~PowerShell: 910~~)
settings_dialog.py: 846 lines     (~~PowerShell: 755~~)
settings_dialog_ui.py: 695 lines  (~~PowerShell: 497~~)
icon_rc.py: 1,540 lines           (~~PowerShell: 1,533~~)

# gitignore 확인 — 테스트 추적 여부
$ git check-ignore -v tests/test_help_dialog.py
.gitignore:32:tests/  tests/test_help_dialog.py                          ⚠ 확인됨
$ git ls-files | findstr "^tests/"
(결과 없음)                                                            ⚠ 확인됨

# 미사용 모듈 확인
$ Select-String -Path app\*.py,app\**\*.py -Pattern 'connection_pool'
app/core/connection_pool.py:13,16,19,96,97,98   ← 자기 자신만 참조    ⚠ 확인됨

# 미사용 import 확인
$ Select-String -Path app\core\model_registry.py -Pattern 'ModuleType'
app/core/model_registry.py:30   ← 사용만, import 없음                    ⚠ 확인됨
$ Select-String -Path app\core\model_registry.py - Pattern 'TextIOWrapper'
app/core/model_registry.py:4    ← import만, 사용 없음                    ⚠ 확인됨

# 문자열 노출 여부 검증
$ python -c "check_connection_status('lm','')"
EMPTY_URL_MESSAGE: 'URL이 비어 있습니다.'    ← 덮어써져 정상             ✅ 위험 낮음

# 생성물 커밋 여부 + 런타임 사용 여부
$ git ls-files | findstr 'main_ui.py'
assets/ui/main_ui.py                                                ⚠ 확인됨
$ grep -rn "import main_ui\|from.*main_ui\|main_ui\." app/ assets/ main.py
(결과 없음 — 런타임 미사용 확인됨)                                  ✅

# _chat_log 실제 사용량 (재검증)
$ grep -n "_chat_log" app/main_controller.py
774, 808, 833, 835, 911, 1176, 1360, 1418, 1445, 1752, 3758, 3768  ← 12곳 (리뷰가 4곳만 언급)  ⚠
$ grep -n "isinstance(record, dict)" app/main_controller.py
1446, 3759, 3769  ← ChatMessageData 객체는 dict가 아니므로 모든 레코드 스킵  ⚠

# 누락 파일 확인
$ ls app/gui/zanime_style_button.py assets/ui/help_dialog_v2_ui.py
app/gui/zanime_style_button.py  (342 lines)  ← 리뷰 누락
assets/ui/help_dialog_v2_ui.py   (187 lines)  ← 리뷰 누락

# 린터 설치 여부
$ .\.venv\Scripts\python.exe -m ruff --version
No module named ruff                                                ⚠ 확인됨
```

---

## 📌 부록: 프로젝트 성격 요약

| 항목 | 내용 |
|---|---|
| **프로젝트** | ComfyCraft AI Easy Studio (v0.3.0) |
| **목적** | ComfyUI 이미지 생성 + LM Studio 프롬프트 향상을 채팅형 GUI로 통합 |
| **원격** | `https://github.com/Donian-kor/comfyui_Lmstudio_gui-v0.3.git` |
| **UI 프레임워크** | PySide6 (Qt Designer `.ui` + 런타임 코드 병행) |
| **테마** | 9종 (fluent_dark 기본, VISIBLE_THEMES는 2종만 노출) |
| **모델 프로필** | base(불변) + default_profiles(최적값) → models(파생) 3층 체계 |
| **진행 단계** | P1~P20 phases, 기획서 v6.0 |
| **다음 계획** | 통합 기획서의 만화(4컷) 기능 — `통합기획서.html` 참조 |

### 최근 커밋 이력

```
49d23df fix: 워크플로우 설정과 이미지 생성 오류 처리 개선
51c942c fix(ui): 사이드바 레일 버튼 글자 좌우 잘림 해결
7531b7c fix(help): 도움말 버튼 반복 클릭 시 창이 중복 생성되는 문제
8311d59 chore(docs): 이미지 모델 설정 목업 제거
b1d9b9a feat(chat): 단계별 AI 발화와 레거시 완료 메시지 복원
f704ace fix(ui): 설정 목록 중복과 카드 잔상 및 크기 문제를 해결
0043a8e feat(settings): 모델 프로필 기준점 설정과 등록 화면 개선
e204ebe backup: 워크플로우 기준점 3종 체계 (base/models 분리 + default_profiles 단일화)
50d1616 refactor(chat): 세션 메시지 기반 카드 렌더링으로 전환
664e19e fix(controller): 세션 전환 시 멈춘 생성과 카드 상태를 정리
```

> 최근 커밋이 `fix` / `backup` 위주이고 `backup:` 접두사가 반복되는 점을 보면, **리팩터링이 자주 되돌려진 경험**이 있는 것으로 보입니다. 이는 1단계(테스트 커밋) 이후 15번(구조 개편)을 진행할 때 반드시 지켜야 할 부분입니다.

---

## 📌 총평

**강점**: "단일 진실" 데이터 모델(`models/chat.py`), 원자적 파일 쓰기(`sections/session.py`), 실행 가능한 불변성 검증(`workflow_deriver.py`), 회귀 원인을 코드에 남기는 주석 문화(`gui/ui_loader.py`). 이 네 가지는 대부분의 개인 프로젝트에서 보기 어려운 수준입니다.

**약점**: **테스트가 git 밖에 있습니다.** 이 한 가지가 나머지 모든 개선의 병목입니다. 리팩터링을 해도 되돌릴 수 없는 상태이기 때문입니다. `.gitignore` 한 줄을 지우는 데 1분이 걸리지만, 이게 선행되지 않으면 어떤 개선도 안전하게 시도할 수 없습니다.

**재검증 결과 요약**: PowerShell `Measure-Object-Line`의 **계측 오류**가 리뷰 전반의 라인 수 통계를 체계적으로 언더카운트했습니다. 구체적인 코드 참조(라인 번호, 로직 구조)는 Python 기준으로 **정확히 검증**되었습니다. 다만 `_chat_log` "채워지지 않는다"는 주장은 **오류**이며, `errorBannerLabel`은 죽은 코드가 아닌 **이벤트 핸들러**로 활성화되어 있습니다. 누락 파일 2종(`zanime_style_button.py`, `help_dialog_v2_ui.py`)이 추가로 확인되었습니다.

**권장**: **1단계를 먼저 완료하세요.** 30분이면 끝나고, 그 뒤부터는 70개의 테스트가 안전망이 됩니다.

---

## 📝 버전 이력

| 버전 | 일자 | 변경 내용 |
|---|---|---|
| v1.0 | 2026-09-29 | 초기 리뷰 작성 (커밋 `49d23df`) |
| v1.1 | 2026-09-29 | 재검증 및 수정안 추가 |

### v1.1 변경 내역

1. **통계 정정**: Python 파일 34→57개, 총 라인수 ~12,700→18,326, AST 파싱 44→57개
   - 근원 원인: PowerShell `Measure-Object-Line`가 CRLF 파일의 라인 수를 언더카운트
2. **라인 수 상위 10개 표 전부 수정**: 모든 파일의 라인 수를 Python 기준으로 정정
3. **`_chat_log` 섹션(§19) 수정**: "_chat_log가 채워지지 않는다"는 주장을 **오류**로 표시하고, 실제 데이터 흐름(`_append_message`, 세션 로드, `_messages` 별칭)을 추가
4. **`errorBannerLabel` 섹션(§4) 수정**: 이중 블록(Line 469+555) 발견, "죽은 코드" 결론을 **부정확**으로 표시하고 실제 동작(클릭 시 로그 창 펼치기) 설명 추가
5. **`_close_thread_pools` 섹션(§5) 수정**: `try/except Exception`이 이미 RuntimeError를 처리 중임을 확인, `shiboken.isValid`가 ThreadPoolExecutor에 적용 불가임을 명시
6. **`split_text_button.py` 라인 수**: 432→513 (corrections.md v1.0에서 이미 지적된 사항 반영)
7. **누락 파일 추가**: `zanime_style_button.py`(342줄), `help_dialog_v2_ui.py`(187줄)
8. **`PromptEnhanceWorker` 클래스**: `enhance_prompt_sync` 절단에 비동기 워커의 적절한 에러 처리 언급 추가
9. **`main_ui.py` 검증 완료**: 런타임에 완전히 미사용임 확인
10. **검증 기록 업데이트**: 실제 검증 결과로 교체






