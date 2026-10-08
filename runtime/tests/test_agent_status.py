from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from astra_daemon.ownership import Ownership
from astra_daemon.server import application


@pytest.mark.asyncio
async def test_static_get_agent_status_returns_the_public_owner():
    owner=Ownership(mode='agent',name='Fixture',token='private-session-token',since=123)
    runtime=SimpleNamespace(owner=owner)
    app=application(runtime,'a'*32)
    app.cleanup_ctx.clear()  # This handler test needs no engine/telemetry lifecycle.
    async with TestClient(TestServer(app)) as client:
        response=await client.get('/v1/agent/status',headers={'Authorization':'Bearer '+'a'*32})
        assert response.status==200
        value=await response.json()
        assert value=={'ok':True,'result':{'mode':'agent','name':'Fixture','since':123}}
        assert 'private-session-token' not in str(value)
