"""Base controller contracts for GUI/engine separation."""

class Controller:
    """Marker base for UI controllers.

    Controllers coordinate UI events and engine operations; widgets should not
    call ComfyUI APIs directly.
    """
