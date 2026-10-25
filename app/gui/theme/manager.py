from __future__ import annotations

import logging
from pathlib import Path
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication


class ThemeManager(QObject):
    """Theme System (v.01 §24, [유지] Theme System).

    다크/라이트 테마와 QSS 기반 스타일링을 제공한다.
    기존 ComfyCraft 테마 시스템을 계승한다.
    """

    THEMES = {
        "dark": {
            "name": "다크",
            "colors": {
                "background": "#1a1a1a",
                "surface": "#222222",
                "surface_alt": "#2a2a2a",
                "border": "#444444",
                "text": "#e0e0e0",
                "text_secondary": "#a0a0a0",
                "accent": "#4a9fff",
                "accent_hover": "#6bb0ff",
                "danger": "#ff6b6b",
                "warning": "#ffd93d",
                "success": "#6bcf7f",
            },
        },
        "light": {
            "name": "라이트",
            "colors": {
                "background": "#f5f5f5",
                "surface": "#ffffff",
                "surface_alt": "#f0f0f0",
                "border": "#e0e0e0",
                "text": "#333333",
                "text_secondary": "#707070",
                "accent": "#2196F3",
                "accent_hover": "#1976D2",
                "danger": "#f44336",
                "warning": "#FF9800",
                "success": "#4CAF50",
            },
        },
    }

    def __init__(self, app: QApplication, config_path: Path | None = None):
        super().__init__()
        self.app = app
        self.config_path = config_path
        self.current_theme: str = "dark"
        self._load_config()

    def _load_config(self) -> None:
        """설정 파일에서 테마 로드.

        설정 파일이 깨져 있어도 기본 테마로 시작해야 한다.
        예외를 그대로 내면 프로그램 시작 자체가 실패한다.
        """
        if not (self.config_path and self.config_path.exists()):
            return
        import json
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logging.getLogger(__name__).warning(
                "테마 설정 파일을 읽지 못해 기본 테마로 시작합니다 (%s): %s",
                self.config_path, exc,
            )
            return
        theme = config.get("theme", "dark")
        if theme in self.THEMES:
            self.current_theme = theme

    def _save_config(self) -> None:
        """테마 설정 저장."""
        if self.config_path:
            import json
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            config = {"theme": self.current_theme}
            self.config_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def get_theme(self, theme_name: str | None = None) -> dict:
        """테마 딕셔너리 반환."""
        name = theme_name or self.current_theme
        return self.THEMES.get(name, self.THEMES["dark"])

    def get_colors(self, theme_name: str | None = None) -> dict:
        """테마 색상값 반환."""
        return self.get_theme(theme_name)["colors"]

    def apply_theme(self, theme_name: str | None = None) -> None:
        """테마 적용."""
        if theme_name:
            self.current_theme = theme_name
        colors = self.get_colors()
        self.app.setStyleSheet(self._generate_qss(colors))
        self._save_config()

    def _generate_qss(self, colors: dict) -> str:
        """QSS 스타일시트 생성."""
        icon_dir = Path(__file__).resolve().parents[3] / "assets" / "icons"
        spin_up_icon = (icon_dir / "spin-up.svg").as_posix()
        spin_down_icon = (icon_dir / "spin-down.svg").as_posix()
        return f"""
        QWidget {{
            background-color: {colors['background']};
            color: {colors['text']};
            font-family: 'Segoe UI', 'Malgun Gothic', Arial, sans-serif;
            font-size: 14px;
        }}
        QGroupBox {{
            border: 1px solid {colors['border']};
            border-radius: 6px;
            padding-top: 10px;
            margin-top: 10px;
            font-weight: bold;
            color: {colors['text']};
        }}
        QGroupBox::title {{
            padding: 0 6px;
            color: {colors['accent']};
        }}
        QPushButton {{
            background-color: {colors['surface']};
            border: 1px solid {colors['border']};
            border-radius: 4px;
            padding: 6px 12px;
            color: {colors['text']};
        }}
        QPushButton:hover {{
            background-color: {colors['surface_alt']};
        }}
        QPushButton:pressed {{
            background-color: {colors['accent']};
            color: {colors['background']};
        }}
        QComboBox, QSpinBox, QDoubleSpinBox {{
            background-color: {colors['surface']};
            border: 1px solid {colors['border']};
            border-radius: 4px;
            padding: 4px 8px;
            color: {colors['text']};
        }}
        QSpinBox::up-button, QDoubleSpinBox::up-button,
        QSpinBox::down-button, QDoubleSpinBox::down-button {{
            subcontrol-origin: border;
            width: 28px;
            border-left: 1px solid {colors['border']};
            background-color: {colors['surface']};
        }}
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
            image: url("{spin_up_icon}");
            width: 10px;
            height: 7px;
        }}
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
            image: url("{spin_down_icon}");
            width: 10px;
            height: 7px;
        }}
        QSpinBox::up-button, QDoubleSpinBox::up-button {{
            subcontrol-position: top right;
            border-top-right-radius: 3px;
        }}
        QSpinBox::down-button, QDoubleSpinBox::down-button {{
            subcontrol-position: bottom right;
            border-bottom-right-radius: 3px;
        }}
        QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
        QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
            background-color: {colors['surface_alt']};
        }}
        QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
        QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
            background-color: {colors['accent']};
        }}
        QTextEdit, QLineEdit {{
            background-color: {colors['surface']};
            border: 1px solid {colors['border']};
            border-radius: 4px;
            padding: 4px 8px;
            color: {colors['text']};
        }}
        QTabBar::tab {{
            background-color: {colors['surface']};
            border: 1px solid {colors['border']};
            border-radius: 4px 4px 0 0;
            padding: 6px 12px;
            color: {colors['text']};
        }}
        QTabBar::tab:selected {{
            background-color: {colors['accent']};
            color: {colors['background']};
        }}
        QTreeWidget, QTreeWidget::item {{
            background-color: {colors['surface']};
            border: 1px solid {colors['border']};
            color: {colors['text']};
        }}
        QTreeWidget::item:selected {{
            background-color: {colors['accent']};
            color: {colors['background']};
        }}
        QProgressBar {{
            border: 1px solid {colors['border']};
            border-radius: 4px;
            text-align: center;
            color: {colors['text']};
        }}
        QProgressBar::chunk {{
            background-color: {colors['accent']};
            border-radius: 3px;
        }}
        QLabel {{
            color: {colors['text']};
        }}
        QToolBar {{
            background-color: {colors['surface']};
            border: 1px solid {colors['border']};
            spacing: 4px;
            padding: 4px;
        }}
        QSplitter::handle {{
            background-color: {colors['border']};
        }}
        """

    def toggle_theme(self) -> str:
        """라이트/다크 테마 토글."""
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        self.apply_theme()
        return self.current_theme

    def get_available_themes(self) -> list[str]:
        """사용 가능한 테마 목록 반환."""
        return list(self.THEMES.keys())
