"""Owner-only access in addition to Community Cloud's private-app setting."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets


def hash_password(password: str, *, iterations=600_000):
    if len(password) < 12:
        raise ValueError("Use an application password with at least 12 characters.")
    salt = secrets.token_bytes(24)
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(value).decode()}"


def verify_password(password, encoded):
    try:
        algorithm, count, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or not 100_000 <= int(count) <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt, validate=True), int(count))
        return hmac.compare_digest(actual, base64.b64decode(expected, validate=True))
    except (ValueError, TypeError):
        return False


def secret_value(name, default=None):
    if os.environ.get(name):
        return os.environ[name]
    try:
        import streamlit as st
        return st.secrets.get(name, default)
    except (FileNotFoundError, RuntimeError):
        return default


def require_app_access():
    import streamlit as st
    if os.environ.get("TRACKER_DEMO") == "1":
        if secret_value("TRACKER_ENV", "local") != "local" or secret_value("DATABASE_URL"):
            st.error("Demo mode requires local development with DATABASE_URL unset; it cannot open a configured private database.")
            st.stop()
        st.warning("LOCAL DEMO — synthetic data and virtual accounts only.")
        return True
    encoded = secret_value("TRACKER_APP_PASSWORD_HASH")
    if not encoded:
        st.info("Private setup required: configure TRACKER_APP_PASSWORD_HASH and DATABASE_URL in server secrets. See DEPLOYMENT.md.")
        st.stop()
    fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
    if st.session_state.get("owner_authenticated") == fingerprint:
        return True
    st.title("TA & Momentum Tracker")
    with st.form("owner_login", clear_on_submit=True):
        password = st.text_input("Application password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        if verify_password(password, encoded):
            st.session_state["owner_authenticated"] = fingerprint
            st.rerun()
        else:
            st.error("Incorrect application password.")
    st.stop()
