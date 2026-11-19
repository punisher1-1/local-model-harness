from test_app import setup


def test_public_shell_has_no_data_and_protects_browser(tmp_path):
    client, _ = setup(tmp_path)
    with client:
        for path, media in (("/memory", "text/html"), ("/memory/app.js", "text/javascript"), ("/memory/style.css", "text/css")):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith(media)
            assert response.headers["cache-control"] == "no-store"
            assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
            assert response.headers["x-content-type-options"] == "nosniff"
        assert client.get("/v1/memories").status_code == 401
        assert client.get("/v1/identity").status_code == 401
        assert client.get("/memory?filename=/etc/passwd").content == client.get("/memory").content
        assert client.get("/memory/missing.js").status_code == 404
