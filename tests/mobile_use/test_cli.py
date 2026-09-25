import importlib


def test_cli_passes_locked_app_package_to_automation(monkeypatch):
    main_module = importlib.import_module("minitap.mobile_use.main")
    received = {}

    async def fake_run_automation(**kwargs):
        received.update(kwargs)

    monkeypatch.setattr(main_module, "run_automation", fake_run_automation)
    monkeypatch.setattr(main_module, "display_device_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module.telemetry, "start_session", lambda _context: "test-session")
    monkeypatch.setattr(main_module.telemetry, "end_session", lambda **_kwargs: None)

    main_module.main(
        goal="Open the approved test app",
        locked_app_package="com.marcus.boundaryproof",
    )

    assert received["locked_app_package"] == "com.marcus.boundaryproof"


def test_cli_enables_strict_app_lock(monkeypatch):
    main_module = importlib.import_module("minitap.mobile_use.main")
    received = {}

    async def fake_run_automation(**kwargs):
        received.update(kwargs)

    monkeypatch.setattr(main_module, "run_automation", fake_run_automation)
    monkeypatch.setattr(main_module, "display_device_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module.telemetry, "start_session", lambda _context: "test-session")
    monkeypatch.setattr(main_module.telemetry, "end_session", lambda **_kwargs: None)

    main_module.main(
        goal="Open the approved test app",
        locked_app_package="com.marcus.boundaryproof",
        strict_app_lock=True,
    )

    assert received["app_lock_policy"] == "strict"
