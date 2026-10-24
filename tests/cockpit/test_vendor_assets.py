"""Tests for vendored local static assets in YOGI Cockpit.

Verifies:
1. index.html references the local vendored Lightweight Charts asset.
2. index.html does NOT contain external CDN dependencies (unpkg.com / jsdelivr.net) for chart loading.
3. The vendored asset exists on disk with exact version 4.1.3 bytes and SHA-256 checksum.
4. The asset retains the official Apache 2.0 license notice from TradingView.
5. FastAPI serves the asset with HTTP 200 and appropriate JavaScript MIME type.
"""

import hashlib
from pathlib import Path
import pytest
from yogi.cockpit.app import create_app
from yogi.cockpit.state import AppState
from tests.cockpit.test_batch_u1_stock_detail import AsgiTestClient


EXPECTED_SHA256 = "0c146b9bfbc6e5f19da1a0de876dae43023c332d5157d82f7575f9b7653ee519"
EXPECTED_BYTE_LENGTH = 160943


def test_index_html_references_local_vendor_chart_script():
    """Verify index.html loads Lightweight Charts locally without external CDN requests."""
    html_path = Path("src/yogi/cockpit/static/index.html")
    assert html_path.exists(), "index.html missing"
    html_content = html_path.read_text(encoding="utf-8")

    # Local vendor script reference must be present
    assert '<script src="/static/js/vendor/lightweight-charts.standalone.production.js"></script>' in html_content

    # External CDN references must be absent from the startup path
    assert "unpkg.com/lightweight-charts" not in html_content
    assert "cdn.jsdelivr.net/npm/lightweight-charts" not in html_content


def test_vendor_asset_integrity_and_license():
    """Verify vendored Lightweight Charts 4.1.3 has bit-for-bit integrity and license notice."""
    asset_path = Path("src/yogi/cockpit/static/js/vendor/lightweight-charts.standalone.production.js")
    assert asset_path.exists(), "Vendored Lightweight Charts file missing"

    data = asset_path.read_bytes()
    assert len(data) == EXPECTED_BYTE_LENGTH, f"Expected length {EXPECTED_BYTE_LENGTH}, got {len(data)}"

    sha256 = hashlib.sha256(data).hexdigest()
    assert sha256 == EXPECTED_SHA256, f"Expected SHA-256 {EXPECTED_SHA256}, got {sha256}"

    # License header verification
    header = data[:400].decode("utf-8", errors="replace")
    assert "TradingView Lightweight Charts" in header
    assert "v4.1.3" in header
    assert "Licensed under Apache License 2.0" in header


def test_fastapi_serves_local_vendor_asset():
    """Verify FastAPI static route serves the vendored chart asset with HTTP 200."""
    state = AppState()
    app = create_app(app_state=state)
    client = AsgiTestClient(app)

    res = client.get("/static/js/vendor/lightweight-charts.standalone.production.js")
    assert res.status_code == 200
    content_type = res.headers.get("content-type", "").lower()
    assert "javascript" in content_type or "text/plain" in content_type
    assert len(res.body) == EXPECTED_BYTE_LENGTH
    assert hashlib.sha256(res.body).hexdigest() == EXPECTED_SHA256
