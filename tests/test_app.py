"""Smoke-test every page of the Streamlit app (skipped if streamlit is not installed).

Synthetic data — for demonstration only.
"""

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

PAGES = ["Network", "Send a request", "Measures", "Data quality", "Audit log", "About"]


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(repo_root, page):
    at = AppTest.from_file(str(repo_root / "app" / "streamlit_app.py"), default_timeout=60)
    at.run()
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, at.exception
    assert any("Synthetic data" in w.value for w in at.sidebar.warning)


@pytest.mark.parametrize(
    "requester,purpose,op,status",
    [
        ("lkdph", "T-PH", "bulk-export", "HTTP 202"),
        ("acme-health-plan", "T-PH", "bulk-export", "HTTP 403"),
        ("amc-clinician", "T-TREAT", "patient-query", "HTTP 200"),
    ],
)
def test_request_simulator(repo_root, requester, purpose, op, status):
    at = AppTest.from_file(str(repo_root / "app" / "streamlit_app.py"), default_timeout=60)
    at.run()
    at.sidebar.radio[0].set_value("Send a request").run()
    at.selectbox[0].set_value(requester).run()
    at.selectbox[1].set_value(purpose).run()
    at.selectbox[2].set_value(op).run()
    at.button[0].click().run()
    assert not at.exception, at.exception
    assert any(s.value == status for s in at.subheader), [s.value for s in at.subheader]
