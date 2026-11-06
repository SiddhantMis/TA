"""Access-control regressions without reading deployment secrets or opening private state."""
from unittest.mock import patch
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from scanner_tracker.security import hash_password


def protected_fixture():
    import streamlit as st
    from scanner_tracker.security import require_app_access
    if require_app_access():
        st.write("PRIVATE SYNTHETIC SENTINEL")


def visible(app):
    return "\n".join(item.value for item in app.markdown)


def test_missing_hash_stops_before_private_content(monkeypatch):
    monkeypatch.setenv("TRACKER_DEMO", "0")
    with patch("scanner_tracker.security.secret_value", side_effect=lambda name, default=None: default):
        app = AppTest.from_function(protected_fixture).run()
    assert not app.exception
    assert "PRIVATE SYNTHETIC SENTINEL" not in visible(app)
    assert any("Private setup required" in item.value for item in app.info)


def test_production_demo_flag_never_bypasses_access_control(monkeypatch):
    monkeypatch.setenv("TRACKER_DEMO", "1")
    with patch("scanner_tracker.security.secret_value", side_effect=lambda name, default=None: "production" if name == "TRACKER_ENV" else default):
        app = AppTest.from_function(protected_fixture).run()
    assert not app.exception
    assert "PRIVATE SYNTHETIC SENTINEL" not in visible(app)
    assert app.error


def test_valid_hash_rejects_wrong_password_and_allows_correct_password(monkeypatch):
    monkeypatch.setenv("TRACKER_DEMO", "0")
    password = "synthetic test password only"
    encoded = hash_password(password, iterations=100000)
    with patch("scanner_tracker.security.secret_value", side_effect=lambda name, default=None: encoded if name == "TRACKER_APP_PASSWORD_HASH" else default):
        app = AppTest.from_function(protected_fixture).run()
        app.text_input[0].set_value("wrong test password")
        app.button[0].click().run()
        assert "PRIVATE SYNTHETIC SENTINEL" not in visible(app)
        assert any("Incorrect" in item.value for item in app.error)
        app.text_input[0].set_value(password)
        app.button[0].click().run()
        assert not app.exception
        assert "PRIVATE SYNTHETIC SENTINEL" in visible(app)


def test_password_hash_rotation_revokes_cached_application_access(monkeypatch):
    monkeypatch.setenv("TRACKER_DEMO", "0")
    values = {"TRACKER_APP_PASSWORD_HASH": hash_password("synthetic first password", iterations=100000)}
    with patch("scanner_tracker.security.secret_value", side_effect=lambda name, default=None: values.get(name, default)):
        app = AppTest.from_function(protected_fixture).run()
        app.text_input[0].set_value("synthetic first password")
        app.button[0].click().run()
        assert "PRIVATE SYNTHETIC SENTINEL" in visible(app)
        values["TRACKER_APP_PASSWORD_HASH"] = hash_password("synthetic second password", iterations=100000)
        app.run()
        assert "PRIVATE SYNTHETIC SENTINEL" not in visible(app)
        assert len(app.text_input) == 1


def test_demo_flag_rejects_configured_account_storage_in_guard_and_service(monkeypatch):
    from scanner_tracker.service import TrackerService

    monkeypatch.setenv("TRACKER_DEMO", "1")
    values = {"TRACKER_ENV": "local", "DATABASE_URL": "sqlite:///:memory:"}
    read_secret = lambda name, default=None: values.get(name, default)
    with patch("scanner_tracker.security.secret_value", side_effect=read_secret):
        app = AppTest.from_function(protected_fixture).run()
    assert "PRIVATE SYNTHETIC SENTINEL" not in visible(app)
    assert app.error
    with patch("scanner_tracker.service.secret_value", side_effect=read_secret), patch.object(TrackerService, "__init__", return_value=None) as initialize:
        with pytest.raises(ValueError, match="Demo|demo"):
            TrackerService.from_env()
        initialize.assert_not_called()


def test_local_demo_without_configured_storage_uses_only_dedicated_demo_database(monkeypatch):
    from scanner_tracker.service import TrackerService

    class UnopenedService(TrackerService):
        def __init__(self, database_url):
            self.selected_database = database_url

    monkeypatch.setenv("TRACKER_DEMO", "1")
    with patch("scanner_tracker.service.secret_value", side_effect=lambda name, default=None: "local" if name == "TRACKER_ENV" else default):
        service = UnopenedService.from_env()
    assert service.selected_database == "sqlite:///.local/demo.db"


@pytest.mark.parametrize("sslmode", ["prefer", "allow", "disable"])
def test_production_database_refuses_optional_or_disabled_tls(monkeypatch, sslmode):
    from scanner_tracker.db import make_engine

    monkeypatch.setenv("TRACKER_ENV", "production")
    with patch("scanner_tracker.db.create_engine") as connect:
        with pytest.raises(ValueError, match="TLS"):
            make_engine(f"postgresql+psycopg://synthetic:synthetic@invalid.test/fixture?sslmode={sslmode}")
        connect.assert_not_called()


@pytest.mark.parametrize("sslmode", ["require", "verify-ca", "verify-full"])
def test_strict_tls_is_forwarded_to_engine_without_any_network_connection(monkeypatch, sslmode):
    from scanner_tracker.db import make_engine

    monkeypatch.setenv("TRACKER_ENV", "production")
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    with patch("scanner_tracker.db.create_engine", return_value=engine) as connect:
        assert make_engine(f"postgresql+psycopg://synthetic:synthetic@invalid.test/fixture?sslmode={sslmode}") is engine
    assert connect.call_args.kwargs["connect_args"]["sslmode"] == sslmode
    assert connect.call_args.kwargs["hide_parameters"] is True
