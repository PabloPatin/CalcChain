from __future__ import annotations

from calcchain_backend.app import _frontend_response_path


def test_frontend_response_path_serves_static_file(tmp_path):
    static_root = tmp_path / "web"
    asset = static_root / "assets" / "app.js"
    asset.parent.mkdir(parents=True)
    (static_root / "index.html").write_text("<html></html>", encoding="utf-8")
    asset.write_text("console.log('calcchain')", encoding="utf-8")

    assert _frontend_response_path(static_root.resolve(), "assets/app.js") == asset.resolve()


def test_frontend_response_path_falls_back_to_index_for_spa_route(tmp_path):
    static_root = tmp_path / "web"
    static_root.mkdir()
    index = static_root / "index.html"
    index.write_text("<html></html>", encoding="utf-8")

    assert _frontend_response_path(static_root.resolve(), "projects/123") == index.resolve()


def test_frontend_response_path_does_not_serve_outside_static_root(tmp_path):
    static_root = tmp_path / "web"
    static_root.mkdir()
    index = static_root / "index.html"
    index.write_text("<html></html>", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")

    assert _frontend_response_path(static_root.resolve(), "../secret.txt") == index.resolve()


def test_frontend_response_path_requires_index(tmp_path):
    static_root = tmp_path / "web"
    static_root.mkdir()

    assert _frontend_response_path(static_root.resolve(), "projects") is None
