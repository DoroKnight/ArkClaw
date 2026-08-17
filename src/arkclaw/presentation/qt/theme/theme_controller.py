"""Single authoritative ThemeController for all ArkClaw UI surfaces (Visual Amendment v1.1)."""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import QObject, Signal

from arkclaw.presentation.qt.theme.qt_theme import QtTheme

__all__ = [
    "QtTheme",
    "ThemeController",
    "ThemePreference",
    "resolve_effective_theme",
]


class ThemePreference(StrEnum):
    """User-selectable theme preference."""

    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


def resolve_effective_theme(preference: ThemePreference) -> QtTheme:
    """Resolve a ThemePreference into an EffectiveTheme (QtTheme.LIGHT or QtTheme.DARK)."""
    if preference is ThemePreference.LIGHT:
        return QtTheme.LIGHT
    if preference is ThemePreference.DARK:
        return QtTheme.DARK
    # SYSTEM: Query Windows AppsUseLightTheme
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return QtTheme.LIGHT if value == 1 else QtTheme.DARK
    except Exception:
        return QtTheme.LIGHT


class ThemeController(QObject):
    """Single-source ThemeController broadcasting EffectiveTheme changes across all UI surfaces."""

    theme_changed = Signal(QtTheme)

    def __init__(
        self,
        initial_preference: ThemePreference = ThemePreference.SYSTEM,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._preference = initial_preference
        self._effective_theme = resolve_effective_theme(initial_preference)

    @property
    def preference(self) -> ThemePreference:
        return self._preference

    @property
    def effective_theme(self) -> QtTheme:
        return self._effective_theme

    def set_preference(self, preference: ThemePreference) -> None:
        self._preference = preference
        self.refresh()

    def toggle_light_dark(self) -> None:
        """Instant toggle between Light and Dark mode."""
        if self._effective_theme is QtTheme.LIGHT:
            self.set_preference(ThemePreference.DARK)
        else:
            self.set_preference(ThemePreference.LIGHT)

    def refresh(self) -> None:
        new_theme = resolve_effective_theme(self._preference)
        if new_theme != self._effective_theme or not hasattr(self, "_initialized"):
            self._initialized = True
            self._effective_theme = new_theme
            self.theme_changed.emit(new_theme)
