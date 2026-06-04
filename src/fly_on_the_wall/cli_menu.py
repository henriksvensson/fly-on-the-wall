from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl

from fly_on_the_wall.audio import AudioError, start_audio_playback, stop_audio_playback


@dataclass(frozen=True)
class MenuChoice:
    shortcut: str | None
    label: str
    value: str | None
    playback_path: Path | None = None


def select_menu(title: str, choices: list[MenuChoice]) -> str | None:
    return InteractiveMenu(title, choices).run()


class InteractiveMenu:
    def __init__(self, title: str, choices: list[MenuChoice]) -> None:
        self.title = title
        self.choices = choices
        self.selected_index = 0
        self.selected_value: str | None = None
        self.status_message = ""
        self.playback_process = None
        self.key_bindings = KeyBindings()
        self.application = self._build_application()

    def run(self) -> str | None:
        try:
            self.application.run()
        except (KeyboardInterrupt, EOFError):
            return None
        return self.selected_value

    def _build_application(self) -> Application:
        self._bind_navigation_keys()
        self._bind_shortcut_keys()
        control = FormattedTextControl(self._render_menu, focusable=True)
        return Application(
            layout=Layout(HSplit([Window(content=control, always_hide_cursor=True)])),
            key_bindings=self.key_bindings,
            full_screen=False,
            style=None,
        )

    def _bind_navigation_keys(self) -> None:
        @self.key_bindings.add("up")
        def _up(_event) -> None:
            self._move(-1)

        @self.key_bindings.add("down")
        def _down(_event) -> None:
            self._move(1)

        @self.key_bindings.add("enter")
        def _enter(_event) -> None:
            if self._playback_is_running():
                self._stop_playback()
                return
            self._finish(self.choices[self.selected_index])

        @self.key_bindings.add("escape")
        @self.key_bindings.add("c-c")
        def _cancel(_event) -> None:
            self._cancel()

    def _bind_shortcut_keys(self) -> None:
        bound_shortcuts: set[str] = set()
        for choice in self.choices:
            if choice.shortcut is None or choice.shortcut in bound_shortcuts:
                continue
            bound_shortcuts.add(choice.shortcut)
            self.key_bindings.add(choice.shortcut)(lambda _event, selected=choice: self._finish(selected))

    def _finish(self, choice: MenuChoice) -> None:
        if choice.playback_path is not None:
            self._toggle_playback(choice.playback_path)
            return
        self._stop_playback()
        self.selected_value = choice.value
        self.application.exit()

    def _cancel(self) -> None:
        self._stop_playback()
        self.selected_value = None
        self.application.exit()

    def _toggle_playback(self, audio_path: Path) -> None:
        if self._playback_is_running():
            self._stop_playback()
            return
        try:
            self.playback_process = start_audio_playback(audio_path)
        except AudioError as exc:
            self.status_message = f"Could not play clip: {exc}"
            self.application.invalidate()
            return
        self.status_message = "Playing. Press Enter to stop."
        self.application.invalidate()

    def _stop_playback(self) -> None:
        if self.playback_process is not None:
            stop_audio_playback(self.playback_process)
            self.playback_process = None
        self.status_message = ""
        self.application.invalidate()

    def _move(self, offset: int) -> None:
        self.selected_index = (self.selected_index + offset) % len(self.choices)
        self.application.invalidate()

    def _render_menu(self):
        if self.playback_process is not None and self.playback_process.poll() is not None:
            self.playback_process = None
            self.status_message = ""
        lines = [("class:title", f"{self.title}\n")]
        lines.extend(self._choice_lines())
        if self.status_message:
            lines.append(("class:status", f"\n{self.status_message}\n"))
        lines.append(("class:help", "\nUse arrows, Enter, shortcut key, or Esc to cancel."))
        return lines

    def _choice_lines(self) -> list[tuple[str, str]]:
        lines = []
        for index, choice in enumerate(self.choices):
            prefix = ">" if index == self.selected_index else " "
            style = "class:selected" if index == self.selected_index else ""
            shortcut = f"[{choice.shortcut}] " if choice.shortcut is not None else ""
            lines.append((style, f"{prefix} {shortcut}{choice.label}\n"))
        return lines

    def _playback_is_running(self) -> bool:
        return self.playback_process is not None and self.playback_process.poll() is None
