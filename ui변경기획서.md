# UI 변경기획서 — Google Material Design 3 적용

- **문서 버전**: v1.0
- **작성일**: 2026-10-02
- **대상 코드베이스**: Geuryeojwo-Powered by Geurim-gyeol (v0.2, PySide6 6.6~6.x)
- **목표**: 현재 자체 정의된 어두운 색상 중심 UI를 Google Material Design 3(M3) 기반으로 전면 개편

> 이 문서는 **기획서**다. 코드 변경은 포함하지 않는다.
> 실행 전 반드시 §12(완료 기준)를 기준으로 판정한다.

---

## 1. 범위와 비범위

### 범위(In Scope)

| 대상 | 파일 |
|---|---|
| 테마 색상 정의 | `app/gui/theme/manager.py` |
| QSS 스타일시트 | `app/gui/theme/manager.py` (`_generate_qss`) |
| 인라인 하드코딩 스타일 제거 | `app/gui/main_window.py`, `app/gui/session_browser.py` |
| 간격·여백 4dp 그리드 정렬 | `app/gui/main_window.py`, `app/gui/session_browser.py` |
| elevation / state layer / ripple | 신규 모듈 (Phase 3~4) |

### 비범위(Out of Scope)

- 레이아웃 구조 자체의 변경 (탭 구성, 위젯 배치 순서) — 이미 이번 작업에서 정리된 상태
- 엔진/스토리지/세션 로직
- `ComfyCraft` 등 외부 테마 체계 이식 기록 보존
- 다크/라이트 **외에** 테마 ��대(예: 고대비,、品牌 컬러) — 필요 시 Phase 5 이후 확장

---

## 2. 현재 상태 진단 (As-Is)

### 2.1 색상 체계

`app/gui/theme/manager.py` 의 `THEMES` 는 M3가 아닌 자체 팔레트다.

| 토큰 | 현재 dark | 현재 light | M3 대응 토큰 |
|---|---|---|---|
| `background` | `#1a1a1a` | `#f5f5f5` | `surface` |
| `surface` | `#222222` | `#ffffff` | `surface-container-low` |
| `surface_alt` | `#2a2a2a` | `#f0f0f0` | `surface-container-high` |
| `border` | `#444444` | `#e0e0e0` | `outline-variant` |
| `text` | `#e0e0e0` | `#333333` | `on-surface` |
| `text_secondary` | `#a0a0a0` | `#707070` | `on-surface-variant` |
| `accent` | `#4a9fff` | `#2196F3` | `primary` |
| `accent_hover` | `#6bb0ff` | `#1976D2` | `primary`(state layer) |
| `danger` | `#ff6b6b` | `#f44336` | `error` |
| `warning` | `#ffd93d` | `#FF9800` | *(M3에 warning 없음 → tertiary/error 조합으로 대체 필요)* |
| `success` | `#6bcf7f` | `#4CAF50` | *(M3에 success 없음 → primary로 대체)* |

**핵심 문제 3가지**

1. **토큰이 12개뿐이다.** M3는 기본 20개, 확장( tonal palette )으로 100개 이상이다. `surface-container` 5단계, `primary-container`, `on-*` 쌍이 전부 없다. 이 때문에 "배경"이 한 종류로 뭉개진다.
2. **`QWidget` 에 전역 `background-color` 를 건다.** 이것이 현재 UI가 "모든 것이 같은 회색 판 위의 상자"처럼 보이는 근본 원인이다. M3는 표면의 **높이차(surface tint elevation)** 로 층을 만는데, 전역 배경 지정이 그 구분을 없앤다.
3. **`warning` / `success` 가 M3에 없다.** M3는 `tertiary`(보조 강조)와 `error` 만 갖는다. 임의로 넣은 두 토큰을 그대로 옮기면 M3가 되지 않는다.

### 2.2 하드코딩된 인라인 스타일 (테마 무시 버그)

**이것은 현재 버그다.** Qt에서 위젯 레벨 `setStyleSheet()` 은 애플리케이션 레벨 스타일시트보다 우선한다. 따라서 아래 코드는 라이트 테마로 전환해도 **색이 바뀌지 않는다.**

`app/gui/main_window.py`

| 위치(확인 시점) | 코드 | 문제 |
|---|---|---|
| `_LEVEL_QSS[level]` | `color:#ffd93d;` / `color:#ff6b6b;` | 토큰 미사용, 테마 무시 |
| `ModelInfoPanel._build_ui` | `color:#a0a0a0;` | 토큰 미사용 |
| `build_ui` 타이틀 | `font-size:18px;font-weight:700` | 타입 스케일 무시 |
| `build_ui` comfy_label 초기값 | `color:#7fb3ff;` | 토큰 미사용, 테마 무시 |
| `status_banner` | `color:#ffd93d; font-size:12px;` | 토큰·타입 무시 |
| `_model_warning` | `color:#ff6b6b; font-size:12px;` | 토큰·타입 무시 |
| `_field()` 보조라벨 | `color:#a0a0a0; font-size:11px;` | 토큰·타입 무시 |
| `lora_strength_label` | `color:#a0a0a0; font-size:11px;` | 토큰·타입 무시 |
| `preview` (생성 결과) | `border:1px solid #444` | 토큰 미사용, 라이트에서 진회색 남음 |

`app/gui/session_browser.py`

| 위치 | 코드 | 문제 |
|---|---|---|
| `image_preview` | `border: 1px solid #444; background: #222; color: #888;` | 라이트 테마에서 **어두운 상자**가 그대로 남음 |

→ 총 **10곳**을 반드시 정리해야 한다. 안 하면 "테마 버튼을 눌러도 반만 바뀌는" 상태가 그대로 유지된다.

### 2.3 타이포그래피

`font-size` 는 `14px`(본문), `11px`(보조), `12px`(경고), `18px`(제목) 네 값만 쓰고 **임의로** 흩어져 있다. 행간(line-height)과 자간(tracking) 규칙이 없다. M3 타입 스케일(11단계)과 대응되지 않는다.

폰트 스택은 `'Segoe UI', 'Malgun Gothic', Arial, sans-serif` 다. Roboto·Noto Sans KR 이 없다.

### 2.4 모양(Shape)

`border-radius` 가 `3px`(progressbar chunk), `4px`(button, input, tab), `6px`(groupbox) 로 흩어져 있다. M3 모양 단계(corner scale)와 대응되지 않는다.

### 2.5 간격(Spacing)

`setSpacing(1)`, `4`, `6`, `10` 이 임의로 섞여 있다. M3는 4dp 기본 그리드를 쓴다.

### 2.6 없는 것들 (M3 핵심)

Material 3 를 정의하는 다음 요소가 **하나도 없다.**

- **elevation shadow** — QSS `box-shadow` 미지원
- **state layer** (hover 8% / focus 10% / pressed 10% / dragged 16%) — 미구현
- **ripple** (터치 ripple) — 미구현
- **focus ring** — 미구현 (키보드 접근성 결함)
- **모션/전환** — 미구현
- **터치 타깃 48dp 규칙** — 현재 버튼 높이 약 31px (14px 폰트 + padding 6px×2 + border 2px)

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

이 효과는 **자식이 있는 위젯에 정상 적용되지 않는다.** 효과가 위젯 자체의 pixmap 에 걸리는데, 자식이 그 위에 별도로 그려지기 때문에 그림자가 가려지거나 아예 나타나지 않는다.

- **대응**: 효과를 걸 대상은 항상 **자식이 없는 컨테이너(QFrame)** 로 한 겹 감싼다. 그룹박스를 그대로 효과 대상에 지정하지 않는다.
- **성능**: 이미지 프리뷰(큰 pixmap)에는 효과를 걸지 않는다. 드로잉 비용이 프레임마다 발생한다.

### 3.2 데스크톱에서의 M3 (M3 Express)

M3는 터치 기기 밀도로 설계됐다. 이 앱은 데스크톱이다.

| 규칙 | 터치 | 이 앱 적용값 | 이유 |
|---|---|---|---|
| 터치 타깃 | 48dp | **36dp** (버튼), **40dp** (탭) | 마우스 조작이 주라 48dp는 지나치게 큼 |
| elevation | 0~5단계 | **0~2단계만 사용** | 데스크톱 M3 Express 규칙 |
| 모션 | 200~500ms | **150~250ms** | 지연감이 체감됨 |

**이 적용값은 M3가 아니라 M3의 데스크톱 확장이며, 그 점을 문서화해 둔다.**

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

### 4.2 기존 토큰 → M3 토큰 매핑 (마이그레이션용)

코드에서 기존 키를 쓰는 곳이 있다면 이 표로 옮긴다.

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
> `_paint_usage()` 의 `UsageLevel.OK/WARN/DANGER` 3단계는 M3의 `primary/tertiary/error` 3색 구조와 정확히 대응하므로 그대로 유지한다.

### 4.3 타이포그래피 스케일

Roboto 기준 M3 타입 스케일을 이 앱에 필요한 항목만 추린다.

| 스타일 | font-size | line-height | weight | letter-spacing | 이 앱 용도 |
|---|---|---|---|---|---|
| headline-small | 24px | 32px | 400 | 0 | 앱 타이틀 "그려줘 v0.2" |
| title-large | 22px | 28px | 400 | 0 | (예비) |
| title-medium | 16px | 24px | 500 | 0.15px | GroupBox 제목 |
| title-small | 14px | 20px | 500 | 0.1px | 버튼 |
| body-large | 16px | 24px | 0.5px | 0 | 프롬프트 입력창, 로그 |
| body-medium | 14px | 20px | 0.25px | 0 | 상태바, 목록 본문 |
| body-small | 12px | 16px | 0.4px | 0 | 보조 설명 |
| label-large | 14px | 20px | 500 | 0.1px | 입력 필드 라벨 |
| label-medium | 12px | 16px | 500 | 0.5px | 보조 라벨 (W/H/Steps 등) |
| label-small | 11px | 16px | 500 | 0.5px | 최소 크기 라벨 |

**QSS 제약**: Qt의 `font-size` 는 `px` 만 받는다. `line-height` 와 `letter-spacing` 은 **QSS로 제어 불가**. 行간은 레이아웃 `setSpacing()` 으로, 자간은 필요 시 `QFont.setLetterSpacing()` 을 코드에서 적용한다. 이 두 항목은 **CSS 그대로 옮길 수 없다**는 점을 구현 시 유의한다.

### 4.4 폰트 스택

```css
font-family: 'Roboto', 'Noto Sans KR', 'Segoe UI Variable Text', 'Malgun Gothic', 'Segoe UI', sans-serif;
```

- Roboto / Noto Sans KR 은 시스템에 없을 수 있다. 없어도 뒤의 폰트로 자연스럽게 폴백한다( degrades gracefully ).
- 리본은 무시하고 시스템 폰트를 쓴다. 폰트 파일 동봉은 파일 추가로 이어지므로 **선택 사항**으로 둔다(§8 Phase 5).
- 한글은 `Malgun Gothic`(Windows 기본)이 가장 안정적이다.

### 4.5 모양(Shape) 스케일

| 토큰 | radius | 적용 대상 |
|---|---|---|
| corner-none | 0px | 이미지 프리뷰, progressbar chunk |
| corner-extra-small | 4px | progressbar chunk, 체크박스 |
| corner-small | 8px | 버튼, 입력 필드, combo |
| corner-medium | 12px | 카드, dialog |
| corner-large | 16px | GroupBox (카드 역할) |
| corner-extra-large | 28px | (미사용) |

### 4.6 간격(Spacing) — 4dp 그리드

| 토큰 | 값 | 적용 |
|---|---|---|
| space-1 | 4px | 아이콘↔라벨, 필드 내부 |
| space-2 | 8px | 라벨↔필드, 버튼 간격 |
| space-3 | 12px | GroupBox 내부 여백 |
| space-4 | 16px | GroupBox 간격, 카드 여백 |
| space-6 | 24px | 섹션 간격 |
| space-8 | 32px | 대区块 |

현재 쓰이는 `1`, `6`, `10` 은 위 스케일로 흡수한다. `1px` 은 M3에 없지만 M3 Dense 관례상 유지 가능하다(라벨 위아래 미세 간격).

### 4.7 Elevation (Phase 3)

| 레벨 | dp | blur-radius | y-offset | 용도 |
|---|---|---|---|---|
| 0 | 0 | — | — | 페이지 배경, 카드 기본 |
| 1 | 1 | 3 | 1 | resting 카드, dialog |
| 2 | 3 | 6 | 2 | hover 상태 카드 |

> M3 elevation 은 2겹 그림자(base + tint)지만 Qt 는 단일 `QGraphicsDropShadowEffect` 다.
> base 그림자 + 상위 오버레이로 근사한다. **근사임을 주석으로 남긴다.**

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

테마별로 on-surface 의 RGB 가 다르므로 **토큰 문자열 치환이 아니라 계산된 rgba 를 넣어야 한다.** `get_colors()` 가 HEX만 주므로 헬퍼가 필요하다.

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

**M3**: 버튼은 3종으로 나눈다.

| 종류 | M3 이름 | 구현 |
|---|---|---|
| 주 액션 | Filled Button | `background: primary` / `color: on-primary` / radius 20px(필 Full) / height 40px |
| 보조 | Outlined Button | `background: transparent` / `border: 1px solid outline` / `color: on-surface` / radius 20px / height 40px |
| 경량 | Text Button | 배경·테두리 없음 / `color: primary` / padding만 8×12 |

**이 앱 적용안**

| 버튼 | 종류 |
|---|---|
| `그려줘` (generate) | **Filled Button** — 유일한 주 액션 |
| `중지` (cancel) | **Outlined Button** (또는 생성 중일 때만 Filled error) |
| `새로고침` (refresh, Generate 탭) | Text Button |
| `상태 새로고침`, `테마` (타이틀바) | Text Button |
| `폴더 열기`, `다른 이름으로 저장`, `Prompt 복사`, `재생성` | Outlined Button |
| `삭제` | **Outlined + error 색상** — 파괴 동작임을 색으로 알림 |

> **모두 같은 스타일로 두면 "무엇이 중요한 행동인지" 알 수 없다.** 지금처럼 전부 동일한 회색 버튼이면 사용자가 매번 읽어야 한다. `그려줘` 만 색을 칠하는 것��� M3의 가장 값싼 개선이다.

**상태**
```css
QPushButton:hover   { background: <overlay 8%>; }
QPushButton:pressed { background: <overlay 10%>; }
QPushButton:disabled{ color: rgba(...,0.38); background: transparent; }
QPushButton:focus   { outline: 2px solid primary; outline-offset: 2px; }  /* QSS 제약으로 불안정 → Phase 4에서 커스텀 paint */
```

### 5.2 입력 필드 (QTextEdit / QLineEdit / QComboBox / QSpinBox)

**현재**: surface 배경 + 1px border + 4px radius + padding 4×8

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
**프롬프트·Negative(여러 줄)만 Filled**, 파라미터 숫자 입력과 combo 는 **Outlined** 로 두는 편이 낫다.

- 프롬프트 / Negative → Filled (여백이 크고 입력량이 많다)
- W / H / Steps / CFG / Seed / Sampler / Scheduler / LoRA → Outlined
- model combo 4개 → Outlined

### 5.3 GroupBox

**현재**: 1px border + 6px radius + 제목에 `accent` 색

**M3 Card**

| 항목 | 다크 | 라이트 |
|---|---|---|
| 배경 | `surface-container-low` | `surface-container-low` |
| radius | 16px | 16px |
| elevation | 0 (resting) | 0 |
| 제목 색 | `on-surface` | `on-surface` |
| 제목 크기 | title-medium (16px/500) | 동일 |
| 내부 여백 | 16px (`space-4`) | 16px |
| 구분선 | **없음** (배경 차이로 구분) | 동일 |

**현재 GroupBox 의 1px 테두리는 M3에 없다.** 테두리 대신 표면색 차이로 영역을 구분한다. 이를 적용하면 화면이 훨씬 현대적으로 보인다.

단, **`surface-container-low` 과 `surface` 의 대비가 미묘할 수 있다**(dark: `#1D1B20` vs `#1C1B1F`, 차이 1단계). 이때는 `surface-container`(`#211F26`)를 쓴다.

### 5.4 탭 (QTabWidget)

**현재**: 닫힌 탭 = surface + border, 선택된 탭 = accent 배경 + background 글자 (알약 모양)

**M3 Primary Tabs**

| 항목 | 값 |
|---|---|
| 활성 탭 글자 | `on-surface` + **font-weight 500** |
| 비활성 탭 글자 | `on-surface-variant` |
| 활성 표시 | 탭 아래 3px `primary` 인디케이터 |
| 비활성 표시 | 1px `outline-variant` 인디케이터 |
| 탭 최소 높이 | 48px (M3) → 이 앱 **40px** (M3 Express) |
| 패딩 | 수평 16px |

**구현상 주의**: QSS `QTabBar::tab:selected` 로 **인디케이터 바**를 그릴 수 없다. 가능한 우회:

- (a) `border-bottom: 3px solid primary` 를 활성 탭에 적용 — 단순하고 충분히 M3에 가까움
- (b) `QTabBar` 를 `paintEvent` 로 재정의해 인디케이터를 직접 그리기 — 정확하지만 코드 증가

**Phase 1에서는 (a) 로 시작한다.** 시각적 차이는 작고 위험은 0이다.

> 이미 사용 중인 `setCornerWidget(Qt.TopRightCorner)`(워크플로 선택기)는 그대로 유지한다. M3 탭과 충돌하지 않고, 폭 경쟁 문제도 해결된 상태다.

### 5.5 상태바

**현재**: `RAM 58% | CPU 13% | VRAM 14% | GPU 7%` — 라벨 나열

**M3 적용안**
- 배경: `surface-container-low`
- 위쪽 1px `outline-variant` 구분선
- 본문: label-medium(12px/500), 색 `on-surface-variant`
- 값이 임계치를 넘으면 `error`(DANGER), 주의는 `tertiary`(WARN) — **현재 `_paint_usage()` 구조 유지**
- 세로 가운데 정렬, 좌우 여백 16px

### 5.6 제목바(상단 행)

**현재**: 앱 타이틀(18px bold) + 부제 + `comfy_label` + 버튼 2개

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

**현재** chunk가 3px radius라 트랙(4px)과 어긋난다. 둘 다 4px로 통일.

### 5.8 리스트/트리 (History 탭)

| 항목 | 값 |
|---|---|
| 배경 | `surface` |
| 행 높이 | 40px (썸네일 40px와 일치) |
| hover | `surface-container-low` |
| 선택 | `secondary-container` + `on-secondary-container` |

> **선택 색을 `primary` → `secondary-container` 로 바꾸는 것이 M3다.** `primary` 배경 + `background` 글자는 M3가 아니며 대비도 나쁘다(보조 텍스트가 읽히지 않는다).

### 5.9 Dialog (삭제 확인)

| 항목 | 값 |
|---|---|
| 배경 | `surface-container-high` |
| radius | 28px (corner-extra-large) |
| elevation | 1 (3dp) |
| 본문 | body-medium(14px) |
| 버튼 | Text Button 2개(취소 / 확인) |

---

## 6. 인라인 스타일 제거 목록 (Phase 1 필수)

`setStyleSheet()` 로 박힌 값을 전부 토큰 참조로 바꾼다.

### 6.1 방법

두 가지 중 **하나**를 채택한다.

| 방식 | 설명 | 권장 |
|---|---|---|
| (A) 테마 색을 위젯 속성으로 | 위젯에 `setProperty("role", "warning")` → QSS `QLabel[role="warning"]` 로 스타일링 | ✅ **권장** |
| (B) 문자열 생성 | `f"color: {self.theme_manager.get_colors()['warning']};"` | 가능하지만 테마 전환 시 수동 갱신 필요 |

**(A) 를 권장한다.** 테마 전환 시 Qt 가 자동으로 다시 스타일링하므로 갱신 코드가 필요 없다. 실제로 현재 버그(테마 전환해도 인라인 색이 안 바뀜)의 근본 해결이 된다.

### 6.2 작업 대상

`app/gui/main_window.py`

| 대상 | 현재 | 변경 |
|---|---|---|
| `_LEVEL_QSS` | `color:#ffd93d;` / `color:#ff6b6b;` | QSS `QLabel[level="warn"]` / `QLabel[level="danger"]` |
| `ModelInfoPanel` 보조라벨 | `color:#a0a0a0;` | `QLabel[role="secondary"]` |
| 앱 타이틀 | `font-size:18px;font-weight:700` | `QLabel[role="headline"]` (24px) |
| `comfy_label` 초기값 | `color:#7fb3ff;` | QSS `QLabel[role="comfy"]` |
| `status_banner` | `color:#ffd93d; font-size:12px;` | `QLabel[role="warning"]` |
| `_model_warning` | `color:#ff6b6b; font-size:12px;` | `QLabel[role="danger"]` |
| `_field()` 보조라벨 | `color:#a0a0a0; font-size:11px;` | `QLabel[role="label"]` |
| `lora_strength_label` | `color:#a0a0a0; font-size:11px;` | 동일 |
| `preview` | `border:1px solid #444` | QSS `QLabel[role="preview"]` |

`app/gui/session_browser.py`

| 대상 | 현재 | 변경 |
|---|---|---|
| `image_preview` | `border: 1px solid #444; background: #222; color: #888;` | QSS `QLabel[role="preview"]` |

> **성공 기준**: 라이트 테마로 전환했을 때 화면에 `#444` / `#222` / `#a0a0a0` 계열이 **한 픽셀도 남아있지 않아야 한다.**

---

## 7. 단계별 작업 계획

각 Phase 는 완료 후 테스트를 통과시키고, 이상 시 그 Phase 만 되돌린다.

### Phase 0 — 준비 (코드 변경 없음)

- [ ] 현재 UI 스크린샷 캡처 (다크 / 라이트 × 3탭 = 6장) — **변경 전 기준선**
- [ ] `git branch ui-material-3` 생성
- [ ] 현행 테스트 119건 통과 확인
- [ ] `app/gui/theme/__init__.py` 확인

**완료 기준**: 기준선 스크린샷 6장 확보, 테스트 통과

---

### Phase 1 — 토큰 + QSS (가장 큰 효과, 가장 낮은 위험)

**수정 파일**: `app/gui/theme/manager.py`, `app/gui/main_window.py`, `app/gui/session_browser.py`

- [ ] `THEMES` 를 §4.1 구조로 교체 (M3 Baseline, dark/light)
- [ ] 기존 키 → M3 키 매핑 적용, `warning`→`tertiary`, `success`→`primary`
- [ ] `_generate_qss()` 전면 재작성
      - `QWidget` 전역 `background-color` **제거** (M3 의 층 구분 회복)
      - GroupBox → Card (§5.3)
      - 버튼 3종 구분 + 상태층 (§5.1)
      - 입력 필드 Filled / Outlined (§5.2)
      - 탭 인디케이터 `border-bottom` 방식 (§5.4 (a))
      - progressbar, 상태바, 리스트 선택색 `secondary-container` (§5.7, §5.5, §5.8)
- [ ] §6 인라인 스타일 10곳을 동적 속성(QSS 선택자) 로 전환
- [ ] 간격 4dp 그리드 정렬

**주의**
- `QWidget` 전역 배경을 지우면 **투명 배경 위젯이 검게 보이거나 잘리는 부작용**이 생길 수 있다. 이때는 특정 위젯에 `background: <surface-container-*>` 를 개별 지정한다.
- 프리뷰 이미지(`QLabel`)는 배경 제거 시 라이트 테마에서 흰 배경 + 흰 이미지 문제가 생긴다. 반드시 `role="preview"` 로 배경을 명시한다.

**완료 기준**
- [ ] 라이트 테마 전환 시 하드코딩 색이 1픽셀도 안 보임
- [ ] 다크 테마에서 모든 표면이 시각적으로 구분됨 (5단계)
- [ ] 전체 테스트 통과
- [ ] 라이트/다크 × 3탭 스크린샷 확보

---

### Phase 2 — 타이포그래리

**수정 파일**: `app/gui/theme/manager.py`, `app/gui/main_window.py`

- [ ] 폰트 스택 교체 (`Roboto`, `Noto Sans KR` 추가)
- [ ] §4.3 타입 스케일의 `font-size` / `font-weight` 를 QSS 에 반영
- [ ] `line-height` 는 QSS 불가 → 레이아웃 `setSpacing()` 으로 근사
- [ ] 자간이 필요한 곳만 `QFont.setLetterSpacing()` 사용

**완료 기준**: 모든 글자에 §4.3 중 하나의 크기만 쓰임 (임의 `11px`/`12px`/`18px` 残留 0건)

---

### Phase 3 — Elevation + State Layer

**신규 파일**: `app/gui/theme/elevation.py` (힌지 함수), `app/gui/theme/state.py` (불투명도 계산)

**수정 파일**: `app/gui/theme/manager.py`

- [ ] `state.py`: HEX → `rgba()` 변환 헬퍼 (테마별 on-surface RGB 기준)
- [ ] `elevation.py`: `QGraphicsDropShadowEffect` 부착 헬퍼
      - **§3.1 함정**: 자식 없는 `QFrame` 래퍼에만 부착
      - 이미지 프리뷰에는 금지
- [ ] hover/focus/pressed state layer 를 QSS `rgba()` 로 적용
- [ ] 카드에 resting elevation 적용

**완료 기준**: 카드에 그림자가 보이고, 라이트 테마에서 이미지/텍스트가 깨지지 않음

---

### Phase 4 — Focus Ring + Ripple

**수정 파일**: `app/gui/main_window.py`, `app/gui/session_browser.py`

- [ ] focus ring: `QSS :focus` 로 시도 → 불안정하면 `paintEvent` 커스텀
- [ ] ripple: 버튼용 `QPushButton` 서브클래스 + `eventFilter`
      - press 시 원형 오버레이 확산, `QPropertyAnimation` (150ms, `OutCubic`)
      - **Theming concern**: 오버레이 색은 테마 따라 바뀌어야 하므로 위젯에서 테마를 조회하지 말고 QSS 속성(`role`)으로 받는다
- [ ] 모션 duration 은 §4.9 값 사용

**완료 기준**: 키보드 Tab 이동 시 포커스가 보이고, 버튼 클릭 시 ripple 이 동작하며 테마 전환 후에도 ripple 색이 맞음

---

### Phase 5 — 선택적 다듬기

- [ ] Roboto / Noto Sans KR 폰트 동봉 여부 결정 (파일 추가 → 승인 필요)
- [ ] Material Symbols 아이콘 폰트 도입 검토 (현재 아이콘 없음)
- [ ] third-party 확장 포인트 확인 (`app/gui/widgets/`, `app/gui/pages/` 는 현재 빈 패키지)

**완료 기준**: 자체 판단. 이 Phase 는 없어도 완성으로 볼 수 있다.

---

## 8. 신규 파일 목록

| 파일 | Phase | 역할 |
|---|---|---|
| `app/gui/theme/elevation.py` | 3 | elevation 힌지 |
| `app/gui/theme/state.py` | 3 | state layer 색 계산 |

**Phase 4 에서 추가될 수 있는 파일**

| 파일 | 역할 |
|---|---|
| `app/gui/widgets/ripple_button.py` | ripple QPushButton |

> `app/gui/widgets/` 와 `app/gui/pages/` 는 현재 빈 패키지다. ripple 버튼을 여기에 두면 나중에 재사용성이 생긴다. 단, **빈 패키지를 채우는 것이 목표는 아니다.**

---

## 9. 리스크와 대응

| # | 리스크 | 영향 | 대응 |
|---|---|---|---|
| R1 | `QWidget` 전역 배경 제거 후 투명 위젯 깨짐 | 중간 | Phase 1 을 **테마 단위로** 나눠 적용(dark 먼저 → 확인 → light). 되돌리기 용이하게 |
| R2 | elevation 가 자식 위젯에 안 그려짐 | 낮음 | §3.1 래퍼 규칙 준수 |
| R3 | 색상 대비 부족 (다크 `surface` vs `surface-container-low` 가 1단계 차이) | 중간 | `surface-container` 상위 사용 검토, 대비 확인 후 확정 |
| R4 | QSS `line-height` / `letter-spacing` 미지원 | 낮음 | 레이아웃 간격으로 근사, 자간은 코드 |
| R5 | 상태 rgba 계산을 잘못해 라이트 테마에서 글자가 안 보임 | **높음** | Phase 3 을 Phase 1 과 **분리**해 독립 검증 |
| R6 | ripple 이 QSS 와 충돌 | 중간 | ripple 오버레이는 `QGraphicsOpacityEffect` 로 그려 QSS 를 건드리지 않음 |
| R7 | 동시 작업으로 코드 충돌 | **높음** | **Phase 1 착수 전 `git status` 확인.** 이미 다른 세션이 파일을 수정 중이었던 이력이 있다 |

---

## 10. 검증 방법

### 10.1 자동

```bash
python -m pytest tests -q
```

- **기준선**: 현재 119건 중 117 passed / 2 failed.
  실패 2건(`test_shutdown_*`)은 **샌드박스 환경의 `WinError`** 이고 변경 전에도 동일하게 실패한다. **Baseline 이다.**
- **회귀 판정**: 실패 수가 3건 이상으로 늘면 Phase 실패로 간주한다.

### 10.2 추가할 테스트

Phase 1 이후 아래 테스트를 추가한다.

| 테스트 | 확인 내용 |
|---|---|
| `test_theme_has_m3_roles` | M3 토큰이 모두 존재 |
| `test_no_inline_hardcoded_color` | `main_window.py` / `session_browser.py` 에 `#hex` 리터럴이 **0건** |
| `test_light_theme_has_no_dark_colors` | light 팔레트에 밝은/어두운 값 섞이지 않음 |
| `test_qss_generates_without_error` | `_generate_qss()` 가 예외 없이 문자열 생성 |

`test_no_inline_hardcoded_color` 는 **회귀를 실제로 막는 핵심 테스트**다. §6 이 되돌아가는 것을 막는다.

### 10.3 수동 (눈 확인)

Phase 마다 아래를 캡처해 비교한다.

- [ ] 다크 × (Generate / Model / History) = 3장
- [ ] 라이트 × 3탭 = 3장
- [ ] 최소 창 크기(900×700) 1장
- [ ] 포커스 이동 시 focus ring
- [ ] 삭제 확인 dialog

---

## 11. 되돌리기

- Phase 1~5 는 각각 **단일 커밋**으로 끝낸다. 커밋 메시지는 Conventional Commits 규약(`refactor(gui): ...`)을 따른다.
- 되돌리기는 `git revert <commit>` 로 Phase 단위가 가능하다.
- `git branch ui-material-3` 에서 작업하고, 검증 후에만 기본 브랜치에 병합한다.

---

## 12. 완료 기준 (Definition of Done)

- [ ] 다크/라이트 테마 모두 M3 Baseline 팔레트를 사용한다
- [ ] 하드코딩 색상 리터럴이 `app/gui/` 에 **0건**
- [ ] 테마 전환 시 모든 위젯의 색이 함께 바뀐다 (인라인 잔존 없음)
- [ ] GroupBox 가 테두리 없이 표면색 차이로 구분된다
- [ ] `그려줘` 버튼만 Filled(색이 채워짐)로 강조된다
- [ ] 리스트 선택 색이 `secondary-container` 다
- [ ] 상태바가 사용률만 표시하고, 타이틀바가 기기 정보를 표시한다
- [ ] 모든 글자 크기가 §4.3 타입 스케일에 속한다
- [ ] 간격이 4dp 그리드에 속한다
- [ ] Phase 3 이상 완료 시 카드에 elevation 가 있고 hover 시 상태층이 보인다
- [ ] Phase 4 이상 완료 시 focus ring 과 ripple 이 동작한다
- [ ] 최소 창 크기(900×700)에서 레이아웃이 깨지지 않는다
- [ ] `pytest` 결과가 **baseline(117 passed / 2 failed) 이하의 실패**다
- [ ] 스크린샷 7장 이상 확보

---

## 13. 참고

- Material Design 3 공식 문서: <https://m3.material.io/>
- Material Theme Builder(팔레트 생성·검증): <https://material-foundation.github.io/material-theme-builder/>
- 색상 토큰 전체 목록: <https://m3.material.io/styles/color/system/overview>
- 타이포그래피 스케일: <https://m3.material.io/styles/typography/overview>
- elevation 규칙: <https://m3.material.io/styles/elevation/overview>

---

**문서 끝**