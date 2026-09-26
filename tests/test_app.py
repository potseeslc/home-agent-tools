import base64
import json
import time

import httpx
import pytest

from home_agent_tools.app import Settings, create_app, REPOS


def session(who):
    payload=base64.urlsafe_b64encode(json.dumps({'token_use':'session','email':who,'sub':who}).encode()).decode().rstrip('=')
    return 'header.'+payload+'.signature'


class Broker:
    def __init__(self):
        self.tokens={}
        self.calls=[]
        self.counter=0
        self.down=False
        self.account='alice-upstream'

    def __call__(self,request):
        path=request.url.path
        token=request.headers.get('authorization','').removeprefix('Bearer ')
        who=next((u for u in ('alice','bob') if token==session(u)),None)
        if token in self.tokens:
            who=self.tokens[token]['owner'] if self.tokens[token]['active'] else None
        if self.down:
            return httpx.Response(503)
        if path=='/auth/email/me':
            return httpx.Response(200,json={'email':who+'@example.com','full_name':who.title(),'is_admin':True,'is_active':True}) if who else httpx.Response(401)
        if not who:
            return httpx.Response(401)
        ownership={'ownerEmail':who+'@example.com','teamId':who+'-team','visibility':'private'}
        tools=[{'id':'ha','name':'ha-api-status',**ownership,'authToken':'NEVER-SEND-THIS'}, {'id':'git','name':'gitea-personal-evaluation-get-me',**ownership},{'id':'repos','name':REPOS,**ownership}]
        if path=='/tools':return httpx.Response(200,json=tools)
        if path=='/gateways':return httpx.Response(200,json=[{'id':'gitea','name':'gitea-personal-evaluation',**ownership,'oauthConfig':{'client_secret':'NEVER-SEND-THIS'}}])
        if path=='/servers':return httpx.Response(200,json=[{'id':who+'-server','name':'Home Agent Tools Evaluation',**ownership}])
        if path=='/tokens' and request.method=='POST':
            body=json.loads(request.content)
            assert body['team_id']==who+'-team'
            assert body['scope']['server_id']==who+'-server'
            self.counter+=1;new='test-token-'+str(self.counter)
            self.tokens[new]={'owner':who,'active':True,'id':str(self.counter)}
            return httpx.Response(201,json={'token':{'id':str(self.counter)},'access_token':new})
        if path.startswith('/tokens/') and request.method=='DELETE':
            for row in self.tokens.values():
                if row['id']==path.split('/')[-1] and row['owner']==who:row['active']=False
            return httpx.Response(204)
        if path=='/auth/logout':return httpx.Response(200,json={})
        if path=='/oauth/authorize/gitea':return httpx.Response(302,headers={'location':'https://git.example.com/login/oauth/authorize'})
        if path=='/rpc':
            body=json.loads(request.content)
            if body['method']=='tools/list':return httpx.Response(200,json={'jsonrpc':'2.0','id':1,'result':{'tools':tools}})
            self.calls.append(body)
            name=body['params']['name']
            result={'message':'API running.'} if name=='ha-api-status' else {'id':7,'login':self.account if who=='alice' else 'bob-upstream'}
            return httpx.Response(200,json={'jsonrpc':'2.0','id':1,'result':{'content':[{'type':'text','text':json.dumps(result)}],'isError':False}})
        return httpx.Response(404)


@pytest.fixture
async def setup(tmp_path):
    broker=Broker()
    cfg=Settings('http://broker','http://localhost:4444','a'*40,frozenset({'alice','bob'}),str(tmp_path/'state.sqlite'))
    app=create_app(cfg,httpx.MockTransport(broker))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=cfg.public_url) as client:
        client.cookies.set('jwt_token',session('alice'))
        yield client,app,broker


async def headers(client):
    result=(await client.get('/api/bootstrap')).json()
    return {'Origin':'http://localhost:4444','X-HAT-CSRF':result['csrf']}


async def check(client,service):
    return await client.post('/api/connections/'+service+'/test',headers=await headers(client))


async def enroll(client,services=None):
    services=services or ['homeassistant']
    for service in services:assert (await check(client,service)).json()['ok']
    r=await client.post('/api/agents',headers=await headers(client),json={'name':'Test agent','services':services,'days':1})
    assert r.status_code==200,r.text
    return r.json()


async def rpc(client,token,method='tools/call',params=None):
    return await client.post('/mcp',headers={'Authorization':'Bearer '+token,'Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-06-18'},json={'jsonrpc':'2.0','id':1,'method':method,'params':params or {'name':'ha-api-status','arguments':{}}})


async def test_browser_auth_and_secret_redaction(setup):
    c,app,b=setup
    response=await c.get('/api/bootstrap')
    assert response.status_code==200
    assert 'NEVER-SEND-THIS' not in response.text
    assert 'fingerprint' not in response.text
    c.cookies.clear()
    assert (await c.get('/api/bootstrap')).status_code==401
    assert (await c.post('/rpc',json={})).status_code==404


async def test_reconnect_pauses_existing_agents(setup):
    c,app,b=setup;a=await enroll(c,['gitea'])
    assert (await c.post('/api/connections/gitea/connect')).status_code==403
    assert (await rpc(c,a['token'],'tools/list',{})).status_code==200
    r=await c.post('/api/connections/gitea/connect',headers=await headers(c))
    assert r.json()['url'].startswith('https://git.example.com/')
    assert (await rpc(c,a['token'],'tools/list',{})).status_code==401


async def test_identity_survives_failed_check(setup):
    c,app,b=setup;a=await enroll(c,['gitea'])
    app.state.store.observation('alice','gitea','needs_attention')
    b.account='different-account'
    assert (await check(c,'gitea')).json()['identity_changed']
    assert (await rpc(c,a['token'],'tools/list',{})).status_code==401


async def test_malformed_calls_and_repository_bounds(setup):
    c,app,b=setup;a=await enroll(c,['gitea'])
    for args in ({'limit':1},{'per_page':51},{'page':0},{'per_page':1.5}):
        assert (await rpc(c,a['token'],params={'name':REPOS,'arguments':args})).json()['error']['code']==-32602
    assert 'result' in (await rpc(c,a['token'],params={'name':REPOS,'arguments':{'per_page':1}})).json()
    assert (await rpc(c,a['token'],params={'name':[],'arguments':{}})).json()['error']['code']==-32602


async def test_csrf_and_host_boundaries(setup):
    c,app,b=setup
    assert (await c.post('/api/connections/gitea/test')).status_code==403
    h=await headers(c);h['Origin']='https://attacker.example'
    assert (await c.post('/api/connections/gitea/test',headers=h)).status_code==403
    assert (await c.get('/health',headers={'Host':'attacker.example'})).status_code==400
    assert (await c.post('/mcp',content=b'x'*65537)).status_code==413
    assert not b.calls


async def test_strict_arguments_and_tool_grants(setup):
    c,app,b=setup;a=await enroll(c);before=len(b.calls)
    bad=await rpc(c,a['token'],params={'name':'ha-api-status','arguments':{'url':'http://metadata.invalid'}})
    assert bad.json()['error']['code']==-32602
    denied=await rpc(c,a['token'],params={'name':REPOS,'arguments':{}})
    assert denied.json()['error']['code']==-32601
    assert len(b.calls)==before
    assert (await rpc(c,a['token'])).json()['result']['isError'] is False
    names=[t['name'] for t in (await rpc(c,a['token'],'tools/list',{})).json()['result']['tools']]
    assert REPOS not in names and 'home_agent_request_connection' in names


async def test_independent_revocation_and_restart(setup):
    c,app,b=setup;a=await enroll(c);other=await enroll(c)
    response=await c.delete('/api/agents/'+a['id'],headers=await headers(c))
    assert response.json()['ok']
    assert (await rpc(c,a['token'])).status_code==401
    assert (await rpc(c,other['token'])).status_code==200
    restarted=create_app(app.state.config,httpx.MockTransport(b))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted),base_url='http://localhost:4444') as after:
        assert (await rpc(after,a['token'])).status_code==401
        assert (await rpc(after,other['token'])).status_code==200


async def test_user_cannot_revoke_or_resolve_anothers(setup):
    c,app,b=setup;a=await enroll(c)
    request=(await rpc(c,a['token'],params={'name':'home_agent_request_connection','arguments':{'service':'homeassistant'}})).json()
    link=json.loads(request['result']['content'][0]['text'])['url'];rid=link.split('=')[-1]
    c.cookies.set('jwt_token',session('bob'))
    assert (await c.delete('/api/agents/'+a['id'],headers=await headers(c))).status_code==404
    assert (await c.post('/api/requests/'+rid+'/resolve',headers=await headers(c))).status_code==404
    dashboard=(await c.get('/api/bootstrap')).json()
    assert not dashboard['agents'] and not dashboard['requests'] and not dashboard['events']


async def test_request_requires_fresh_check_and_never_grants(setup):
    c,app,b=setup;a=await enroll(c)
    result=(await rpc(c,a['token'],params={'name':'home_agent_request_connection','arguments':{'service':'homeassistant'}})).json()
    rid=json.loads(result['result']['content'][0]['text'])['url'].split('=')[-1]
    assert (await c.post('/api/requests/'+rid+'/resolve',headers=await headers(c))).status_code==409
    await check(c,'homeassistant')
    assert (await c.post('/api/requests/'+rid+'/resolve',headers=await headers(c))).status_code==200
    assert (await rpc(c,a['token'],params={'name':REPOS,'arguments':{}})).json()['error']['code']==-32601


async def test_changed_upstream_identity_disables_existing_grants(setup):
    c,app,b=setup;a=await enroll(c,['gitea'])
    b.account='different-account'
    result=(await check(c,'gitea')).json()
    assert result['identity_changed']
    assert (await rpc(c,a['token'])).status_code==401


async def test_mcp_protocol_and_expiry(setup):
    c,app,b=setup;a=await enroll(c)
    initialize=(await rpc(c,a['token'],'initialize',{'protocolVersion':'2025-06-18'})).json()
    assert initialize['result']['protocolVersion']=='2025-06-18'
    assert (await c.get('/mcp',headers={'Authorization':'Bearer '+a['token']})).status_code==405
    assert (await c.post('/mcp',headers={'Authorization':'Bearer '+a['token']},json={'jsonrpc':'2.0','method':'notifications/initialized'})).status_code==202
    with app.state.store.db() as db:db.execute('UPDATE agents SET expires=? WHERE id=?',(time.time()-1,a['id']))
    assert (await rpc(c,a['token'])).status_code==401


async def test_revocation_survives_broker_failure(setup):
    c,app,b=setup;a=await enroll(c)
    original=b.__class__.__call__
    # Broker authenticates the owner, but its token deletion endpoint fails.
    def failure(self,request):
        if request.method=='DELETE' and request.url.path.startswith('/tokens/'):return httpx.Response(503)
        return original(self,request)
    from unittest.mock import patch
    with patch.object(Broker,'__call__',failure):
        r=await c.delete('/api/agents/'+a['id'],headers=await headers(c))
        assert r.json()['upstream_revoked'] is False
    assert (await rpc(c,a['token'])).status_code==401


async def test_unverified_connections_and_extra_fields_cannot_enroll(setup):
    c,app,b=setup
    h=await headers(c)
    assert (await c.post('/api/agents',headers=h,json={'name':'bad','services':['gitea'],'days':1})).status_code==409
    assert (await c.post('/api/agents',headers=h,json={'name':'bad','services':['gitea'],'days':1,'user_email':'bob@example.com'})).status_code==422
    assert (await c.post('/api/agents',headers=h,json={'name':'bad','services':['admin'],'days':1})).status_code==422
