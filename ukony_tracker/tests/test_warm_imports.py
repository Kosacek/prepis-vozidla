"""The AI SDK loads in the background at boot, not inside the first scan."""
import app as appmod


def _started_threads(monkeypatch):
    started = []

    class Spy:
        def __init__(self, target=None, name=None, daemon=None):
            self.target, self.name, self.daemon = target, name, daemon

        def start(self):
            started.append(self)

    monkeypatch.setattr(appmod.threading, "Thread", Spy)
    return started


def test_boot_loads_the_ai_sdk_in_a_background_thread(monkeypatch):
    # 26.10.: the first scans after a quiet weekend took 26–36 s, because the
    # worker imported the Anthropic SDK (21 s on the NAS) inside the request.
    started = _started_threads(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-never-sent")
    appmod.create_app()
    assert [(t.name, t.daemon) for t in started] == [("warm-imports", True)]
    started[0].target()  # must not raise, whatever is installed


def test_no_key_no_background_load(monkeypatch):
    started = _started_threads(monkeypatch)
    appmod.create_app()
    assert started == []
