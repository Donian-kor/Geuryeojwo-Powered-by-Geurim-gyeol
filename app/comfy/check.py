"""워크플로 등록 전 검사 (GUI 없이 검증 가능한 순수 함수).

ComfyUI 에서 가져온 워크플로가 '이 프로그램에서 바로 쓸 수 있는 상태' 인지
확인하고, 막혔으면 무엇을 해야 하는지까지 함께 돌려준다.

판단만 한다. 서버에 접속하지 않고 파일도 고치지 않는다.
(목록은 호출자가 /object_info 와 /models/* 응답을 넘겨준다)

검사 4단계
    1) 형식   - ComfyUI API 형식인가
    2) 노드   - 없는 노드가 있나 (커스텀 노드 미설치)
    3) 모델   - 필요한 모델 파일이 설치돼 있나
    4) 적합성 - 이 프로그램으로 그 결과를 받을 수 있나

막혔을 때 '안 됨' 으로 끝내지 않는 것이 이 모듈의 목적이다.
모든 항목에 해결 방법(actions)과 링크(links)를 함께 실어 준다.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from .workflow import _MODEL_FOLDERS, _MODEL_INPUTS

# HuggingFace 모델 검색. 파일명만 알아도 받을 파일을 찾을 수 있다.
_HF_SEARCH = "https://huggingface.co/models?search={}"

# 화면 저장 형식에만 있고 서버에는 없는 노드.
# API 로 내보내면 자동으로 사라지므로 '필요 없는 노드' 가 아니다.
_UI_ONLY_NODES = frozenset({"Note", "MarkdownNote", "Reroute", "PrimitiveNode"})

# 파일명에 이런 이름이 들어가면 같은 계열의 다른 모델이다.
# (z-anime-distill-8step-aio-fp8 와 z-anime-base-aio-fp8 는 서로 다른 모델)
_SIMILAR_CUTOFF = 0.62

LEVEL_OK = "ok"
LEVEL_INFO = "info"      # 확인하지 못함. 이상 없음도 아니다.
LEVEL_WARN = "warn"
LEVEL_BLOCK = "block"


@dataclass
class CheckItem:
    """검사 결과 하나. GUI 는 이 필드만 보고 문장을 그린다."""

    level: str                      # ok / warn / block
    title: str
    detail: str = ""
    rows: list[tuple[str, str]] = field(default_factory=list)     # (라벨, 값)
    actions: list[str] = field(default_factory=list)               # 사용자가 할 일
    links: list[tuple[str, str]] = field(default_factory=list)     # (라벨, url)


@dataclass
class CheckReport:
    """검사 전체 결과."""

    items: list[CheckItem] = field(default_factory=list)
    # 결과 저장 노드 ID. 2개 이상이면 GUI 가 선택지를 띄운다.
    outputs: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        """진행이 막혔는지. 막혔어도 '기본 베이스로' 우회할 수 있다."""
        return any(i.level == LEVEL_BLOCK for i in self.items)

    @property
    def ready(self) -> bool:
        """모든 항목을 확인했고 이상이 없는 상태.

        '확인 못 함'(info) 도 준비 완료가 아니다.
        모르는 걸 정상이라고 말하면 사용자가 그대로 믿고 실패한다.
        """
        return bool(self.items) and all(i.level == LEVEL_OK for i in self.items)

    def add(self, item: CheckItem) -> None:
        self.items.append(item)


# --- 1) 형식 ------------------------------------------------------------

def prompt_of(data: dict) -> dict | None:
    """API 형식 프롬프트(dict)를 꺼낸다. 화면 형식이면 None."""
    if not isinstance(data, dict):
        return None
    inner = data.get("prompt")
    if isinstance(inner, dict) and inner:
        return inner
    if any(isinstance(v, dict) and "class_type" in v for v in data.values()):
        return data
    return None


def check_format(data: dict) -> CheckItem | None:
    """API 형식이 아니면 안내. 맞으면 None."""
    if prompt_of(data) is not None:
        return None
    looks_ui = isinstance(data.get("nodes"), list)
    return CheckItem(
        LEVEL_BLOCK,
        "화면용 형식의 파일입니다" if looks_ui else "워크플로 노드를 찾지 못했습니다",
        detail=(
            "ComfyUI 는 두 가지 형식으로 저장합니다.\n"
            "  File → Save              : 화면 배치까지 담은 파일 (사용 불가)\n"
            "  File → Export Workflow (API) : 프로그램이 읽는 파일"
        ),
        actions=[
            "ComfyUI 에서 File → Load (Ctrl+O) 로 이 파일을 엽니다",
            "File → Export Workflow (API) 로 다시 내려받습니다",
            "내려받은 파일을 다시 가져옵니다",
        ],
    )
# --- 2) 노드 ------------------------------------------------------------

def _title(node: dict) -> str:
    return (node.get("_meta") or {}).get("title") or ""


def nodes_without_class_type(prompt: dict) -> list[tuple[str, str]]:
    """class_type 이 빠진 노드. (노드 ID, 화면에 보이는 이름)"""
    result: list[tuple[str, str]] = []
    for node_id, node in (prompt or {}).items():
        if isinstance(node, dict) and not node.get("class_type"):
            result.append((str(node_id), _title(node) or "(이름 없음)"))
    return result


def unknown_input_nodes(prompt: dict) -> list[str]:
    """입력 이름이 UNKNOWN 인 노드. ComfyUI 가 값을 못 옮긴 자리."""
    result = []
    for node_id, node in (prompt or {}).items():
        inputs = (node or {}).get("inputs") or {}
        if any(str(k).startswith("UNKNOWN") for k in inputs):
            result.append(_title(node) or str(node_id))
    return result


def check_nodes(prompt: dict, known_types) -> CheckItem | None:
    """없는 노드가 있으면 왜 안 되는지와 해결 방법을 함께 돌려준다.

    class_type 이 빠진 노드가 가장 확실한 신호다.
    ComfyUI 는 서버에 없는 노드를 API 로 내보낼 때 값을 옮기지 못하고
    class_type 없이 UNKNOWN_* 입력만 남긴다. 이런 파일은 서버가 거부한다.
    """
    broken = nodes_without_class_type(prompt)
    unknown = unknown_input_nodes(prompt)

    if broken:
        names = " · ".join(t for _, t in broken)
        return CheckItem(
            LEVEL_BLOCK,
            f"추가 노드 {len(broken)}개가 설치돼 있지 않습니다",
            detail=(
                "이 워크플로를 API 로 내보내도 쓸 수 없습니다.\n"
                "노드가 없으면 ComfyUI 가 값을 옮기지 못해 "
                "꺼진 노드와 빈 입력으로 기록하기 때문입니다.\n\n"
                f"없는 노드: {names}"
            ),
            actions=[
                "ComfyUI 의 Manager 탭을 엽니다",
                "Install Missing Custom Nodes 로 위 노드들을 설치합니다",
                "원본 워크플로를 다시 열어 File → Export Workflow (API)",
                "다시 가져오기 버튼을 누릅니다",
            ],
        )

    if unknown:
        return CheckItem(
            LEVEL_WARN,
            f"값이 옮겨지지 않은 입력이 {len(unknown)}개 노드에 있습니다",
            detail=" · ".join(unknown),
            actions=["원본 워크플로를 다시 내보내 주세요 (노드 버전이 맞지 않을 수 있습니다)"],
        )

    if known_types:
        used = {
            n.get("class_type") for n in (prompt or {}).values()
            if isinstance(n, dict) and n.get("class_type")
        }
        absent = sorted(
            t for t in used
            if t not in known_types and t not in _UI_ONLY_NODES
        )
        if absent:
            return CheckItem(
                LEVEL_BLOCK,
                f"설치되지 않은 노드 {len(absent)}종을 씁니다",
                detail="\n".join(absent),
                actions=["ComfyUI Manager → Install Missing Custom Nodes 에서 설치합니다"],
            )
    return None
# --- 3) 모델 ------------------------------------------------------------

_FOLDER_LABEL = {
    "checkpoints": "체크포인트",
    "diffusion_models": "확산 모델",
    "text_encoders": "텍스트 인코더",
    "vae": "VAE",
    "loras": "LoRA",
    "upscale_models": "업스케일 모델",
}


def required_models(prompt: dict) -> dict[str, list[str]]:
    """폴더 -> 워크플로가 요구하는 파일 목록."""
    result: dict[str, list[str]] = {}
    for node in (prompt or {}).values():
        for name, value in ((node or {}).get("inputs") or {}).items():
            if name in _MODEL_INPUTS and isinstance(value, str) and value:
                folder = _MODEL_FOLDERS[name]
                result.setdefault(folder, [])
                if value not in result[folder]:
                    result[folder].append(value)
    return result


def similar_models(name: str, installed: list[str]) -> list[str]:
    """비슷한 이름으로 설치된 파일. '다른 모델' 일 수 있어 힌트로만 쓴다.

    확장자를 뗀 이름끼리 비교한다. 확장자가 다르면 다른 계열이다.
    """
    stem, ext = Path(name).stem, Path(name).suffix
    pool = {Path(h).stem: h for h in installed if Path(h).suffix == ext}
    matches = difflib.get_close_matches(
        stem, list(pool), n=1, cutoff=_SIMILAR_CUTOFF
    )
    return [pool[matches[0]]] if matches else []


def check_models(prompt: dict, installed, models_dir=None) -> CheckItem | None:
    """필요한 모델을 찾고, 없으면 어디에 뭘 넣어야 하는지 알려준다.

    installed: {"diffusion_models": [...], ...} (None 이면 판단하지 않는다)
    models_dir: ComfyUI models 폴더. 경로를 보여줄 수 있게 해준다.
    """
    needed = required_models(prompt)
    if not needed:
        return None

    rows: list[tuple[str, str]] = []
    links: list[tuple[str, str]] = []
    missing = 0
    verified = 0

    for folder, names in needed.items():
        have = (installed or {}).get(folder)
        if have is None:
            # 목록을 못 받았으면 이 폴더는 판단을 보류한다.
            continue
        verified += 1
        for name in names:
            if name in have:
                continue
            missing += 1
            stem = Path(name).stem
            rows.append((f"{_FOLDER_LABEL.get(folder, folder)}\\{name}", ""))
            for alt in similar_models(name, have):
                rows.append(("", f"비슷한 이름으로 이미 설치됨: {alt}  (다른 모델일 수 있음)"))
            if models_dir:
                rows.append(("", str(Path(models_dir) / folder / name)))
            links.append((stem, _HF_SEARCH.format(stem)))

    if not verified:
        # 하나도 확인 못 했다. '모두 설치' 라고 말하면 안 된다.
        return CheckItem(
            LEVEL_INFO,
            "모델 설치 여부를 확인하지 못했습니다",
            detail="ComfyUI 에서 모델 목록을 못 받았습니다. 실행해 보면 알 수 있습니다.",
            actions=["ComfyUI 가 켜져 있는지 확인합니다"],
        )

    if not missing:
        return CheckItem(
            LEVEL_OK,
            f"필요한 모델 {sum(len(v) for v in needed.values())}개가 모두 설치돼 있습니다",
            detail=", ".join(
                f"{_FOLDER_LABEL.get(f, f)} {len(v)}개" for f, v in needed.items()
            ),
        )

    item = CheckItem(
        LEVEL_WARN,
        f"모델 {missing}개를 더 받아야 실행됩니다",
        detail="아래 경로에 파일을 넣으면 됩니다.",
        rows=rows,
        links=links,
        actions=["모델을 받고 나면 다시 가져오기를 누릅니다"],
    )
    if models_dir:
        item.detail += f"\n모델 폴더: {models_dir}"
    return item
# --- 4) 적합성 ----------------------------------------------------------

# 결과가 저장되는 노드. 여기가 여러 개면 어느 쪽을 받을지 골라야 한다.
_OUTPUT_CLASSES = ("SaveImage", "PreviewImage")


def output_nodes(prompt: dict) -> list[str]:
    return [
        nid for nid, node in (prompt or {}).items()
        if isinstance(node, dict) and node.get("class_type") in _OUTPUT_CLASSES
    ]


def ancestors(prompt: dict, node_id: str, limit: int = 400) -> set[str]:
    """node_id 로 흘러 들어온 노드들(업스트림 전체)."""
    seen: set[str] = set()
    stack = [node_id]
    while stack:
        cur = stack.pop()
        if cur in seen or len(seen) > limit:
            continue
        seen.add(cur)
        for value in ((prompt.get(cur) or {}).get("inputs") or {}).values():
            if (isinstance(value, list) and len(value) == 2
                    and isinstance(value[0], str) and value[0] in prompt):
                stack.append(value[0])
    return seen


def check_fitness(prompt: dict) -> CheckItem | None:
    """이 프로그램으로 결과를 받을 수 있는지."""
    outs = output_nodes(prompt)

    if not outs:
        return CheckItem(
            LEVEL_BLOCK,
            "결과를 저장하는 노드가 없습니다",
            detail="SaveImage 노드가 있어야 그림을 받을 수 있습니다.",
            actions=["기본 베이스로 등록하면 됩니다"],
        )

    # LoadImage 는 '결과까지 연결된 경우에만' 막는다.
    # 연결이 끊긴 노드(안내용 이미지)는 무시해야 한다.
    reachable: set[str] = set()
    for out in outs:
        reachable |= ancestors(prompt, out)
    loaders = sorted(
        nid for nid in reachable
        if (prompt.get(nid) or {}).get("class_type") == "LoadImage"
    )
    if loaders:
        return CheckItem(
            LEVEL_BLOCK,
            "이미지를 입력으로 받는 워크플로입니다",
            detail=(
                "이 프로그램은 설명문을 입력받아 그림을 만듭니다.\n"
                "이미지를 고르는 워크플로는 쓸 수 없습니다."
            ),
            actions=["기본 베이스로 등록하면 됩니다"],
        )

    if len(outs) > 1:
        titles = " · ".join(
            ((prompt.get(n) or {}).get("_meta") or {}).get("title", str(n))
            for n in outs
        )
        return CheckItem(
            LEVEL_WARN,
            f"저장할 결과가 {len(outs)}개입니다",
            detail=f"{titles}\n어느 쪽을 받을지 골라 주세요.",
        )
    return None


# --- 전체 ---------------------------------------------------------------

def check_workflow(
    data: dict,
    known_types=None,
    installed=None,
    models_dir=None,
) -> CheckReport:
    """워크플로 파일 하나를 4단계로 검사한다.

    Args:
        data: 읽은 JSON (API 형식 또는 화면 형식)
        known_types: ComfyUI 가 아는 노드 타입 집합. None 이면 건너뛴다.
        installed: {"diffusion_models": [...], ...}
        models_dir: ComfyUI models 폴더 경로
    """
    report = CheckReport()

    fmt = check_format(data)
    if fmt is not None:
        # 형식이 다르면 뒤 단계 결과가 무의미하다.
        report.add(fmt)
        return report

    prompt = prompt_of(data) or {}

    node_item = check_nodes(prompt, known_types)
    if node_item is not None:
        report.add(node_item)

    model_item = check_models(prompt, installed, models_dir)
    if model_item is not None:
        report.add(model_item)

    report.outputs = output_nodes(prompt)
    fit = check_fitness(prompt)
    if fit is not None:
        report.add(fit)

    if not report.items:
        report.add(CheckItem(LEVEL_OK, "이 워크플로를 바로 쓸 수 있습니다"))
    return report