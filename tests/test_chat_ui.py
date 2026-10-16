from fastapi import FastAPI
from fastapi.testclient import TestClient
from dataclasses import replace
from test_app import setup, HEADERS
import chat_ui


def test_profile_catalog_requires_auth_and_filters_permissions(tmp_path, monkeypatch):
    client,_=setup(tmp_path)
    with client:
        assert client.get('/v1/profiles').status_code==401
        assert client.get('/v1/profiles',headers=HEADERS).json()=={'data':[{'id':'local','skills':[],'default_skill':None,'skill_info':[],'mcp_servers':[]}]}
        identity=client.app.state.identity
        principal=identity.authenticate(HEADERS['Authorization'])
        monkeypatch.setattr(identity,'authenticate',lambda _:replace(principal,profiles=frozenset()))
        assert client.get('/v1/profiles',headers=HEADERS).json()=={'data':[]}


def test_static_chat_has_no_secrets_and_constrained_paths(tmp_path,monkeypatch):
    (tmp_path/'assets').mkdir();(tmp_path/'index.html').write_text('<h1>Chat shell</h1>');(tmp_path/'assets/app.js').write_text('console.log("hello")')
    monkeypatch.setattr(chat_ui,'ROOT',tmp_path)
    app=FastAPI();chat_ui.install_chat_ui(app)
    with TestClient(app) as c:
        r=c.get('/chat');assert r.status_code==200
        assert 'frame-ancestors' in r.headers['content-security-policy']
        assert r.headers['cache-control']=='no-store'
        assert c.get('/chat/assets/app.js').status_code==200
        assert c.get('/chat/assets/%2e%2e/index.html').status_code==404
