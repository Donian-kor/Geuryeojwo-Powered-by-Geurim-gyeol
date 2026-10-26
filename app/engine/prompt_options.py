"""선택형 이미지 연출 설정과 프롬프트 조합."""
from __future__ import annotations


PROMPT_OPTION_FIELDS = (
    (
        "location", "장소", "Location",
        (
            ("카페", "a cozy café interior"),
            ("실내 수영장", "an indoor swimming pool"),
            ("해변", "a tropical beach"),
            ("호텔 객실", "a refined hotel room"),
            ("도시 거리", "a lively city street"),
            ("숲", "a lush forest"),
            ("직접 입력", ""),
        ),
    ),
    (
        "season", "계절", "Season",
        (
            ("봄", "spring"),
            ("여름", "summer"),
            ("가을", "autumn"),
            ("겨울", "winter"),
            ("직접 입력", ""),
        ),
    ),
    (
        "time", "시간", "Time",
        (
            ("새벽", "at dawn"),
            ("아침", "in the morning"),
            ("오후", "in the afternoon"),
            ("일몰", "at sunset"),
            ("야간", "at night"),
            ("직접 입력", ""),
        ),
    ),
    (
        "weather", "날씨", "Weather",
        (
            ("맑음", "clear sunny weather"),
            ("흐림", "overcast cloudy weather"),
            ("비", "rainy weather"),
            ("눈", "snowfall"),
            ("안개", "misty fog"),
            ("직접 입력", ""),
        ),
    ),
    (
        "outfit", "의상", "Outfit",
        (
            ("캐주얼", "casual clothing"),
            ("정장", "a tailored formal outfit"),
            ("계절 의상", "season-appropriate clothing"),
            ("직접 입력", ""),
        ),
    ),
    (
        "pose", "포즈", "Pose",
        (
            ("자연스러운 자세", "a natural relaxed pose"),
            ("걷는 모습", "walking naturally"),
            ("앉은 자세", "sitting comfortably"),
            ("인물 사진 포즈", "a graceful portrait pose"),
            ("직접 입력", ""),
        ),
    ),
    (
        "camera_direction", "카메라 방향", "Camera direction",
        (
            ("정면", "front view"),
            ("전면 45도", "three-quarter front view"),
            ("측면", "side view"),
            ("후면 45도", "three-quarter rear view"),
            ("후면", "rear view"),
            ("직접 입력", ""),
        ),
    ),
    (
        "camera_angle", "카메라 앵글", "Camera angle",
        (
            ("눈높이", "eye-level angle"),
            ("하이 앵글", "high-angle view"),
            ("로우 앵글", "low-angle view"),
            ("탑뷰", "overhead view"),
            ("직접 입력", ""),
        ),
    ),
    (
        "shot_size", "샷 크기", "Shot size",
        (
            ("얼굴 클로즈업", "face close-up"),
            ("상반신", "upper-body medium shot"),
            ("허리 위", "waist-up shot"),
            ("전신", "full-body shot"),
            ("넓은 장면", "wide establishing shot"),
            ("직접 입력", ""),
        ),
    ),
    (
        "lens", "렌즈", "Lens",
        (
            ("24mm 광각", "24mm wide-angle lens"),
            ("35mm", "35mm lens"),
            ("50mm 표준", "50mm standard lens"),
            ("85mm 인물", "85mm portrait lens"),
            ("135mm 망원", "135mm telephoto lens"),
            ("직접 입력", ""),
        ),
    ),
    (
        "aperture", "조리개", "Aperture",
        (
            ("f/1.4", "f/1.4 aperture with shallow depth of field"),
            ("f/1.8", "f/1.8 aperture"),
            ("f/2.8", "f/2.8 aperture"),
            ("f/4", "f/4 aperture"),
            ("f/8", "f/8 aperture with deeper focus"),
            ("직접 입력", ""),
        ),
    ),
    (
        "lighting", "조명", "Lighting",
        (
            ("자연광", "soft natural lighting"),
            ("스튜디오 조명", "professional studio lighting"),
            ("골든아워", "warm golden-hour lighting"),
            ("역광", "dramatic backlighting"),
            ("측면광", "soft directional side lighting"),
            ("시네마틱 조명", "cinematic dramatic lighting"),
            ("직접 입력", ""),
        ),
    ),
    (
        "style", "화풍", "Visual style",
        (
            ("실사 사진", "photorealistic photography"),
            ("실사 영화", "a live-action cinematic film still"),
            ("일본 애니메이션", "Japanese anime style with expressive clean line art"),
            ("손그림 2D 애니메이션", "hand-drawn 2D animation with soft painted backgrounds"),
            ("3D 애니메이션", "polished 3D animated film style"),
            ("레트로 애니메이션", "retro animation with a vintage cel look"),
            ("치비 애니메이션", "cute chibi animation style"),
            ("스톱모션", "tactile stop-motion animation style"),
            ("수채화 일러스트", "delicate watercolor illustration"),
            ("웹툰", "clean Korean webtoon illustration style"),
            ("직접 입력", ""),
        ),
    ),
)

PROMPT_OPTION_HELP = {
    "lens": {
        "24mm 광각": "넓은 공간을 담지만 가장자리가 늘어나 보임.",
        "35mm": "배경과 인물을 자연스럽게 넓은 화각.",
        "50mm 표준": "사람 눈에 가까운 원근감.",
        "85mm 인물": "인물을 돋보이게, 배경을 부드럽게 흐림.",
        "135mm 망원": "멀리 있는 대상을 크게 담고 배경을 압축.",
    },
    "aperture": {
        "f/1.4": "피사체를 강조.",
        "f/1.8": "배경 흐림이 강한 인물 사진.",
        "f/2.8": "피사체와 배경 흐림의 균형.",
        "f/4": " 조금 선명하게.",
        "f/8": " 장면 전체를 선명하게 .",
    },
}


def compose_prompt(prompt: str, options: dict[str, str] | None = None) -> str:
    """원문 프롬프트를 유지하며 선택한 연출 지시를 덧붙인다."""
    base_prompt = prompt.strip()
    selected = []
    for key, _label, prompt_label, _choices in PROMPT_OPTION_FIELDS:
        value = (options or {}).get(key, "").strip()
        if value:
            selected.append(f"{prompt_label}: {value}")
    if not selected:
        return base_prompt

    direction = "Visual direction: " + "; ".join(selected) + "."
    return f"{base_prompt}\n\n{direction}" if base_prompt else direction
