from app.engine.prompt_options import PROMPT_OPTION_FIELDS, compose_prompt


def test_compose_prompt_keeps_original_and_adds_selected_directions():
    original = "  A cat in a garden.  "
    result = compose_prompt(original, {
        "location": "a lush forest",
        "style": "Japanese anime style",
    })

    assert original == "  A cat in a garden.  "
    assert result == (
        "A cat in a garden.\n\n"
        "Visual direction: Location: a lush forest; "
        "Visual style: Japanese anime style."
    )


def test_compose_prompt_without_options_only_trims_original():
    assert compose_prompt("  a cat  ") == "a cat"
    assert compose_prompt("  ", {}) == ""


def test_all_supported_prompt_option_fields_have_stable_keys():
    keys = [key for key, _label, _prompt_label, _choices in PROMPT_OPTION_FIELDS]
    assert keys == [
        "location", "season", "time", "weather", "outfit", "pose",
        "camera_direction", "camera_angle", "shot_size", "lens",
        "aperture", "lighting", "style",
    ]
    assert "aspect_ratio" not in keys
