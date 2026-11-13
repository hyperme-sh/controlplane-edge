"""Startup guard runs before publisher, gRPC and HTTP client setup."""
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from controlplane_api import config
from controlplane_edge import main

@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('api_key_exchange_jwt_secret',''),
    ('api_keys_internal_token','short'),('api_keys_internal_token','dev-'+'x'*48)])
async def test_startup_rejects_weak_secrets_before_opening_clients(monkeypatch,field,value):
    monkeypatch.setattr(config.settings,'edge_secrets_required',True)
    monkeypatch.setattr(config.settings,'api_key_exchange_jwt_secret','a'*48)
    monkeypatch.setattr(config.settings,'api_keys_internal_token','b'*48)
    monkeypatch.setattr(config.settings,field,value)
    opened=[]
    monkeypatch.setattr(main,'AccessEventPublisher',lambda settings:opened.append('publisher'))
    app=FastAPI()
    app.state.edge_settings=SimpleNamespace()
    with pytest.raises(ValueError,match=field.upper()):
        async with main.lifespan(app):
            pytest.fail('Started with invalid secrets')
    assert opened==[]
