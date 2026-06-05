from pathlib import Path

from fly_on_the_wall.cli_menu import InteractiveMenu, MenuChoice


class FakeApplication:
    def __init__(self) -> None:
        self.invalidated = False

    def invalidate(self) -> None:
        self.invalidated = True


class FakeProcess:
    def __init__(self, returncode: int | None = None) -> None:
        self.returncode = returncode
        self.waited = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self) -> int:
        self.waited = True
        self.returncode = 0
        return self.returncode


def test_playback_completion_clears_status_and_invalidates_menu() -> None:
    process = FakeProcess(returncode=None)
    menu, application = _menu_with_playback(process)

    menu._wait_for_playback_completion(process)

    assert process.waited is True
    assert menu.playback_process is None
    assert menu.status_message == ""
    assert application.invalidated is True


def test_late_playback_completion_does_not_clear_new_playback() -> None:
    old_process = FakeProcess(returncode=None)
    new_process = FakeProcess(returncode=None)
    menu, application = _menu_with_playback(new_process)

    menu._wait_for_playback_completion(old_process)

    assert old_process.waited is True
    assert menu.playback_process is new_process
    assert menu.status_message == "Playing. Press Enter to stop."
    assert application.invalidated is False


def _menu_with_playback(process: FakeProcess) -> tuple[InteractiveMenu, FakeApplication]:
    menu = InteractiveMenu("Review", [MenuChoice("p", "Play clip", None, Path("clip.wav"))])
    application = FakeApplication()
    menu.application = application
    menu.playback_process = process
    menu.status_message = "Playing. Press Enter to stop."
    return menu, application
