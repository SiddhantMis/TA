"""Private Streamlit entry point for the end-of-day scanner and journal."""
import logging

import streamlit as st

st.set_page_config(page_title="Scanner & Tracker", page_icon="◈", layout="wide")


def main():
    # Authentication must precede service construction, which opens private state.
    from scanner_tracker.security import require_app_access

    if not require_app_access():
        return

    from scanner_tracker.service import TrackerService
    from scanner_tracker.ui import render_app

    try:
        service = TrackerService.from_env()
    except Exception as exc:
        logging.getLogger(__name__).error("Tracker setup failed (%s)", type(exc).__name__)
        st.error("The private tracker is not configured. Check the deployment settings and storage location.")
        st.caption("No portfolio data has been loaded. Ask the deployment owner to check the service log.")
        return
    try:
        render_app(service)
    finally:
        engine = getattr(service, "engine", None)
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
