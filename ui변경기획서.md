# UI 변경기획서 v2.0 — Google Material Design 3 적용

- **문서 버전**: v2.0 (v1.0 전면 재검토 후 재작성)
- **작성일**: 2026-10-05
- **대상 코드베이스**: Geuryeojwo-Powered by Geurim-gyeol (v0.2, PySide6 6.6~6.x)
- **목표**: 자체 정의 어두운 색상 중심 UI를 Google Material Design 3(M3) 기반으로 전면 개편

> 이 문서는 **기획서**다. 코드 변경은 포함하지 않는다.
> 실행 전 반드시 §12(완료 기준)를 기준으로 판정한다.
>
> **v1.0 → v2.0 무엇이 바뀌었나**
> v1.0은 2026-10-02 시점 코드를 기준으로 써서 대상 파일·수치·검증 기준이
> 전부 틀렸다. 이 버전은 **2026-10-04 기준 코드를 직접 읽어 확인한 값**만
> 적었다. v1.0의 오류 목록은 §14에 남긴다.

---

## 0. 문서 규칙

- **모든 수치는 확인한 위치와 함께 적는다.** `(파일:줄)` 형식.
- 확인하지 않은 것은 "미확인"으로 표시한다. 추측을 사실처럼 쓰지 않는다.
- 위젯 클래스 이름은 Qt 클래스 그대로 쓴다.

---

## 1. 범위와 비범위

### 범위(In Scope)

| 대상 | 파일 | 확인 |
|---|---|---|
| 테마 색상 정의 | `app/gui/theme/manager.py` | `THEMES` (16~49행) |
| QSS 스타일시트 | `app/gui/theme/manager.py` | `_generate_qss()` (107~198행) |
| 인라인 하드코딩 스타일 제거 | `app/gui/main_window.py` | §6.2 목록 (19줄) |
| 인라인 하드코딩 스타일 제거 | `app/gui/session_browser.py` | §6.2 목록 (1줄) |
| 인라인 하드코딩 스타일 제거 | `app/gui/import_dialog.py` | §6.2 목록 (13줄 / 리터럴 13개) — **v1.0 누락** |
| 커버 안 된 위젯 QSS 추가 | `app/gui/theme/manager.py` | §5.10 — **v1.0 누락** |
| 간격·여백 4dp 그리드 정렬 | `app/gui/main_window.py`, `session_browser.py`, `import_dialog.py` | §4.6 |
| elevation / state layer / ripple | 신규 모듈 (Phase 3~4) | §8 |

### 비범위(Out of Scope)

- 레이아웃 구조 자체의 변경 (탭 구성, 위젯 배치 순서)
- 엔진/스토리지/세션 로직
- 다크/라이트 **외에** 테마 추가(예: 고대비, 브랜드 컬러) — 필요 시 Phase 5 이후 확장
- `ComfyCraft` 등 외부 테마 체계 이식 기록 보존

---

## 2. 현재 상태 진단 (As-Is)

### 2.1 색상 체계

`app/gui/theme/manager.py` 의 `THEMES` 는 M3가 아닌 자체 팔레트다 (16~49행).

| 토큰 | 현재 dark | 현재 light | M3 대응 토큰 |
|---|---|---|---|
| `background` | `#1a1a1a` | `#f5f5f5` | `surface` |
| `surface` | `#222222` | `#ffffff` | `surface-container-low` |
| `surface_alt` | `#2a2a2a` | `#f0f0f0` | `surface-container-high` |
| `border` | `#444444` | `#e0e0e0` | `outline-variant` |
| `text` | `#e0e0e0` | `#333333` | `on-surface` |
| `text_secondary` | `#a0a0a0` | `#707070` | `on-surface-variant` |
| `accent` | `#4a9fff` | `#2196F3` | `primary` |
| `accent_hover` | `#6bb0ff` | `#1976D2` | `primary` + state layer 8% |
| `danger` | `#ff6b6b` | `#f44336` | `error` |
| `warning` | `#ffd93d` | `#FF9800` | *(M3에 없음 → `tertiary` 로 대체)* |
| `success` | `#6bcf7f` | `#4CAF50` | *(M3에 없음 → `primary` 로 대체)* |

**핵심 문제 3가지**

1. **토큰이 11개뿐이다.** M3는 기본 20개, 확장(tonal palette)으로 100개 이상이다.
   `surface-container` 5단계, `primary-container`, `on-*` 쌍이 전부 없다.
   이 때문에 "배경"이 한 종류로 뭉개진다.
2. **`QWidget` 에 전역 `background-color` 를 건다** (`manager.py:110-112`).
   이것이 현재 UI가 "모든 것이 같은 회색 판 위의 상자"처럼 보이는 근본 원인이다.
   M3는 표면의 **높이차(surface tint elevation)** 로 층을 만드는데,
   전역 배경 지정이 그 구분을 없앤다.
3. **`warning` / `success` 가 M3에 없다.** M3는 `tertiary`(보조 강조)와
   `error` 만 갖는다. 임의로 넣은 두 토큰을 그대로 옮기면 M3가 되지 않는다.

### 2.2 하드코딩된 인라인 스타일 (테마 무시 버그)

**이것은 현재 버그다.** Qt에서 위젯 레벨 `setStyleSheet()` 은
애플리케이션 레벨 스타일시트보다 우선한다. 따라서 아래 코드는
라이트 테마로 전환해도 **색이 바뀌지 않는다.**

v1.0은 "총 10곳"이라 했지만 실제는 **33줄**이다.
`app/gui/import_dialog.py` 가 아예 빠져 있었다.

| 파일 | 줄 수 | 색상 리터럴 수 |
|---|---|---|
| `app/gui/main_window.py` | 19 | 20 |
| `app/gui/session_browser.py` | 1 | 3 |
| `app/gui/import_dialog.py` | 13 | 13 |
| **합계** | **33** | **36** |

(색상 리터럴 수는 `#[0-9a-fA-F]{3,8}` 정규식으로 기계 집계한 값이다.
`main_window.py:1166` 은 한 줄에 2개(`#7fb3ff`, `#d9534f`)가 들어간다.)

전체 인벤토리는 §6.2에 줄 번호와 함께 적었다.

### 2.3 커버 안 된 위젯 (v1.0 누락 — 신규 발견)

현재 QSS가 다루는 클래스: `QWidget`, `QGroupBox`, `QPushButton`,
`QComboBox`/`QSpinBox`/`QDoubleSpinBox`, `QTextEdit`/`QLineEdit`,
`QTabBar::tab`, `QTreeWidget`, `QProgressBar`, `QLabel`, `QToolBar`,
`QSplitter::handle`.

**다음 위젯은 QSS가 아예 없다.** OS 기본 모양으로 렌더링돼 테마와 무관하게 보인다.

| 위젯 | 위치 | 비고 |
|---|---|---|
| `QListWidget` | `main_window.py:595` (`self.workflow_list`) | **Model 탭의 워크플로 목록 자체** |
| `QSlider` | `main_window.py:1823` | LoRA 강도 슬라이더 |
| `QCheckBox` | `main_window.py:857` (`self.enhance`) | 인핸서 켜기 |
| `QScrollBar` | 전역 | 어디에도 스타일 없음 |
| `QHeaderView` | `session_browser.py:132` | 트리 헤더 |
| `QTextBrowser` | `import_dialog.py:98` (`self.report_view`) | HTML 리치 텍스트 |
| 콤보 드롭다운(`QListView`) | 전역 | 항목 색이 테마를 안 따른다 |

→ §5.10에 변환 규칙을 추가했다. **이걸 빼면 "테마를 바꿨는데
일부만 바뀌었다"는 결과가 그대로 남는다.**

### 2.4 타이포그래피

`font-size` 는 `14px`(본문, `manager.py:114`), `11px`(보조,
`main_window.py:862,882,1822`), `12px`(경고, `:498,638`),
`18px`(제목, `:480`) 네 값만 쓰고 **임의로** 흩어져 있다.
행간(line-height)과 자간(tracking) 규칙이 없다. M3 타입 스케일(11단계)과
대응되지 않는다.

폰트 스택은 `'Segoe UI', 'Malgun Gothic', Arial, sans-serif` 다
(`manager.py:113`). Roboto·Noto Sans KR 이 없다.

### 2.5 모양(Shape)

`border-radius` 가 `3px`(progressbar chunk, `manager.py:184`),
`4px`(button/input/tab, `:131,145,153,159`),
`6px`(groupbox, `:118`) 로 흩어져 있다. M3 모양 단계(corner scale)와
대응되지 않는다.

### 2.6 간격(Spacing)

`setSpacing()` 값 인벤토리 (실제 코드에서 확인):

| 값 | 위치 |
|---|---|
| 1 | `main_window.py:881` |
| 2 | `main_window.py:900` |
| 3 | `main_window.py:242` |
| 4 | `main_window.py:556,643,871,872,909,910,1830` |
| 6 | `main_window.py:476` |
| 10 | `main_window.py:479` |

v1.0은 "1, 4, 6, 10"이라 했으나 **2와 3도 있다.**
M3는 4dp 기본 그리드를 쓴다.

### 2.7 없는 것들 (M3 핵심)

Material 3 를 정의하는 다음 요소가 **하나도 없다.**

- **elevation shadow** — QSS `box-shadow` 미지원
- **state layer** (hover 8% / focus 10% / pressed 10% / dragged 16%) — 미구현
- **ripple** (터치 ripple) — 미구현
- **focus ring** — 미구현 (키보드 접근성 결함)
- **모션/전환** — 미구현
- **터치 타깃 규칙** — 현재 버튼 높이 약 31px (14px 폰트 + padding 6px×2 + border 2px)

---

## 3. 기술적 제약 — 반드시 먼저 읽을 것

> **QSS는 M3의 핵심 3요소(그림자·상태층·모션)를 표현할 수 없다.**
> 이 사실을 무시하면 "Material처럼 보이는 색만 바꾼" 결과가 된다.

| M3 요소 | QSS 지원 | 필요 구현 |
|---|---|---|
| 색상 | ✅ 완전 지원 | QSS |
| 타이포그래피 | ✅ 지원 (font-family/size/weight만) | QSS |
| 모양(radius) | ✅ 지원 | QSS |
| 간격(padding/margin) | ✅ 지원 | QSS + 레이아웃 코드 |
| elevation shadow | ❌ `box-shadow` 없음 | `QGraphicsDropShadowEffect` |
| state layer (반투명 오버레이) | ⚠️ 부분 — `background-color: rgba()` 로 근사 가능 | QSS |
| ripple | ❌ 없음 | `eventFilter` + `QPropertyAnimation` |
| 모션/전환 | ❌ 없음 | `QPropertyAnimation` / `QEasingCurve` |
| focus ring | ⚠️ `:focus` 선택자는 있으나 형태 제어 어려움 | QSS + 커스텀 paint |

### 3.1 `QGraphicsDropShadowEffect` 의 알려진 함정

이 효과는 **자식이 있는 위젯에 정상 적용되지 않는다.** 효과가 위젯 자체의
pixmap 에 걸리는데, 자식이 그 위에 별도로 그려지기 때문에 그림자가 가려지거나
아예 나타나지 않는다.

- **대응**: 효과를 걸 대상은 항상 **자식이 없는 컨테이너(QFrame)** 로 한 겹 감싼다.
  그룹박스를 그대로 효과 대상에 지정하지 않는다.
- **성능**: 이미지 프리뷰(큰 pixmap)에는 효과를 걸지 않는다. 드로잉 비용이
  프레임마다 발생한다.

**v2.0 추가 — 위험이 v1.0이 말한 것보다 크다.**
`session_browser.py:257-277` 이 **QTreeWidget 안에 QPixmap 썸네일을 행마다
삽입**한다(`_thumbnail()`, `:273`). 트리나 History 탭 어딘가에 효과가
붙으면 **썸네일이 매 프레임 다시 그려진다.**
→ 규칙을 "**QPixmap 자손이 있는 위젯 전체에 효과 금지**"로 넓힌다.

### 3.2 데스크톱에서의 M3 (M3 Express)

M3는 터치 기기 밀도로 설계됐다. 이 앱은 데스크톱이다.

| 규칙 | 터치 | 이 앱 적용값 | 이유 |
|---|---|---|---|
| 터치 타깃 | 48dp | **버튼 40px, 탭 40px, 최소 클릭 영역 32px** | 마우스 조작이 주라 48dp는 지나치게 큼 |
| elevation | 0~5단계 | **0~2단계만 사용** | 데스크톱 M3 Express 규칙 |
| 모션 | 200~500ms | **150~250ms** | 지연감이 체감됨 |

**이 적용값은 M3가 아니라 M3의 데스크톱 확장이며, 그 점을 문서화해 둔다.**

> v1.0 내부 모순 해소: v1.0은 §3.2에서 버튼 36dp, §5.1에서 버튼 높이 40px로
> 서로 달랐다. v2.0은 **버튼·탭 40px**로 통일한다.

### 3.3 v2.0 신규 제약 — 위젯 레벨 스타일시트가 앱 QSS를 가린다

`import_dialog.py:73` 이 **QDialog 자신에게** `setStyleSheet("font-size: 14px;")`
를 건다. Qt에서 위젯 레벨 스타일시트는 애플리케이션 레벨보다 우선하므로
**이 창 전체 서브트리가 앱 테마 QSS를 받지 못한다.**

→ §6.1 (A) 방식(속성 기반 QSS 선택자)으로 고치려면 **이 줄을 지우는 것이
전제**다. 지우지 않으면 창 안의 모든 위젯이 테마를 무시한다.

### 3.4 v2.0 신규 제약 — 리치 텍스트 HTML 색은 QSS로 못 바꾼다

`import_dialog.py` 의 `QTextBrowser`(`:98`)는 HTML을 직접 조립하며
인라인 `style='color:#777'` 등을 넣는다 (`:102,103,153,159,165,237`).
**QSS 선택자는 리치 텍스트 안에 닿지 않는다.**

→ §6.1 (A) 방식으로는 제거 불가. 별도 처방이 필요하다:
**색을 토큰으로 조립**하거나 `QTextDocument` 의 기본 스타일시트를
주입한다. §6.3에 방법을 적었다.

### 3.5 v2.0 신규 제약 — 모듈 상수는 테마 전환을 못 따른다

`main_window.py:64-65`

```python
_BAD_COLOR = "#ff6b6b"
_BAD_QSS = f"QComboBox {{ color:{_BAD_COLOR}; }}"
```

이 값은 **임포트 시점에 한 번만 계산**된다. `ThemeManager.apply_theme()`
(`manager.py:104`)가 `app.setStyleSheet()`를 다시 호출해도 이 상수는
바뀌지 않는다. 즉 **다크→라이트 전환 시 "설치 안 된 모델" 빨간색이
다크 테마 값으로 남는다.**

`main_window.py:1690` 의 `QBrush(QColor("#c9d1d9"))` 도 같은 문제다.

→ §6.4에 동적화 처방을 적었다. **이 두 곳을 빼면 §12의 "테마 전환 시
1픽셀도 안 보임"은 달성 불가능하다.**

---

## 4. 디자인 토큰 정의

`app/gui/theme/manager.py` 의 `THEMES` 를 아래 구조로 교체한다.

### 4.1 색상 — M3 Baseline 팔레트

Material Theme Builder 의 **Baseline** 스킴 값을 그대로 쓴다. 임의 색을 섞지 않는다.

#### 다크 테마 (`dark`)

| 역할 | HEX | 역할 | HEX |
|---|---|---|---|
| primary | `#D0BCFF` | on-primary | `#381E72` |
| primary-container | `#4F378B` | on-primary-container | `#EADDFF` |
| secondary | `#CCC2DC` | on-secondary | `#332D41` |
| secondary-container | `#4A4458` | on-secondary-container | `#E8DEF8` |
| tertiary | `#EFB8C8` | on-tertiary | `#332D41` |
| tertiary-container | `#633B48` | on-tertiary-container | `#FFD8E4` |
| error | `#F2B8B5` | on-error | `#601410` |
| error-container | `#8C1D18` | on-error-container | `#F9DEDC` |
| surface | `#1C1B1F` | on-surface | `#E6E1E5` |
| surface-variant | `#49454F` | on-surface-variant | `#CAC4D0` |
| outline | `#938F99` | outline-variant | `#49454F` |
| inverse-surface | `#313033` | inverse-on-surface | `#F4EFF4` |

**surface-container 5단계** (M3 의 층 구분 핵심)

| 토큰 | HEX |
|---|---|
| surface-container-lowest | `#0F0D13` |
| surface-container-low | `#1D1B20` |
| surface-container | `#211F26` |
| surface-container-high | `#2B2930` |
| surface-container-highest | `#36343B` |

#### 라이트 테마 (`light`)

| 역할 | HEX | 역할 | HEX |
|---|---|---|---|
| primary | `#6750A4` | on-primary | `#FFFFFF` |
| primary-container | `#EADDFF` | on-primary-container | `#21005D` |
| secondary | `#625B71` | on-secondary | `#FFFFFF` |
| secondary-container | `#E8DEF8` | on-secondary-container | `#1D192B` |
| tertiary | `#7D5260` | on-tertiary | `#FFFFFF` |
| tertiary-container | `#FFD8E4` | on-tertiary-container | `#31111D` |
| error | `#B3261E` | on-error | `#FFFFFF` |
| error-container | `#F9DEDC` | on-error-container | `#410E0B` |
| surface | `#FFFBFE` | on-surface | `#1C1B1E` |
| surface-variant | `#E7E0EC` | on-surface-variant | `#49454F` |
| outline | `#79747E` | outline-variant | `#CAC4D0` |
| inverse-surface | `#313033` | inverse-on-surface | `#F4EFF4` |

**surface-container 5단계**

| 토큰 | HEX |
|---|---|
| surface-container-lowest | `#FFFFFF` |
| surface-container-low | `#F7F2FA` |
| surface-container | `#F3EDF7` |
| surface-container-high | `#ECE6F0` |
| surface-container-highest | `#E6E0E9` |

### 4.2 기존 토큰 → M3 토큰 매핑

**v2.0 단순화 — 별도 호환 계층을 두지 않는다.**

v1.0은 "마이그레이션용 매핑 표"를 뒀지만, 확인 결과 **`get_colors()` 를
호출하는 곳이 `manager.py` 밖에 없다**(`manager.py:103` 단 1곳.
`tests/test_output_session.py:119` 는 `ThemeManager` 를 import만 한다).
외부 소비자가 없으므로 **토큰 이름을 바로 M3로 바꿔도 된다.**
호환 별칭을 두면 죽은 코드가 된다.

| 기존 키 | M3 키 (dark) | 비고 |
|---|---|---|
| `background` | `surface` | |
| `surface` | `surface-container-low` | |
| `surface_alt` | `surface-container-high` | |
| `border` | `outline-variant` | |
| `text` | `on-surface` | |
| `text_secondary` | `on-surface-variant` | |
| `accent` | `primary` | |
| `accent_hover` | `primary` + state layer 8% | 색이 아니라 오버레이로 표현 |
| `danger` | `error` | |
| `warning` | `tertiary` | M3에 warning 없음 → **tertiary 로 대체** |
| `success` | `primary` | M3에 success 없음 → **primary 로 대체** |

> `warning` → `tertiary`, `success` → `primary` 는 **의미 변경**이다.
> `_paint_usage()` 의 `UsageLevel.OK/WARN/DANGER` 3단계는 M3의
> `primary/tertiary/error` 3색 구조와 정확히 대응하므로 그대로 유지한다.
> (`main_window.py:82-96`)

### 4.3 타이포그래피 스케일

Roboto 기준 M3 타입 스케일을 이 앱에 필요한 항목만 추린다.

| 스타일 | font-size | line-height | weight | letter-spacing | 이 앱 용도 |
|---|---|---|---|---|---|
| headline-small | 24px | 32px | 400 | 0 | 앱 타이틀 "그려줘 v0.2" |
| title-large | 22px | 28px | 400 | 0 | (예비) |
| title-medium | 16px | 24px | 500 | 0.15px | GroupBox 제목 |
| title-small | 14px | 20px | 500 | 0.1px | 버튼 |
| body-large | 16px | 24px | 400 | 0.5px | 프롬프트 입력창, 로그 |
| body-medium | 14px | 20px | 400 | 0.25px | 상태바, 목록 본문 |
| body-small | 12px | 16px | 400 | 0.4px | 보조 설명 |
| label-large | 14px | 20px | 500 | 0.1px | 입력 필드 라벨 |
| label-medium | 12px | 16px | 500 | 0.5px | 보조 라벨 (W/H/Steps 등) |
| label-small | 11px | 16px | 500 | 0.5px | 최소 크기 라벨 |

**QSS 제약**: Qt의 `font-size` 는 `px` 만 받는다. `line-height` 와
`letter-spacing` 은 **QSS로 제어 불가**. 행간은 레이아웃 `setSpacing()` 으로,
자간은 필요 시 `QFont.setLetterSpacing()` 을 코드에서 적용한다.
이 두 항목은 **CSS 그대로 옮길 수 없다**는 점을 구현 시 유의한다.

### 4.4 폰트 스택

```css
font-family: 'Roboto', 'Noto Sans KR', 'Segoe UI Variable Text', 'Malgun Gothic', 'Segoe UI', sans-serif;
```

- Roboto / Noto Sans KR 은 시스템에 없을 수 있다. 없어도 뒤의 폰트로
  자연스럽게 폴백한다(degrades gracefully).
- 폰트 파일 동봉은 파일 추가로 이어지므로 **선택 사항**으로 둔다(§8 Phase 5).
- 한글은 `Malgun Gothic`(Windows 기본)이 가장 안정적이다.

### 4.5 모양(Shape) 스케일

> v1.0 내부 모순 해소: v1.0은 §4.5에서 버튼 8px, §5.1에서 버튼 20px로
> 서로 달랐다. v2.0은 **M3 규칙대로 버튼은 Full(높이의 절반)**로 통일한다.

| 토큰 | radius | 적용 대상 |
|---|---|---|
| corner-none | 0px | 이미지 프리뷰, progressbar 트랙 |
| corner-extra-small | 4px | progressbar chunk, 체크박스, 입력 필드(Outlined 상단) |
| corner-small | 8px | 카드 내부 컨테이너 |
| corner-medium | 12px | 카드(GroupBox), dialog 내부 패널 |
| corner-large | 16px | (예비) |
| corner-extra-large | 28px | Dialog |
| corner-full | 높이/2 | **버튼(Filled/Outlined)** |

### 4.6 간격(Spacing) — 4dp 그리드

| 토큰 | 값 | 적용 |
|---|---|---|
| space-1 | 4px | 아이콘↔라벨, 필드 내부 |
| space-2 | 8px | 라벨↔필드, 버튼 간격 |
| space-3 | 12px | GroupBox 내부 여백 |
| space-4 | 16px | GroupBox 간격, 카드 여백 |
| space-6 | 24px | 섹션 간격 |
| space-8 | 32px | 큰 블록 |

현재 쓰이는 `1`, `2`, `3`, `4`, `6`, `10` 은 위 스케일로 흡수한다.
`1px` 은 M3에 없지만 M3 Dense 관례상 유지 가능하다(라벨 위아래 미세 간격).

### 4.7 Elevation (Phase 3)

> v1.0 내부 모순 해소: v1.0은 §5.3에서 카드 elevation 0, §12에서
> "카드에 elevation가 있고"로 서로 달랐다. v2.0은 **카드는 resting 0,
> hover 시 1로 올린다**로 통일한다. 이게 M3 Express 관행이고 Phase 3의
> 가치를 남긴다.

| 레벨 | dp | blur-radius | y-offset | 용도 |
|---|---|---|---|---|
| 0 | 0 | — | — | 페이지 배경, 카드 resting |
| 1 | 1 | 3 | 1 | 카드 hover, dialog |
| 2 | 3 | 6 | 2 | (예비) |

> M3 elevation 은 2겹 그림자(base + tint)지만 Qt 는 단일
> `QGraphicsDropShadowEffect` 다. base 그림자 + 상위 오버레이로 근사한다.
> **근사임을 주석으로 남긴다.**

### 4.8 State Layer (Phase 3)

`on-surface` (다크) 또는 `on-surface` 기준 오버레이 불투명도.

| 상태 | 불투명도 | QSS 표현 |
|---|---|---|
| hover | 8% | `background-color: rgba(<r>,<g>,<b>, 0.08)` |
| focus | 10% | 동일 값 + focus ring 별도 |
| pressed | 10% | 동일 값 |
| dragged | 16% | 동일 값 |
| disabled (아이콘) | 38% | `color: rgba(..., 0.38)` |
| disabled (텍스트) | 12% | `color: rgba(..., 0.12)` |

테마별로 on-surface 의 RGB 가 다르므로 **토큰 문자열 치환이 아니라
계산된 rgba 를 넣어야 한다.** `get_colors()` 가 HEX만 주므로 헬퍼가 필요하다.

### 4.9 모션 (Phase 4)

| 토큰 | duration | curve | 용도 |
|---|---|---|---|
| short | 100ms | `ease-out` | hover, ripple 시작 |
| medium | 200ms | `ease-in-out` | 패널 전개, 탭 전환 |
| long | 300ms | `ease-in-out` | dialog 등장 |

**Qt 대응**: `QEasingCurve.Type.OutCubic`, `QEasingCurve.Type.InOutCubic`

---

## 5. 컴포넌트별 변환 규칙

### 5.1 버튼 (QPushButton)

**현재**: surface 배경 + 1px border + 4px radius + padding 6×12
(`manager.py:128-141`)

**M3**: 버튼은 3종으로 나눈다.

| 종류 | M3 이름 | 구현 |
|---|---|---|
| 주 액션 | Filled Button | `background: primary` / `color: on-primary` / radius Full / 높이 40px |
| 보조 | Outlined Button | `background: transparent` / `border: 1px solid outline` / `color: on-surface` / radius Full / 높이 40px |
| 경량 | Text Button | 배경·테두리 없음 / `color: primary` / padding만 8×12 |

**이 앱 적용안** — 실제 버튼은 **16개**다. v1.0은 10개만 적었다.

| 버튼 | 위치 | 종류 |
|---|---|---|
| `그려줘` (generate) | `main_window.py:921` | **Filled Button** — 유일한 주 액션 |
| `중지` (cancel) | `main_window.py:921` | Outlined Button (생성 중일 때만 Filled error) |
| `새로고침` (Generate 탭) | `main_window.py:922` | Text Button |
| `고급` (checkable) | `main_window.py:923` | Text Button — **v1.0 누락**. 토글 상태는 `:checked` 로 표시 |
| `상태 새로고침` | `main_window.py:489` | Text Button |
| `테마` | `main_window.py:490` | Text Button |
| `+ 가져오기` | `main_window.py:605` | Outlined Button — **v1.0 누락** |
| `삭제` (Model 탭) | `main_window.py:612` | **Outlined + error 색상** — 파괴 동작임을 색으로 알림 |
| `새로고침` (History) | `session_browser.py:106` | Text Button |
| `폴더 열기` | `session_browser.py:107` | Outlined Button |
| `다른 이름으로 저장` | `session_browser.py:108` | Outlined Button |
| `삭제` (History) | `session_browser.py:109` | **Outlined + error 색상** |
| `Prompt 복사` | `session_browser.py:110` | Outlined Button |
| `재생성` | `session_browser.py:111` | Outlined Button |
| `파일 선택` | `import_dialog.py:92` | Outlined Button — **v1.0 누락** |
| `취소` | `import_dialog.py:135` | Text Button — **v1.0 누락** |
| `등록` | `import_dialog.py:137` | **Filled Button** — **v1.0 누락** |

> **모두 같은 스타일로 두면 "무엇이 중요한 행동인지" 알 수 없다.**
> 지금처럼 전부 동일한 회색 버튼이면 사용자가 매번 읽어야 한다.
> `그려줘` 와 `등록` 만 색을 칠하는 것이 M3의 가장 값싼 개선이다.

**상태**

```css
QPushButton:hover   { background: <overlay 8%>; }
QPushButton:pressed { background: <overlay 10%>; }
QPushButton:disabled{ color: rgba(...,0.38); background: transparent; }
QPushButton:focus   { outline: 2px solid primary; outline-offset: 2px; }  /* QSS 제약으로 불안정 → Phase 4에서 커스텀 paint */
```

### 5.2 입력 필드 (QTextEdit / QLineEdit / QComboBox / QSpinBox)

**현재**: surface 배경 + 1px border + 4px radius + padding 4×8
(`manager.py:142-155`)

**M3 Filled Text Field**

| 항목 | 값 |
|---|---|
| 컨테이너 배경 | `surface-container-highest` |
| 활성 밑줄 | 2px `primary` |
| 비활성 밑줄 | 1px `outline` |
| focus 시 | 밑줄 2px `primary` |
| radius | 4px (상단만) |
| 라벨 | focus 시 `primary` / blur 시 `on-surface-variant` |
| helper text | `on-surface-variant` |

**이 앱 적용안**

텍스트 필드 전체를 Filled 로 바꾸면 프레시보기까지 Filled 로 바뀌어 과해진다.
**프롬프트·Negative(여러 줄)만 Filled**, 파라미터 숫자 입력과 combo 는
**Outlined** 로 두는 편이 낫다.

- 프롬프트 / Negative → Filled (여백이 크고 입력량이 많다)
- W / H / Steps / CFG / Seed / Sampler / Scheduler / LoRA → Outlined

> **v1.0 오류 정정**: v1.0은 "model combo 4개 → Outlined"라 했지만
> 실제 모델 콤보는 **개수가 고정되어 있지 않다.**
> `_rebuild_model_rows()`(`main_window.py:676-715`) 가 워크플로마다
> 행을 다시 만든다. CLIP 은 1개일 수도 4개일 수도 있고(`:641` 주석),
> 커스텀 노드의 선택형 입력도 같은 그리드에 들어온다(`:684-686`).
> → **콤보 개수를 세는 방식으로 스타일을 정하면 안 된다.**
> `QComboBox` 클래스 선택자로 일괄 적용한다.

> **주의**: `self.neg` 는 `setFixedHeight(46)` (`main_window.py:868`) 이
> 걸려 있다. Filled 필드의 2px 밑줄 + 패딩이 46px 안에 들어오는지
> 확인이 필요하다. 안 들어오면 높이를 `sizeHint` 기반으로 바꾼다.

### 5.3 GroupBox

**현재**: 1px border + 6px radius + 제목에 `accent` 색
(`manager.py:116-127`)

**M3 Card**

| 항목 | 다크 | 라이트 |
|---|---|---|
| 배경 | `surface-container-low` | `surface-container-low` |
| radius | 12px (corner-medium) | 12px |
| elevation | 0 (resting) → hover 시 1 | 동일 |
| 제목 색 | `on-surface` | `on-surface` |
| 제목 크기 | title-medium (16px/500) | 동일 |
| 내부 여백 | 16px (`space-4`) | 16px |
| 구분선 | **없음** (배경 차이로 구분) | 동일 |

**현재 GroupBox 의 1px 테두리는 M3에 없다.** 테두리 대신 표면색 차이로
영역을 구분한다. 이를 적용하면 화면이 훨씬 현대적으로 보인다.

단, **`surface-container-low` 과 `surface` 의 대비가 미묘할 수 있다**
(dark: `#1D1B20` vs `#1C1B1F`, 차이 1단계). 이때는
`surface-container`(`#211F26`)를 쓴다.

### 5.4 탭 (QTabWidget)

**현재**: 닫힌 탭 = surface + border, 선택된 탭 = accent 배경 + background 글자
(알약 모양) (`manager.py:156-166`)

**M3 Primary Tabs**

| 항목 | 값 |
|---|---|
| 활성 탭 글자 | `on-surface` + **font-weight 500** |
| 비활성 탭 글자 | `on-surface-variant` |
| 활성 표시 | 탭 아래 3px `primary` 인디케이터 |
| 비활성 표시 | 1px `outline-variant` 인디케이터 |
| 탭 최소 높이 | 48px (M3) → 이 앱 **40px** (M3 Express) |
| 패딩 | 수평 16px |

**구현상 주의**: QSS `QTabBar::tab:selected` 로 **인디케이터 바**를 그릴 수 없다.
가능한 우회:

- (a) `border-bottom: 3px solid primary` 를 활성 탭에 적용 — 단순하고 충분히 M3에 가까움
- (b) `QTabBar` 를 `paintEvent` 로 재정의해 인디케이터를 직접 그리기 — 정확하지만 코드 증가

**Phase 1에서는 (a) 로 시작한다.** 시각적 차이는 작고 위험은 0이다.

> 이미 사용 중인 `setCornerWidget(Qt.TopRightCorner)`(워크플로 선택기,
> `main_window.py:521`)은 그대로 유지한다. M3 탭과 충돌하지 않고,
> 폭 경쟁 문제도 해결된 상태다.

### 5.5 상태바

**현재**: `RAM 58% | CPU 13% | VRAM 14% | GPU 7%` — 라벨 나열
(`main_window.py:524-533`)

**M3 적용안**
- 배경: `surface-container-low`
- 위쪽 1px `outline-variant` 구분선
- 본문: label-medium(12px/500), 색 `on-surface-variant`
- 값이 임계치를 넘으면 `error`(DANGER), 주의는 `tertiary`(WARN) —
  **현재 `_paint_usage()` 구조 유지** (`main_window.py:89-96`)
- 세로 가운데 정렬, 좌우 여백 16px

> 확인: "상태바는 사용률만, 타이틀바는 기기 정보를 맡는다"는 분업이
> 이미 코드에 반영돼 있다(`main_window.py:525-527` 주석). §12의 해당
> 항목은 **현재 상태와 일치**하므로 그대로 둔다.

### 5.6 제목바(상단 행)

**현재**: 앱 타이틀(18px bold, `main_window.py:480`) + 부제(`:482`) +
`comfy_label`(`:486`) + 버튼 2개(`:489-490`)

**M3 적용안**
- 앱 타이틀: **headline-small(24px)** (현재 18px → 24px)
- 부제: body-small(12px), `on-surface-variant`
- `comfy_label`: body-small(12px), 온라인 `primary` / 오프라인 `error`
- 버튼 2개: Text Button
- 구분선 없음 (배경만으로)

### 5.7 progressbar

| 항목 | 값 |
|---|---|
| 트랙 | `surface-container-highest`, radius 4px, 높이 4px |
| chunk | `primary`, radius 4px |
| 텍스트 | 표시하지 않음 (M3는 진행률만) |

**현재** chunk가 3px radius라 트랙(4px)과 어긋난다(`manager.py:184`).
둘 다 4px로 통일.

### 5.8 리스트/트리 (History 탭)

| 항목 | 값 |
|---|---|
| 배경 | `surface` |
| 행 높이 | 40px (썸네일 40px와 일치) |
| hover | `surface-container-low` |
| 선택 | `secondary-container` + `on-secondary-container` |

> **선택 색을 `primary` → `secondary-container` 로 바꾸는 것이 M3다.**
> `primary` 배경 + `background` 글자는 M3가 아니며 대비도 나쁘다
> (보조 텍스트가 읽히지 않는다).
> 현재 `manager.py:172-175` 가 `primary` 배경을 쓰고 있다.

### 5.9 Dialog (삭제 확인)

| 항목 | 값 |
|---|---|
| 배경 | `surface-container-high` |
| radius | 28px (corner-extra-large) |
| elevation | 1 (1dp) |
| 본문 | body-medium(14px) |
| 버튼 | Text Button 2개(취소 / 확인) |

### 5.10 v2.0 신규 — 커버 안 된 위젯 (§2.3)

이 위젯들은 지금 QSS가 없어 OS 기본 모양이다. **Phase 1에서 반드시
함께 처리해야 한다.** 빼면 "테마를 바꿨는데 일부만 바뀌었다"가 된다.

| 위젯 | M3 대응 | 구현 |
|---|---|---|
| `QListWidget` (Model 탭 워크플로 목록) | 리스트 | §5.8과 동일. 배경 `surface`, hover `surface-container-low`, 선택 `secondary-container` |
| `QSlider` (LoRA 강도) | M3 Slider | 트랙 4px `surface-container-highest`, 핸들 `primary` 원형 16px, 활성 트랙 `primary` |
| `QCheckBox` (인핸서) | M3 Checkbox | 18px 박스, 체크 시 `primary` 채움, `on-primary` 체크마크 |
| `QScrollBar` | M3 Express 스크롤바 | 두께 12px, `surface-container-high` 트랙, `on-surface-variant` 40% 핸들, hover 70% |
| `QHeaderView` (트리 헤더) | 테이블 헤더 | `surface-container-low` 배경, label-medium, `on-surface-variant` |
| `QTextBrowser` (가져오기 결과) | 본문 영역 | 배경 `surface-container-low`, §6.3으로 HTML 색을 토큰화 |
| 콤보 드롭다운(`QListView`) | 메뉴 | 배경 `surface-container-high`, 항목 hover state layer 8%, 선택 `secondary-container` |

---

## 6. 인라인 스타일 제거

### 6.1 방법

두 가지 중 **하나**를 채택한다.

| 방식 | 설명 | 권장 |
|---|---|---|
| (A) 테마 색을 위젯 속성으로 | 위젯에 `setProperty("role", "warning")` → QSS `QLabel[role="warning"]` 로 스타일링 | ✅ **권장** |
| (B) 문자열 생성 | `f"color: {self.theme_manager.get_colors()['warning']};"` | 가능하지만 테마 전환 시 수동 갱신 필요 |

**(A) 를 권장한다.** 테마 전환 시 Qt 가 자동으로 다시 스타일링하므로
갱신 코드가 필요 없다. 실제로 현재 버그(테마 전환해도 인라인 색이 안
바뀜)의 근본 해결이 된다.

**v2.0 추가 — (A)로 안 되는 경우가 있다.** §3.3, §3.4, §3.5 의 세 경우는
각각 §6.3, §6.4, §6.5의 별도 처방을 따른다.

#### 6.1.1 role 값 전체 목록 (Phase 1A 에서 QSS 로 정의)

속성 이름은 **`role` 하나만 쓴다.** §6.2/§6.5 표에 `level=` 으로 적힌 곳은
모두 `role=` 과 같은 뜻이다. 속성을 두 개 쓰면 규칙이 헷갈린다.

| `role` 값 | 쓰는 곳 | 색 (dark) |
|---|---|---|
| `ok` | `_LEVEL_QSS[OK]`, `_set_status` 준비완료 | (기본색 유지 — 색을 칠하지 않는다) |
| `warn` | `_LEVEL_QSS[WARN]`, `:408`, `:418` | `tertiary` |
| `danger` | `_LEVEL_QSS[DANGER]`, `:638`, `:862` | `error` |
| `secondary` | `:271`, `:282`, `import_dialog:90` | `on-surface-variant` |
| `divider` | `:305`, `:712` | `outline-variant` |
| `headline` | `:480` | `on-surface` (24px) |
| `subtitle` | `:482` | `on-surface-variant` (12px) |
| `comfy-pending` | `:486` (초기값) | `on-surface-variant` (12px) |
| `comfy-on` | `:1166` (온라인) | `primary` (12px) |
| `comfy-off` | `:1166` (오프라인) | `error` (12px) |
| `warning` | `:498` status_banner | `tertiary` (12px) |
| `label` | `:882`, `:1822` | `on-surface-variant` (11px) |
| `preview` | `:936`, `session_browser:161` | `surface-container` + `outline-variant` 테두리 |

버튼은 §5.1 에서 정한 `primary` / `secondary` / `text` 를 쓴다.
가져오기 다이얼로그의 4단계(`import_dialog:29-32`)는
`ok` / `info` / `warn` / `block` 을 쓴다(`info` 는 `on-surface-variant`,
`block` 은 `error`).

### 6.2 작업 대상 (전체 인벤토리 — 33줄 + 1)

#### `app/gui/main_window.py` (19줄)

| 줄 | 대상 | 현재 | 변경 |
|---|---|---|---|
| 64 | `_BAD_COLOR` | `"#ff6b6b"` | §6.4 — 함수화 |
| 84 | `_LEVEL_QSS[WARN]` | `"color:#ffd93d;"` | `role="warn"` |
| 85 | `_LEVEL_QSS[DANGER]` | `"color:#ff6b6b;"` | `role="danger"` |
| 271 | `ModelInfoPanel` 보조라벨 | `"color:#a0a0a0;"` | `role="secondary"` |
| 282 | `ModelInfoPanel` 섹션 제목 | `"color:#7a7a7a;"` | `role="secondary"` |
| 305 | 구분선 | `"color:#c8c8c8;"` | `role="divider"` |
| 408 | `_set_status` 호출 | `"#ffd93d"` | `"warn"` (§6.2.1) |
| 418 | `_set_status` 호출 | `"#ffd93d"` | `"warn"` (§6.2.1) |
| 429 | `_set_status` 호출 | `"#6bcf7f"` | `"ok"` (§6.2.1) |
| 480 | 앱 타이틀 | `"font-size:18px;font-weight:700"` | `role="headline"` (24px) |
| 486 | `comfy_label` 초기값 | `"color:#7fb3ff;"` | `role="comfy-pending"` |
| 498 | `status_banner` | `"color:#ffd93d; font-size:12px;"` | `role="warning"` |
| 638 | `_model_warning` | `"color:#ff6b6b; font-size:12px;"` | `role="danger"` |
| 712 | 구분선 | `"color:#d5d5d5;"` | `role="divider"` |
| 862 | `enhancer_warning` | `"color:#d9534f; font-size:11px;"` | `role="danger"` |
| 882 | `_field()` 보조라벨 | `"color:#a0a0a0; font-size:11px;"` | `role="label"` |
| 936 | `preview` | `"border:1px solid #444"` | `role="preview"` |
| 1166 | `comfy_label` 갱신 | `"color:#7fb3ff;"` / `"color:#d9534f;"` | `role="comfy-on"` / `"comfy-off"` |
| 1690 | 콤보 항목 브러시(**설치된** 모델의 정상 글자색) | `QColor("#c9d1d9")` | §6.4 — `on-surface` 로 동적화 |
| 1822 | LoRA 보조라벨 | `"color:#a0a0a0; font-size:11px;"` | `role="label"` |

#### `app/gui/session_browser.py` (1줄)

| 줄 | 대상 | 현재 | 변경 |
|---|---|---|---|
| 161 | `image_preview` | `"border: 1px solid #444; background: #222; color: #888;"` | `role="preview"` |

#### `app/gui/import_dialog.py` (13줄) — **v1.0 누락**

| 줄 | 대상 | 현재 | 변경 |
|---|---|---|---|
| 29-32 | `_STYLE` 단계 색 | `("#2e7d32", …)` 등 4종 | §6.3 — 토큰으로 조립 |
| 73 | **QDialog 자체** | `"font-size: 14px;"` | **삭제** (§3.3 — 앱 QSS를 가림) |
| 90 | `file_label` | `"color:#555;"` | `role="secondary"` |
| 102, 103 | 안내 HTML | `style='color:#777'` | §6.3 — 토큰으로 조립 |
| 128 | `hint` | `"color:#c62828; font-size:14px;"` | `role="danger"` |
| 148 | `_STYLE` 기본값 | `("#333333", "·")` | §6.3 — 토큰으로 조립 |
| 153, 159, 165 | 보고서 HTML | `color:#444` / `color:#777` / `color:#333` | §6.3 — 토큰으로 조립 |
| 237 | 오류 HTML | `color:#c62828` | §6.3 — 토큰으로 조립 |

> **성공 기준**: 라이트 테마로 전환했을 때 화면에 `#444` / `#222` /
> `#a0a0a0` 계열이 **한 픽셀도 남아있지 않아야 한다.**

### 6.2.1 v2.0 신규 — 리터럴은 없지만 **작업 대상인 곳**

`#[0-9a-fA-F]{3,8}` 정규식으로 세면 **33줄**이 나온다. 하지만 실제로
스타일을 만들어야 하는 자리는 그보다 하나 더 있다. **색을 인자로 받아
문자열로 조립하는 곳**은 정규식에 안 잡힌다.

| 줄 | 내용 | 왜 잡히지 않는가 |
|---|---|---|
| `main_window.py:384` | `self.status_label.setStyleSheet(f"color:{color};")` | 리터럴이 아니라 **변수** `color` 를 넣는다 |

`_set_status(text, color)`(`:377`)가 색을 인자로 받는 함수라서,
호출부 3곳(`:408`, `:418`, `:429`)의 리터럴이 실제로 384행에서 문자열이 된다.

→ **작업 대상은 34곳**이다. 처방은 §7 Phase 1B-2~1B-4 참조.
`_set_status` 의 시그니처를 `color: str` → `level: str`(role 이름)로 바꾸고,
384행을 `setProperty("role", level)` 로 바꾼다. 호출부는
`"#ffd93d"` → `"warn"`, `"#6bcf7f"` → `"ok"` 가 된다.

> **setProperty 주의 (Qt 함정)**: 위젯이 이미 화면에 나온 뒤에
> `setProperty()` 하면 스타일시트가 즉시 다시 계산되지 않는다.
> `w.style().unpolish(w); w.style().polish(w)` 를 같이 호출해야 한다.
> `build_ui()` 안에서 처음 붙일 때는 불필요하다.

### 6.3 v2.0 신규 — 리치 텍스트 HTML 색 제거 (§3.4)

`import_dialog.py` 의 `QTextBrowser` HTML은 QSS 선택자가 닿지 않는다.
두 가지 방법이 있다.

| 방법 | 설명 | 권장 |
|---|---|---|
| (i) HTML을 토큰으로 조립 | `f'<p style="color:{colors["on-surface-variant"]}">…'` | ✅ **권장** — 단순, 테마 전환 시 재조립 필요 |
| (ii) `QTextDocument` 기본 스타일시트 | `document().setDefaultStyleSheet("p { color: … }")` | 클래스 기반이라 재조립 불필요. 하지만 인라인 `style=` 가 여전히 우선하므로 **인라인을 먼저 제거해야 한다** |

**권장 조합**: (ii)로 기본 스타일을 정하고 인라인 `style=` 을 제거한다.
그러면 테마 전환 시 `setDefaultStyleSheet()`를 다시 호출하는 것으로
끝난다. 단, `import_dialog.py:102-103` 처럼 **한 번 조립한 HTML을
바꾸지 않는** 곳은 (i)로 전환해야 한다.

> **주의**: `QTextBrowser` 는 `setHtml()` 를 호출할 때마다 문서를 다시
> 만든다. 테마 전환 후에도 색이 유지되려면 **테마 전환 시점에 HTML을
> 다시 조립**해야 한다. `ThemeManager` 에 테마 변경 시그널을 추가하거나,
> 다이얼로그를 열 때마다 조립하는 쪽이 안전하다.

### 6.4 v2.0 신규 — 모듈 상수의 동적화 (§3.5)

`_BAD_COLOR` / `_BAD_QSS`(`main_window.py:64-65`)는 임포트 시점 상수라
테마 전환을 못 따른다.

**실제 사용처 (모두 확인함)**

| 줄 | 용도 |
|---|---|
| 1420 | 다른 계열 항목의 브러시 색 |
| 1424 | 다른 계열이 **현재 선택**됐을 때 콤보 전체 QSS |
| 1676 | `_refresh_combo_state()` — 고른 값이 '고르 수 없는 값'일 때 콤보 QSS |
| 1690 | 설치된 모델의 **정상 글자색** 브러시 (`#c9d1d9`) |
| 1693 | 설치 안 된 항목의 브러시 색 |

**처방**: 상수를 없애고 **함수로 바꾼다.**

```python
def _bad_qss(colors: dict) -> str:
    """설치 안 된 모델의 글자색. (테마마다 다르다)"""
    return f"QComboBox {{ color:{colors['error']}; }}"
```

`1420`, `1424`, `1676`, `1693` 은 `self.theme_manager.get_colors()`를
넘겨 호출한다. `1690` 은 **정상 색**이므로 `error` 가 아니라
`on-surface` 를 쓴다.

그리고 `MainWindow._toggle_theme()`(`:952-955`)에서 **콤보 상태를
다시 칠한다.** 콤보가 이미 있으면 `_refresh_combo_state(key)` 를,
없으면 다음 `_paint_missing_models()` 가 알아서 칠한다.

> **왜 중요한가**: 이 색은 "설치 안 된 모델 / 다른 계열 모델"을
> 빨간색으로 표시하는 **기능**이다. `tests/test_model_selection.py:1030`
> 이 `RED in combo.styleSheet().lower()` 로 이 동작을 검증한다.
> 토큰으로 바꾸면 `error`(`#F2B8B5`)가 되므로 **테스트도 함께 바꿔야
> 한다**(§10.2).

### 6.4.1 v2.0 신규 — 실측 결과: 구분선은 `color:` 다, `border-color` 가 아니다

`main_window.py:305`, `:712` 의 구분선은 `QFrame.setFrameShape(QFrame.HLine)`
에 `color:` 를 주었다. 구현자는 "선에는 `border-color` 지"는 식으로
손댈 수 있고, 그러면 **조용히 동작하지 않는다.**

offscreen 렌더링으로 실제 픽셀을 재 계측한 결과:

| 적용한 QSS | HLine 픽셀 | 줄이 바뀌는가 |
|---|---|---|
| (스타일 없음) | `(0,0,0)` | — |
| `color: red;` | `(127,0,0)` | ✅ **바뀐다** |
| `border-color: red;` | `(0,0,0)` | ❌ **안 바뀐다** |
| `border-top: 2px solid red;` | `(255,0,0)` | 바뀐다(줄이 2개 됨) |

→ **`color:` 가 HLine 에서 실제로 통한다.** 현재 코드가 버그가 아니며,
§6.2 의 `role="divider"` 처방도 `color:` 로 쓰는 것이 맞다.
**`border-color` 로 바꾸지 않는다.**

### 6.5 v2.0 신규 — `_LEVEL_QSS` 의 토큰화

`_LEVEL_QSS`(`main_window.py:82-86`)는 문자열 상수다. M3 토큰으로
바꾸면 값이 `color:#EFB8C8;`(tertiary) / `color:#F2B8B5;`(error)로
변한다.

**처방**: `_LEVEL_QSS` 를 없애고 role 기반으로 바꾼다(§6.1.1).

```python
def _paint_usage(label: QLabel, text: str, level: UsageLevel) -> None:
    """상태바(와 ModelInfo) 한 칸에 글자와 단계 색을 함께 칠한다."""
    label.setText(text)
    label.setProperty("role", {UsageLevel.OK: "ok",
                               UsageLevel.WARN: "warn",
                               UsageLevel.DANGER: "danger"}[level])
```

테마 전환 시 Qt 가 `QLabel[role="warn"]` 규칙을 다시 적용하므로
**갱신 코드가 필요 없다.** 이것이 (A) 방식의 본질적인 이점이다.

> `tests/test_status_bar.py:22` 가 `_LEVEL_QSS` 를 직접 import 하므로
> `_LEVEL_QSS` 를 없애면 **테스트가 import 에러로 죽는다.**
> import 를 없애고 `label.property("role")` 로 단언하도록 함께 고친다(§10.2).

---
## 7. 단계별 작업 계획

각 Phase 는 **되돌릴 수 있는 단위**다. 완료 후 `git commit` 하나를 남기고,
검증에 실패하면 그 Phase 만 `git revert` 한다.

### Phase 실행 순서와 커밋

| Phase | 커밋 접두사 | 되돌리기 |
|---|---|---|
| 0 | (커밋 없음 — 도구만 추가) | 파일 삭제 |
| 1A | `refactor(theme): M3 Baseline 토큰과 QSS 로 교체한다` | `git revert` |
| 1B | `refactor(gui): 인라인 색을 테마 속성으로 옮긴다` | `git revert` |
| 1C | `refactor(gui): 나머지 창도 테마를 받게 한다` | `git revert` |
| 2 | `refactor(theme): M3 타입 스케일을 적용한다` | `git revert` |
| 3 | `feat(gui): 카드에 elevation 과 상태층을 넣는다` | `git revert` |
| 4 | `feat(gui): 포커스 링과 ripple 을 넣는다` | `git revert` |

> Phase 1 을 A/B/C 로 나눈 이유: **1A(매니저) 가 깨져도 UI 가 전부 나빠지지
> 않지만, 1B/1C(위젯) 가 깨지면 일부만 어색해진다.** 나눠서 하면 원인을
> 특정하기 쉽다.

---

### Phase 0 — 준비 (프로덕트 코드 변경 없음)

**목표**: 나중에 비교할 기준선을 만든다. 기준선이 없으면 이 작업은 검증할 수 없다.

| # | 할 일 | 위치 | 산출물 / 확인 |
|---|---|---|---|
| 0-1 | 스크린샷 하네스 작성 | `tools/screenshot.py` (신규) | 아래 0-1 참조 |
| 0-2 | 기준선 캡처 6장 | — | `docs/screenshots/before/` 에 PNG 6개 |
| 0-3 | 기준선 캡처 3장 (추가) | — | 가져오기 다이얼로그 dark/light 2장 + 최소 크기(900×700) 1장 |
| 0-4 | 브랜치 생성 | — | `git branch ui-material-3` |
| 0-5 | 기준선 테스트 기록 | — | `pytest tests` → **5 failed, 423 passed** 를 문서에 기입 |
| 0-6 | **사전 실패 5건 정리** | `tests/test_non_blocking_refresh.py:64` | `workflows/qwen-image-2.1-baseline.json` → `qwen-image-2.1.json` 로 교체. 목적: 회귀 판정을 0/0 으로 만든다 |
| 0-7 | 테마 모듈 확인 | `app/gui/theme/__init__.py` | `ThemeManager` 가 export 되는지 확인 (2줄) |

**0-1 하네스가 만족해야 할 것**
- `QT_QPA_PLATFORM=offscreen` 로 동작 (GUI 없는 환경)
- `MainWindow` 를 3탭(`Generate` / `Model` / `History`)으로 돌아가며 `grab()`
- `ThemeManager.apply_theme("dark")` / `("light")` 를 각각 적용한 뒤 캡처
- 타이머(1초/3초 주기)를 멈춰 캡처가 비어 보이지 않게 한다
  (`w._fast_timer.stop(); w._slow_timer.stop()` — `tests/test_status_bar.py:277` 참고)
- `w.show()` 후 `processEvents()` 호출 (grab 전에 레이아웃이 끝나야 한다)
- **ComfyUI 접속은 하지 않는다.** 서버가 꺼져도 레이아웃은 그려진다
- 가져오기 다이얼로그는 `ImportWorkflowDialog` 를 별도로 띄워 캡처

**검증**
```powershell
.\.venv\Scripts\python.exe tools\screenshot.py --out docs\screenshots\before
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q tests
```

**완료 기준**
- [ ] `docs/screenshots/before/` 에 PNG **9장** 존재
- [ ] `pytest tests` 결과가 **428 passed, 0 failed**
- [ ] `git branch` 에 `ui-material-3` 존재

> **왜 0-6 이 먼저인가**: 지금은 매번 "이 5건은 원래 실패던 거니까" 라는
> 단서를 붙여 판정해야 한다. 0부터 0으로 만들면 **신규 실패만 보면 된다.**

---

### Phase 1A — M3 토큰 + QSS (매니저만 건드린다)

**목표**: 테마 정의와 QSS 만 M3로 바꿔 **전체 화면의 기본 질감**을 바꾼다.
이 Phase 에서는 위젯 코드를 한 줄도 건드리지 않는다.

**변경 파일**: `app/gui/theme/manager.py`, `app/gui/theme/state.py` (신규)

| # | 할 일 | 위치 | 확인 |
|---|---|---|---|
| 1A-1 | `THEMES` 를 M3 Baseline 으로 교체 | `manager.py:16-49` | 다크/라이트 각각 29개 토큰. 값은 §4.1 그대로 |
| 1A-2 | 토큰 이름 교체 (`background`→`surface` 등) | `manager.py:16-49` | §4.2 매핑표. **호환 별칭을 두지 않는다** |
| 1A-3 | `state.py` 작성 — HEX→`rgba()` 변환 + state layer 헬퍼 | `app/gui/theme/state.py` (신규) | `overlay("#E6E1E5", 0.08)` → `rgba(230,225,229,0.08)` |
| 1A-4 | `_generate_qss()` 재작성 | `manager.py:107-198` | 아래 1A-5~1A-14 |
| 1A-5 | **`QWidget` 전역 `background-color` 제거** | `manager.py:110-112` | 제거 후 최상위 배경이 `surface` 로 오돌아와야 한다 |
| 1A-6 | `QGroupBox` → Card | `manager.py:116-127` | border 제거, 배경 `surface-container-low`, radius 12px, 제목 16px/500 |
| 1A-7 | 버튼 3종 도입 | `manager.py:128-141` | `QPushButton[role="primary"/"secondary"/"text"]`. 기본은 Outlined |
| 1A-8 | 입력 필드 Filled / Outlined | `manager.py:142-155` | `QTextEdit[role="filled"]` + 나머지 Outlined |
| 1A-9 | 탭 인디케이터 | `manager.py:156-166` | `:selected` 에 `border-bottom: 3px solid primary`. 알약 배경 제거 |
| 1A-10 | progressbar 4px 통일 + 텍스트 숨김 | `manager.py:176-185` | chunk radius 3→4px, `text-align` 제거 |
| 1A-11 | 트리/리스트 선택색 `secondary-container` | `manager.py:167-175` | 현재 `primary` 배경 (§5.8) |
| 1A-12 | `QToolBar` / `QSplitter::handle` 갱신 | `manager.py:189-197` | surface-container-low / outline |
| 1A-13 | **§5.10 커버 안 된 7종 추가** | `_generate_qss()` 에 append | `QListWidget`, `QSlider`, `QCheckBox`, `QScrollBar`(전역), `QHeaderView`, `QTextBrowser`, `QComboBox::drop-down`+`QListView` |
| 1A-14 | role 별 QSS 규칙 블록 추가 | `_generate_qss()` | §6.1.1 표의 role 전부 |

**⚠ 주의**
- 1A-5 (전역 배경 제거) 가 이 Phase 의 최대 위험이다. 투명 위젯이 검게 보이면
  **어느 위젯인지 화면으로 특정**해서 해당 셀렉터에 배경을 명시한다.
- 1A-13 의 `QScrollBar` 는 `*` 선택자로 전역에 걸어야 한다.
  세로/가로를 함께 걸면 `::add-line` / `::sub-line` 이 기본 화살표로 남으므로
  `width: 0` 으로 지운다.
- 버튼 40px 높이는 `min-height` 로 준다. `padding` 만으로는 Qt 가 높이를
  안 맞추기 때문이다.

**검증**
```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q tests\test_output_session.py
.\.venv\Scripts\python.exe tools\screenshot.py --out docs\screenshots\after-1A
```
`test_output_session.py` 가 `ThemeManager` 를 직접 쓰는 유일한 테스트다(§4.2).

**완료 기준**
- [ ] `pytest tests` 결과가 **428 passed, 0 failed**
- [ ] 다크 캡처에서 표면 5단계가 육안으로 구분된다
- [ ] 라이트 캡처에서 잘린 글자·안 보이는 글자가 없다

---

### Phase 1B — main_window.py 인라인 색 제거

**목표**: `main_window.py` 에 박힌 색을 테마 속성으로 옮긴다.

**변경 파일**: `app/gui/main_window.py`, `tests/test_status_bar.py`,
`tests/test_model_selection.py`

| # | 할 일 | 위치 | 확인 |
|---|---|---|---|
| 1B-1 | **`_LEVEL_QSS` 를 role 기반으로** | `:82-86`, `:89-96` | `_paint_usage` 가 `setProperty("role", …)` 호출. §6.5 |
| 1B-2 | `_set_status` 시그니처 변경 | `:377` | `color: str` → `level: str` |
| 1B-3 | `_set_status` 본문 변경 | `:384` | `setStyleSheet(f"color:{color};")` → `setProperty("role", level)` |
| 1B-4 | `_set_status` 호출부 3곳 수정 | `:408`, `:418`, `:429` | `"#ffd93d"`→`"warn"`, `"#6bcf7f"`→`"ok"` (§6.2.1) |
| 1B-5 | `_BAD_COLOR` / `_BAD_QSS` → 함수화 | `:64-65`, 사용처 `:1420`,`:1424`,`:1676`,`:1693` | §6.4. `colors["error"]` 를 넘겨 받는다 |
| 1B-6 | 설치된 모델의 정상 글자색 동적화 | `:1690` | `QColor(colors["on-surface"])` (§6.4) |
| 1B-7 | `_toggle_theme()` 에 콤보 재색칠 추가 | `:952-955` | §6.4. `_refresh_combo_state()` 를 키마다 다시 부른다 |
| 1B-8 | `ModelInfoPanel` 라벨 role 부여 | `:271`, `:282` | `role="secondary"` |
| 1B-9 | 구분선 2곳 role 부여 | `:305`, `:712` | `role="divider"`. **`color:` 로 쓴다** (§6.4.1) |
| 1B-10 | 앱 타이틀 role 부여 | `:480` | `role="headline"` (24px) |
| 1B-11 | 부제 role 부여 | `:482` | `role="subtitle"`. **지금엔 인라인이 없다** — §5.6 요구사항 |
| 1B-12 | `comfy_label` role 3분 | `:486`, `:1166` | `comfy-pending` / `comfy-on` / `comfy-off` |
| 1B-13 | `status_banner` role | `:498` | `role="warning"` |
| 1B-14 | `_model_warning` role | `:638` | `role="danger"` |
| 1B-15 | `enhancer_warning` role | `:862` | `role="danger"` |
| 1B-16 | `_field()` 보조라벨 role | `:882` | `role="label"` |
| 1B-17 | `preview` role | `:936` | `role="preview"` — 배경 명시 필수 (§9 주의) |
| 1B-18 | LoRA 보조라벨 role | `:1822` | `role="label"` |
| 1B-19 | **깨지는 테스트 수정** | `test_status_bar.py:22,36,49` / `test_model_selection.py:1030` | §10.2 표 그대로 |
| 1B-20 | 간격 4dp 정렬 | `:476`(6), `:479`(10), `:556,643`(4), `:242`(3), `:900`(2) | §4.6. 1 은 M3 Dense 관례상 유지 |

**⚠ 주의**
- 1B-1 을 하면 `test_status_bar.py:22` 의 `import _LEVEL_QSS` 가 깨진다.
  import 를 없애고 `label.property("role")` 로 단언하도록 **함께** 고친다.
- 1B-5 를 1B-7 까지 안 하면 **라이트 테마에서 빨간색이 다크 값으로 남는다.**
  1B-5 와 1B-7 은 한 커밋에서 끝낸다.
- 1B-1 / 1B-3 은 이미 떠 있는 라벨의 속성을 바꾼다. §6.2.1 의
  `unpolish/polish` 호출이 필요한지 확인한다(타이머로 주기적으로 칠해지는
  라벨은 매번 새로 칠해지므로 불필요하다).

**검증**
```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q tests\test_status_bar.py tests\test_model_selection.py
.\.venv\Scripts\python.exe tools\screenshot.py --out docs\screenshots\after-1B
```

**완료 기준**
- [ ] 위 테스트 2개 통과
- [ ] **테마를 여러 번 토글해도** 빨간색·파란색이 이전 값에 고정되지 않는다
- [ ] 라이트 캡처에 `#a0a0a0` 계열이 없다

---

### Phase 1C — 나머지 창도 테마를 받게 한다

**목표**: `session_browser.py` 와 `import_dialog.py` 를 테마에 맞춘다.

**변경 파일**: `app/gui/session_browser.py`, `app/gui/import_dialog.py`,
`tests/test_import_dialog.py`, `tests/test_history_browser.py`

| # | 할 일 | 위치 | 확인 |
|---|---|---|---|
| 1C-1 | **QDialog 자체 스타일시트 삭제** | `import_dialog.py:73` | §3.3. 안 지우면 이 Phase 전체가 무의미 |
| 1C-2 | `_STYLE` 단계 색을 토큰 기반으로 | `import_dialog.py:29-32` | §6.3. 리터럴 4개 제거 |
| 1C-3 | `file_label` role | `import_dialog.py:90` | `role="secondary"` |
| 1C-4 | `report_view` HTML 색 조립 | `import_dialog.py:102-103` | §6.3 (i) — 초기 안내문 |
| 1C-5 | `hint` role | `import_dialog.py:128` | `role="danger"` |
| 1C-6 | `_STYLE` 기본값 토큰화 | `import_dialog.py:148` | 리터럴 제거 |
| 1C-7 | 보고서 HTML 색 조립 | `import_dialog.py:153`,`:159`,`:165` | §6.3 (i) 또는 (ii) |
| 1C-8 | 오류 HTML 색 조립 | `import_dialog.py:237` | §6.3 (i) |
| 1C-9 | `QTextBrowser` 기본 스타일시트 | `import_dialog.py:98` | `document().setDefaultStyleSheet(...)` — §6.3 (ii) |
| 1C-10 | **`image_preview` role** | `session_browser.py:161` | `role="preview"`. 리터럴 3개 제거 |
| 1C-11 | GUI 테스트 2종 확인 | `test_import_dialog.py`(다이얼로그 5곳), `test_history_browser.py` | 위젯 계층이 바뀌므로 확인 필요 |

**⚠ 주의 — §3.4 리치 텍스트**
`QTextBrowser` 안의 인라인 `style='color:...'` 은 **QSS 선택자로 안 닿는다.**
1C-4/1C-7/1C-8 을 (i) 로 처리하면 **다이얼로그를 열 때마다 HTML 을 다시
조립해야** 테마 전환이 반영된다. 다이얼로그는 `QDialog` 라 메인창과
수명 주기가 달라 캐시만으로 못 푼다 → `ThemeManager` 에 시그널을 하나
추가하고 다이얼로그가 구독하도록 한다.

**검증**
```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q tests\test_import_dialog.py tests\test_history_browser.py
.\.venv\Scripts\python.exe tools\screenshot.py --out docs\screenshots\after-1C --include-dialog
```

**완료 기준**
- [ ] `pytest tests` 결과가 **428 passed, 0 failed**
- [ ] `app/gui/` 에 `#[0-9a-fA-F]{3,8}` 리터럴이 **0건**
- [ ] 가져오기 다이얼로그가 라이트/다크 모두에서 읽힌다
- [ ] History 탭 이미지 프리뷰가 라이트 테마에서 흰 상자 안이 아니다

---

### Phase 2 — 타이포그래피

**목표**: 임의로 흩어진 `11px`/`12px`/`18px` 를 M3 타입 스케일로 모은다.

**변경 파일**: `app/gui/theme/manager.py`

| # | 할 일 | 위치 | 확인 |
|---|---|---|---|
| 2-1 | 폰트 스택 교체 | `manager.py:113` | §4.4 |
| 2-2 | title-medium 을 GroupBox 제목에 | `manager.py:116-127` | 16px / weight 500 |
| 2-3 | headline-small 을 앱 타이틀에 | role="headline" 규칙 | 24px / weight **400** (700 아님) |
| 2-4 | body-small 을 보조 설명에 | role="warning", role="subtitle" | 12px |
| 2-5 | label-small 을 보조 라벨에 | role="label" | 11px / weight 500 |
| 2-6 | title-small 을 버튼에 | `QPushButton` | 14px / weight 500 |
| 2-7 | `line-height` 근사 | 레이아웃 `setSpacing` (§4.6) | QSS로 불가 |
| 2-8 | 자간 적용 (선택) | `QFont.setLetterSpacing()` | §4.3 의 letter-spacing 열. 필요한 곳만 |

**검증**
```powershell
Select-String -Path app\gui\*.py -Pattern "font-size:\s*(\d+)px" |
  ForEach-Object { $_.Matches[0].Groups[1].Value } | Sort-Object -Unique
```
출력이 **§4.3 표에 있는 값들만** 나와야 한다.

**완료 기준**
- [ ] 위 출력에 `18px` 가 없다 (24px 로 대체됨)
- [ ] 라이트 캡처에서 제목·보조 라벨 크기가 계층적으로 구분된다

---

### Phase 3 — Elevation + State Layer

**목표**: QSS 로 못 하는 두 가지(그림자·상태층)를 넣는다.

**신규 파일**: `app/gui/theme/elevation.py`
**변경 파일**: `app/gui/theme/manager.py`, `app/gui/theme/state.py`

| # | 할 일 | 위치 | 확인 |
|---|---|---|---|
| 3-1 | `elevation.py` — 효과 부착 헬퍼 | 신규 | §4.7. QFrame 래퍼를 만들어 붙인다 |
| 3-2 | **QPixmap 자손 검사에 실패** | `elevation.py` | §3.1. 썸네일 트리·프리뷰에 걸면 매 프레임 재드로잉 |
| 3-3 | 카드 resting elevation 0 / hover 1 | `manager.py` hover 규칙 | §4.7 |
| 3-4 | Dialog elevation 1 | `QMessageBox` | §5.9 |
| 3-5 | state layer 명부도 확장 | `state.py` | §4.8 표를 전부 함수로 |
| 3-6 | hover/pressed 에 state layer 적용 | `manager.py` | 버튼·리스트·탭 |

**⚠ 주의 — §3.1 함정**
`QGraphicsDropShadowEffect` 는 **자식이 있는 위젯에 안 먹는다.**
GroupBox 를 그대로 효과 대상으로 지정하지 말고, 자식 없는 QFrame 한 겹을
감싼 뒤 거기에 붙인다.

**⚠ 주의 — §3.1 v2.0**
`session_browser.py:257-277` 이 History 트리에 QPixmap 썸네일을 행마다 넣는다.
트리·History 탭·splitter 어딘가에도 효과를 붙이지 않는다.

**검증**
```powershell
.\.venv\Scripts\python.exe tools\screenshot.py --out docs\screenshots\after-3 --state hover
```
호버 상태는 자동 캡처가 안 되므로, 하네스에
`--state hover` 옵션을 넣고 특정 카드 위에 마우스를 올린 채 `grab()` 한다.

**완료 기준**
- [ ] 카드 hover 시 그림자가 보인다 (수동 확인 포함)
- [ ] 라이트 테마에서 이미지·텍스트가 깨지지 않는다
- [ ] **History 탭 스크롤이 이전과 속도가 같다** (QPixmap 재드로잉 없는지)

---

### Phase 4 — Focus Ring + Ripple

**목표**: 키보드 접근성과 클릭 음각을 넣는다.

**신규 파일**: `app/gui/widgets/ripple_button.py` + `app/gui/widgets/__init__.py`
**변경 파일**: `app/gui/main_window.py`, `app/gui/session_browser.py`

| # | 할 일 | 위치 | 확인 |
|---|---|---|---|
| 4-1 | `app/gui/widgets/` 패키지 생성 | 신규 | §8. **현재 디렉터리 자체가 없다** |
| 4-2 | focus ring — QSS `:focus` 로 먼저 시도 | `manager.py` | §5.1 상태 표. 불안정하면 4-3 |
| 4-3 | focus ring — `paintEvent` 커스텀 | `ripple_button.py` | 4-2 가 안 됐을 때만 |
| 4-4 | ripple 오버레이 위젯 | `ripple_button.py` | `QGraphicsOpacityEffect` + 원형 그리기 |
| 4-5 | `QPropertyAnimation` 150ms `OutCubic` | `ripple_button.py` | §4.9 |
| 4-6 | **오버레이 색을 role 로 받기** | `ripple_button.py` | 위젯이 `get_colors()` 를 직접 부르면 안 된다 |
| 4-7 | 16개 버튼에 적용 | §5.1 표 전체 | 누락 없이 |

**검증**: 자동 검지가 어렵다. §10.4 수동 체크리스트를 그대로 수행한다.

**완료 기준**
- [ ] Tab 키로 이동하면 포커스가 보인다
- [ ] 버튼을 누르면 ripple 이 퍼진다
- [ ] **테마를 바꾼 뒤에도** ripple 색이 맞는다 (4-6 검증)

---

### Phase 5 — 선택적 다듬기

**목표**: 완성도를 높이는 선택 사항. 없어도 §12 를 채울 수 있다.

| # | 할 일 | 판단 기준 |
|---|---|---|
| 5-1 | Roboto / Noto Sans KR 폰트 동봉 | **파일 추가라 승인 필요.** Windows 기본이 Malgun Gothic 이라 실익이 적다 |
| 5-2 | Material Symbols 아이콘 폰트 | 현재 아이콘이 없다. 도입 시 버튼 라벨 구조가 바뀐다 |
| 5-3 | 고대비 테마 추가 | Phase 1 이 안정된 뒤에. §1 비범위 |

**완료 기준**: 자체 판단.

---

## 8. 신규 파일 목록

| 파일 | Phase | 역할 |
|---|---|---|
| `app/gui/theme/elevation.py` | 3 | elevation 힌지 |
| `app/gui/theme/state.py` | **1A** | HEX→rgba 변환 + state layer 색 계산 |
| `tools/screenshot.py` | 0 | 오프스크린 스크린샷 캡처 — **v1.0 누락** |
| `docs/screenshots/` | 0 | 캡처 보관 폴더 |

**Phase 4 에서 추가될 수 있는 파일**

| 파일 | 역할 |
|---|---|
| `app/gui/widgets/__init__.py` | 패키지 생성 — **현재 디렉터리 자체가 없다** |
| `app/gui/widgets/ripple_button.py` | ripple QPushButton |

> `app/gui/widgets/` 를 새로 만드는 것이 목표는 아니다. Phase 4 를 하지
> 않으면 이 둘은 만들지 않는다.

---

## 9. 리스크와 대응

| # | 리스크 | 영향 | 대응 |
|---|---|---|---|
| R1 | `QWidget` 전역 배경 제거 후 투명 위젯 깨짐 | 중간 | Phase 1A 를 다크 → 확인 → 라이트 순으로 나눠 적용 |
| R2 | elevation 가 자식 위젯에 안 그려짐 | 낮음 | §3.1 래퍼 규칙 준수 |
| R3 | 색상 대비 부족 (다크 `surface` vs `surface-container-low` 가 1단계 차이) | 중간 | `surface-container` 상위 사용 검토, 대비 확인 후 확정 |
| R4 | QSS `line-height` / `letter-spacing` 미지원 | 낮음 | 레이아웃 간격으로 근사, 자간은 코드 |
| R5 | 상태 rgba 계산을 잘못해 라이트 테마에서 글자가 안 보임 | **높음** | Phase 3 을 Phase 1 과 **분리**해 독립 검증 |
| R6 | ripple 이 QSS 와 충돌 | 중간 | ripple 오버레이는 `QGraphicsOpacityEffect` 로 그려 QSS 를 건드리지 않음 |
| R7 | 동시 작업으로 코드 충돌 | **높음** | **Phase 착수 전 `git status` 확인.** 이미 다른 세션이 파일을 수정 중이었던 이력이 있다 |
| R8 | **v2.0 신규** — `import_dialog.py:73` 위젯 레벨 스타일시트를 빼먹으면 창 전체가 테마를 안 받음 | **높음** | Phase 1C-1 로 **첫 번째 항목**으로 둔다 |
| R9 | **v2.0 신규** — `_BAD_COLOR`/`_BAD_QSS` 를 상수로 두면 라이트 테마에서 빨간색이 다크 값으로 남음 | 중간 | §6.4 함수화. 1B-5 와 1B-7 을 한 커밋에서 |
| R10 | **v2.0 신규** — `QTextBrowser` HTML 색을 (A) 방식으로만 처리하려 하면 제거 불가 | 중간 | §6.3 별도 처방 + 테마 시그널 |
| R11 | **v2.0 신규** — History 트리 썸네일(`session_browser.py:257-277`)에 elevation 이 붙으면 매 프레임 재드로잉 | 중간 | §3.1 v2.0 확대 규칙. QPixmap 자손 금지 |
| R12 | **v2.0 신규** — `self.neg` 의 `setFixedHeight(46)`(`main_window.py:868`)에 Filled 필드 밑줄이 안 들어감 | 낮음 | Phase 1A 에서 눈 확인, 필요 시 `sizeHint` 기반으로 변경 |
| R13 | **v2.0 신규** — §5.10 위젯 7종을 빼면 "일부만 테마 적용" | 중간 | Phase 1A-13, 1A-14 로 명시 |
| R14 | **v2.0 신규** — 구분선(`QFrame` HLine)을 `border-color` 로 바꾸면 조용히 안 먹는다 | 낮음 | 실측 결과 `color:` 가 통한다(§6.4.1) |
| R15 | **v2.0 신규** — 이미 화면에 나온 위젯에 `setProperty` 하면 스타일 반영이 늦는다 | 낮음 | §6.2.1. `unpolish/polish` 필요 시 함께 호출 |
| R16 | **v2.0 신규** — `role` 속성을 화면에 나온 뒤 바꾸면 이전 role 규칙이 남는다 | 낮음 | `setProperty` 는 덮어쓰지만, 필요 시 `style().unpolish/polish` |

---

## 10. 검증 방법

### 10.1 자동

```powershell
$env:PYTHONDONTWRITEBYTECODE=1
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q tests
```

**v2.0 기준선 (2026-10-05 직접 실행 확인)**

| 범위 | 결과 |
|---|---|
| **전체 (`tests/`)** | **423 passed, 5 failed** in 147.26s (총 428건) |
| `tests/` 중 `test_non_blocking_refresh.py` 제외 | 422 passed |
| Phase 0-6 을 끝낸 뒤 목표 | **428 passed, 0 failed** |

> **`test_non_blocking_refresh.py` 의 5건은 현재 실패 중이다.**
> 원인은 `FileNotFoundError: workflows\qwen-image-2.1-baseline.json`
> (`tests/test_non_blocking_refresh.py:64`) — **존재하지 않는 워크플로
> 파일을 참조하는 오래된 테스트**다. `workflows/` 에는
> `qwen-image-2.1.json` 만 있다.
> **UI 변경과 무관한 사전 실패**이므로 Phase 0-6 에서 먼저 없앤다.
> → 그 뒤 회귀 판정식: **실패 0건.** 하나라도 생기면 Phase 실패.

### 10.2 v2.0 신규 — **깨지는 기존 테스트 (반드시 먼저 수정)**

v1.0은 새 테스트만 적었고 **기존 테스트가 깨진다는 사실을 안 적었다.**
다음 테스트는 하드코딩 색상 값을 직접 단언하므로 **Phase 1B 토큰 교체와
같이 수정해야 한다.**

| 테스트 | 현재 단언 | 문제 | 수정 |
|---|---|---|---|
| `tests/test_status_bar.py:22` | `from app.gui.main_window import _LEVEL_QSS, _paint_usage` | §6.5 로 `_LEVEL_QSS` 를 없애면 import 실패 | import 를 `_paint_usage` 만으로 줄인다 |
| `tests/test_status_bar.py:36` | `assert "ffd93d" in label.styleSheet()` | M3 warning = tertiary `#EFB8C8` | `label.property("role") == "warn"` 로 바꾼다 |
| `tests/test_status_bar.py:43` | `assert label.styleSheet() == ""` | OK 단계는 role="ok" 로 바뀐다 | `label.property("role") == "ok"` 로 바꾼다 |
| `tests/test_status_bar.py:49` | `assert "ff6b6b" in label.styleSheet()` | M3 danger = error `#F2B8B5` | `label.property("role") == "danger"` 로 바꾼다 |
| `tests/test_status_bar.py:57` | `assert label.styleSheet() == ""` (OK 복귀) | 위와 같은 이유 | `label.property("role") == "ok"` |
| `tests/test_status_bar.py:63` | `assert level in _LEVEL_QSS` | 상수 제거 | `_paint_usage` 호출 후 role 확인으로 대체 |
| `tests/test_status_bar.py:67` | `_LEVEL_QSS[WARN] != _LEVEL_QSS[DANGER]` | 상수 제거 | role 문자열이 다른지 단언 |
| `tests/test_model_selection.py:1030` | `RED in combo.styleSheet().lower()` | `_BAD_COLOR` 가 `error`(`#F2B8B5`)로 바뀜 | `colors["error"]` 를 `ThemeManager` 에서 가져와 비교 |

> **`test_status_bar.py` 는 13곳이 `MainWindow` 를 생성**하고
> `test_model_selection.py` 는 3곳, `test_import_dialog.py` 는 5곳이
> `ImportWorkflowDialog` 를 생성한다. GUI 구조 변경(§5.10, §6.2)에
> 따라 **위젯 계층이 바뀌면 이 테스트들이 추가로 깨질 수 있다.**
> 각 Phase 완료 후 전체를 다시 돌려 확인한다.

### 10.3 추가할 테스트

| 테스트 | 확인 내용 | Phase |
|---|---|---|
| `test_theme_has_m3_roles` | M3 토큰이 모두 존재 | 1A |
| `test_qss_generates_without_error` | `_generate_qss()` 가 예외 없이 문자열 생성 | 1A |
| `test_qss_covers_all_widget_classes` | §5.10 위젯 7종이 QSS에 포함됨 | 1A |
| `test_no_inline_hardcoded_color` | `main_window.py` / `session_browser.py` / `import_dialog.py` 에 `#hex` 리터럴 **0건** | 1C |
| `test_theme_toggle_repaints_dynamic_colors` | 테마 전환 후 콤보의 빨간색이 새 토큰을 따른다 | 1B |
| `test_light_theme_has_no_dark_colors` | light 팔레트에 밝은/어두픈 값 섞이지 않음 | 1A |

`test_no_inline_hardcoded_color` 는 **회귀를 실제로 막는 핵심 테스트**다.
§6 이 되돌아가는 것을 막는다.

> **v1.0 모순 해소**: v1.0은 §12에서 "하드코딩 색상 리터럴 0건"을
> 완료 기준으로 두면서 §6.1 (A) 방식만 제시했다. 하지만 §3.4의
> 리치 텍스트 HTML 은 (A)로 제거 불가하다. v2.0은 §6.3 처방을
> 추가해 **DoD와 방법이 일치**하도록 했다.

### 10.4 수동 (눈 확인)

Phase 마다 아래를 캡처해 비교한다.

- [ ] 다크 × (Generate / Model / History) = 3장
- [ ] 라이트 × 3탭 = 3장
- [ ] 최소 창 크기(900×700) 1장 — `main_window.py:439` `setMinimumSize(900, 700)`
- [ ] 포커스 이동 시 focus ring
- [ ] 삭제 확인 dialog
- [ ] **v2.0 신규** — 가져오기 다이얼로그 (라이트/다크) 각 1장
- [ ] **v2.0 신규** — Model 탭 워크플로 목록(라이트/다크)
- [ ] **v2.0 신규** — 테마를 3회 연속 토글한 뒤 상태 (문자열 누적 버그 확인)

---

## 11. 되돌리기

- Phase 1A~4 는 각각 **단일 커밋**으로 끝낸다. 메시지는 Conventional Commits(`refactor(gui): …`, `feat(gui): …`).
- 되돌리기는 `git revert <commit>` 로 Phase 단위가 가능하다.
- `git branch ui-material-3` 에서 작업하고, 검증 후에만 기본 브랜치에 병합한다.
- **Phase 1A 를 되돌리면 1B/1C 도 같이 되돌려야 한다.** 1B/1C 는 1A 가 정의한
  role QSS 를 전제로 하므로 단독으로 되돌리면 role 규칙이 없는 상태가 된다.

---

## 12. 완료 기준 (Definition of Done)

- [ ] 다크/라이트 테마 모두 M3 Baseline 팔레트를 사용한다
- [ ] 하드코딩 색상 리터럴이 `app/gui/` 에 **0건**
- [ ] 테마 전환 시 모든 위젯의 색이 함께 바뀐다 (인라인 잔존 없음)
- [ ] **테마 전환 시 `_BAD_QSS`(설치 안 된 모델 빨간색)와 상태 단계 색도 바뀐다** (§6.4, §6.5)
- [ ] GroupBox 가 테두리 없이 표면색 차이로 구분된다
- [ ] `그려줘` 버튼만 Filled(색이 채워짐)로 강조된다
- [ ] 리스트 선택 색이 `secondary-container` 다
- [ ] 상태바가 사용률만 표시하고, 타이틀바가 기기 정보를 표시한다
- [ ] 모든 글자 크기가 §4.3 타입 스케일에 속한다
- [ ] 간격이 4dp 그리드에 속한다
- [ ] **§5.10 위젯 7종(QListWidget, QSlider, QCheckBox, QScrollBar, QHeaderView, QTextBrowser, 콤보 드롭다운)이 테마를 따른다**
- [ ] Phase 3 이상 완료 시 카드 hover 시 elevation 이 있고 상태층이 보인다
- [ ] Phase 4 이상 완료 시 focus ring 과 ripple 이 동작한다
- [ ] 최소 창 크기(900×700)에서 레이아웃이 깨지지 않는다
- [ ] `pytest tests` 결과가 **428 passed, 0 failed** (사전 실패 5건 해소 포함)
- [ ] 스크린샷 9장 이상 확보 (before 9장 + after 각 Phase)

---

## 13. 참고

- Material Design 3 공식 문서: <https://m3.material.io/>
- Material Theme Builder(팔레트 생성·검증): <https://material-foundation.github.io/material-theme-builder/>
- 색상 토큰 전체 목록: <https://m3.material.io/styles/color/system/overview>
- 타이포그래피 스케일: <https://m3.material.io/styles/typography/overview>
- elevation 규칙: <https://m3.material.io/styles/elevation/overview>
- Qt 스타일시트 참조: <https://doc.qt.io/qt-6/stylesheet-reference.html>

---

## 14. v1.0 오류 정정 목록 (감사 추적)

v1.0(2026-10-02)과 실제 코드(2026-10-04 기준)의 차이. **v2.0에서 모두 수정했다.**

| # | v1.0 기재 | 실제 | v2.0 조치 |
|---|---|---|---|
| 1 | §2.2 "총 10곳" | 33줄 / 36 리터럴 | §6.2 전체 인벤토리 |
| 2 | §1 범위에 `import_dialog.py` 없음 | 313줄, 색상 13개, **위젯 레벨 스타일시트로 앱 QSS를 가림** | §1, §3.3, §6.2, §6.3, Phase 1C |
| 3 | §10.1 "119건 중 117 passed / 2 failed" | **428건 중 423 passed / 5 failed** | §10.1 |
| 4 | §10.1 "실패 2건 `test_shutdown_*` 은 샌드박스 WinError" | `test_shutdown_*` 파일 자체가 없음. 실제 실패는 `test_non_blocking_refresh.py` 5건(존재하지 않는 워크플로 참조) | §10.1, Phase 0-6 |
| 5 | §12 "baseline(117/2)" | 423 passed / 5 failed → 목표 428/0 | §12 |
| 6 | §8/Phase 5 "`app/gui/widgets/`, `app/gui/pages/` 는 빈 패키지" | **두 디렉터리 모두 존재하지 않음** | Phase 4-1, §8 |
| 7 | §2.5 간격 "1, 4, 6, 10" | 1, 2, 3, 4, 6, 10 | §2.6 |
| 8 | §5.1 버튼 10개 | **16개** | §5.1 전체 표 |
| 9 | §5.2 "model combo 4개" | **개수 고정 없음** — `_rebuild_model_rows()` 가 워크플로마다 재생성 | §5.2 경고 상자 |
| 10 | §4.5 버튼 radius 8px vs §5.1 버튼 radius 20px | **내부 모순** | §4.5 corner-full 통일 |
| 11 | §3.2 버튼 36dp vs §5.1 버튼 높이 40px | **내부 모순** | §3.2 40px 통일 |
| 12 | §5.3 카드 elevation 0 vs §12 "카드에 elevation 있음" | **내부 모순** | §4.7 resting 0 → hover 1 |
| 13 | §2.3/§5 커버 안 된 위젯 미기재 | QListWidget, QSlider, QCheckBox, QScrollBar, QHeaderView, QTextBrowser, 콤보 드롭다운 — **QSS 없음** | §2.3, §5.10, Phase 1A-13 |
| 14 | §10.2 깨지는 기존 테스트 미기재 | `test_status_bar.py` 7곳 + `test_model_selection.py:1030` 이 색상 값을 직접 단언 | §10.2 |
| 15 | §6.1 (A) 방식만 제시 | 리치 텍스트 HTML 은 (A) 불가 | §3.4, §6.3, Phase 1C |
| 16 | `_BAD_COLOR`/`_BAD_QSS` 미기재 | **기능색**이며 모듈 상수라 테마 전환 불가 | §3.5, §6.4, R9 |
| 17 | §3.1 "이미지 프리뷰에 효과 금지" | History 트리 **썸네일 행**도 QPixmap 자손 | §3.1 v2.0 확대, R11 |
| 18 | Phase 0 "스크린샷 캡처" | 캡처 수단이 저장소에 없음 | Phase 0-1 하네스, §8 `tools/screenshot.py` |
| 19 | §4.2 마이그레이션용 매핑 표 | `get_colors()` 외부 소비자 0명 — 호환 계층 불필요 | §4.2 단순화 |
| 20 | 30행, 350행 문자열 깨짐(바이트 손상) | — | 수정 |

### 14.1 v2.0 자체 오류 정정 목록 (자기 검토)

v2.0 초안 작성 후 재검토에서 발견한 것. **수정 완료.**

| # | 초안 기재 | 실제 | 조치 |
|---|---|---|---|
| 1 | 리터럴 21 / 17 / **41** | 기계 집계 **20 / 13 / 36** | §2.2 수정 |
| 2 | `QCheckBox` at `:915` | 915 는 `addWidget`, 생성은 **`:857`** | §2.3 수정 |
| 3 | `QSlider` at `:901, :1823` | 901 은 타입 annotation, **`:1823` 만** | §2.3 수정 |
| 4 | Phase 1 주의에 "라이트 먼저"/"다크 먼저" 공존 | **문단 안에서 충돌** | Phase 1A 주의 수정 |
| 5 | "전체 422 passed" | 제외 실행값. 전체는 **423 passed / 5 failed** | §10.1 수정 |
| 6 | "전체 테스트 통과" | 사전 실패 5건과 모순 | §7·§12 를 "428/0" 으로 |
| 7 | `:1690` 을 '고를 수 없는 값' 색으로 | **설치된 모델의 정상 색** | §6.2·§6.4 수정 |
| 8 | `_BAD_COLOR` 사용처를 "1690 근처"로 뭉뚱 | 실제 **5곳**(1420/1424/1676/1690/1693) | §6.4 전수 표 |
| 9 | 정규식 인벤토리만 제시 | `:384` 처럼 **변수로 스타일을 만드는 곳**을 놓침 | §6.2.1 추가, Phase 1B-3 |
| 10 | Phase 항목이 "§6.2 의 33줄을 이런 방식으로" 수준 | **직접 실행 불가** | §7 전면 재작성(Phase 1A/1B/1C 분리, 줄 단위 작업표) |

---

**문서 끝**
