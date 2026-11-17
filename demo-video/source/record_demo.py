"""Record the real demo UI against explicit test doubles; never contacts a real DB.

Requires repository dependencies and playwright. Chrome and Playwright ffmpeg
must be available. Use PLAYWRIGHT_BROWSERS_PATH for an isolated tool cache.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from playwright.async_api import async_playwright
from werkzeug.serving import make_server
from app import create_app
from mysql_fido_gateway import Gateway
from tests.fake_mysql import FakeMySQL
from tests.software_key import SoftwareKey
import mysql_fido_gateway.flask_util as flask_util

OUT = ROOT / 'demo-video'
WORK = Path(os.environ.get('DEMO_WORK', '/private/tmp/gateway-video-work'))
WORK.mkdir(exist_ok=True, parents=True)


class RecordingMySQL(FakeMySQL):
    def handle(self, sock):
        sock.settimeout(120)
        return super().handle(sock)


class AdminFixture:
    """In-memory provisioning fixture, scoped exclusively to the video harness."""
    account_created = False
    def __init__(self):
        self.row = None
    def cursor(self): return self
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def close(self): pass
    def fetchone(self): return self.row
    def execute(self, sql, params=None):
        time.sleep(.4)
        if sql.startswith('SELECT PLUGIN_STATUS'): self.row = ('ACTIVE',)
        elif sql.startswith('SELECT @@GLOBAL'): self.row = ('localhost', 180)
        elif sql.startswith('CREATE USER'):
            assert params == ('demo_video', 'localhost', 'correct-password')
            AdminFixture.account_created = True
        elif not sql.startswith('SET PERSIST'):
            raise AssertionError('Unexpected fixture SQL: ' + sql)


AUTH_SCRIPT = r"""
(() => {
  const b64 = a => btoa(String.fromCharCode(...new Uint8Array(a))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
  const buf = s => Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')), c=>c.charCodeAt(0)).buffer;
  async function credential(operation, options) {
    const source = options.publicKey;
    const encoded = {...source, challenge:b64(source.challenge)};
    if(source.user) encoded.user = {...source.user, id:b64(source.user.id)};
    if(source.allowCredentials) encoded.allowCredentials = source.allowCredentials.map(c=>({...c,id:b64(c.id)}));
    const modal = document.createElement('div');
    modal.id='demo-authenticator';
    document.body.append(modal);
    const keyIcon='<svg width="78" height="68" viewBox="0 0 100 80" aria-hidden="true"><rect x="30" y="18" width="40" height="58" rx="10" fill="#163e50"/><rect x="38" y="2" width="24" height="22" rx="3" fill="#a7b9c1"/><rect x="43" y="5" width="4" height="10" fill="#e7ecee"/><rect x="53" y="5" width="4" height="10" fill="#e7ecee"/><circle class="key-touch" cx="50" cy="48" r="11" fill="#edb651"/><circle cx="50" cy="48" r="5" fill="#fce7b8"/></svg>';
    const heading = operation==='create'?'Register your security key':'Sign in with your security key';
    const steps=operation==='create'?['Security key','PIN','Touch']:['Security key','Touch'];
    const frame = (content,step) => `<div class="demo-key-card"><div class="demo-key-tag">ILLUSTRATED SECURITY PROMPT · SIMULATED</div><div class="demo-key-icon">${keyIcon}</div><div class="demo-dialog-origin">localhost · ${operation==='create'?'Registration':'Sign in'}</div><h2>${heading}</h2><div class="demo-key-steps">${steps.map((s,i)=>`<span class="${i===step?'current':i<step?'done':''}">${i+1}. ${s}</span>`).join('')}</div>${content}<small class="demo-prompt-note">Prompt wording and order vary by browser, OS, and key.<br>This is a recording illustration, not an actual system dialog.</small></div>`;
    modal.innerHTML=frame('<h3>Use your security key</h3><p>Insert your USB security key into this computer.</p><div class="demo-device">USB security key / physical token</div><button id="choose-demo-key">Continue with security key</button>',0);
    await new Promise(resolve=>document.querySelector('#choose-demo-key').onclick=resolve);
    if(operation==='create') {
    modal.innerHTML=frame('<h3>Enter your security key PIN</h3><p>Unlock the connected security key to continue.</p><label for="demo-key-pin">Security key PIN</label><input id="demo-key-pin" type="password" inputmode="numeric" autocomplete="off" placeholder="Enter key PIN"><small>Use the PIN set on this key, not your database password.</small><button id="submit-demo-pin" disabled>Continue</button>',1);
    const input=document.querySelector('#demo-key-pin');
    const next=document.querySelector('#submit-demo-pin');
    input.oninput=()=>next.disabled=input.value.length<4;
    await new Promise(resolve=>next.onclick=()=>{input.value='';resolve()});
    }
    modal.innerHTML=frame('<h3>Touch your security key</h3><p>Touch the flashing contact on your physical token.</p><div class="demo-device">Waiting for a touch…</div><button id="touch-demo-key">Simulate touching the key</button>',steps.length-1);
    await new Promise(resolve=>document.querySelector('#touch-demo-key').onclick=resolve);
    modal.remove();
    const result=await window.recordingAuthenticator(operation,encoded);
    const response=Object.fromEntries(Object.entries(result.response).map(([k,v])=>[k,v?buf(v):null]));
    response.getTransports=()=>['usb'];
    return {...result,rawId:buf(result.rawId),response,getClientExtensionResults:()=>({})};
  }
  Object.defineProperty(navigator.credentials,'create',{value:options=>credential('create',options)});
  Object.defineProperty(navigator.credentials,'get',{value:options=>credential('get',options)});
})();
"""


async def main():
    os.environ.update(ADMIN_TOKEN='recording-only-token', DB_ACCOUNT_HOST='localhost',
                      BROWSER_ORIGIN='https://localhost', RP_ID='localhost')
    server = RecordingMySQL()
    key = SoftwareKey()
    gateway = Gateway({'host':'127.0.0.1','port':server.port,'ssl_disabled':True},
                      'https://localhost','localhost',allow_loopback_plaintext=True)
    original_connect = flask_util.mysql.connector.connect
    def fixture_connect(**kwargs):
        assert kwargs['user']=='root' and kwargs['password']=='recording-root-password'
        return AdminFixture()
    flask_util.mysql.connector.connect = fixture_connect
    app = create_app(gateway)
    http = make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
            context = await browser.new_context(viewport={'width':1600,'height':760},bypass_csp=True,
                record_video_dir=str(WORK/'raw'),record_video_size={'width':1600,'height':760})
            async def forward(route):
                req=route.request
                headers=await req.all_headers()
                headers['host']='localhost'
                response=await route.fetch(url=f'http://127.0.0.1:{http.server_port}'+urlsplit(req.url).path,headers=headers)
                await route.fulfill(response=response)
            await context.route('https://localhost/**',forward)
            async def authenticate(source,operation,options):
                assert AdminFixture.account_created
                if operation=='get':
                    assert options['userVerification']=='discouraged'
                    key.user_verified=False
                return key(operation,options)
            await context.expose_binding('recordingAuthenticator',authenticate)
            await context.add_init_script(AUTH_SCRIPT)
            page=await context.new_page()
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            await page.goto('https://localhost/')
            await page.add_style_tag(content='''
                html{scroll-behavior:smooth} main{padding-top:16px;padding-bottom:16px}
                header{margin-bottom:18px} h1{font-size:42px} header p{margin:8px 0}
                section{padding:20px} .setup-banner{display:none}
                main > p.profile{display:none}
                body.stage-mode header,body.stage-mode footer{display:none}
                body.stage-mode section p{min-height:70px;font-size:15px;margin-bottom:10px}
                body.stage-mode label{margin-top:12px;font-size:15px}
                body.stage-mode input{padding:9px 11px;font-size:17px}
                body.stage-mode button{margin-top:18px;margin-bottom:12px}
                body.stage-mode small{margin-top:8px}
                .columns>section{transition:opacity .4s,box-shadow .4s,border-color .4s}
                body.stage-mode .columns>section:not(.recording-active){opacity:.40}
                .columns>section.recording-active{border-color:#dba34b;box-shadow:0 0 0 3px #e6b05b55}
                .columns>section.recording-active input:focus{background:#fffcf1;outline:3px solid #dfaa51}
                .proof{font-size:13px;line-height:1.5}
                .operation-notifications{padding:12px 18px;margin-bottom:16px}
                .operation-notifications pre{max-height:112px}
                #demo-authenticator{position:fixed;inset:0;background:#102b3f90;display:grid;place-items:center;z-index:99999;backdrop-filter:blur(3px)}
                .demo-key-card{width:560px;padding:24px 32px;background:white;border-radius:18px;box-shadow:0 25px 80px #102b3f55}
                .demo-key-tag{font-size:12px;font-weight:750;letter-spacing:1.3px;color:#176f68}
                .demo-key-icon{text-align:center;height:72px;margin-top:12px}
                .demo-dialog-origin{text-align:center;color:#647984;font-size:13px}
                .demo-key-card h2{text-align:center;margin:9px 0 16px;font-size:26px}
                .demo-key-card h3{font-size:21px;margin:20px 0 5px}
                .demo-key-card p{color:#526873;min-height:0!important;font-size:17px!important;margin:8px 0}
                .demo-key-card label{font-size:16px!important}
                .demo-key-card input{font-size:22px!important;letter-spacing:5px}
                .demo-key-card button{margin-bottom:0;font-size:17px}
                .demo-key-steps{display:flex;justify-content:space-between;gap:10px;border-bottom:1px solid #dfebed;padding-bottom:14px}
                .demo-key-steps span{font-size:13px;color:#81929b;background:#f0f4f6;padding:5px 14px;border-radius:15px}
                .demo-key-steps .current{color:#80540c;background:#fff0cf;font-weight:750}
                .demo-key-steps .done{color:#16665b;background:#e4f4ee}
                .demo-device{background:#eff5f7;padding:12px 16px;border:1px solid #cfdee2;border-radius:8px;color:#214959;margin-top:16px}
                .demo-prompt-note{font-size:11px!important;line-height:1.4!important;text-align:center;margin-top:14px!important}
                .key-touch{animation:pulse-key 1.4s infinite}@keyframes pulse-key{50%{opacity:.3}}
                #recording-cursor{position:fixed;width:24px;height:24px;border:3px solid #e49a37;border-radius:50%;background:#e49a3722;z-index:999999;pointer-events:none;transform:translate(-50%,-50%)}
            ''')
            await page.evaluate("""() => {const el=document.createElement('div');el.id='recording-cursor';el.style.left='1450px';el.style.top='160px';document.body.append(el);document.addEventListener('mousemove',e=>{el.style.left=e.clientX+'px';el.style.top=e.clientY+'px'})}""")
            await page.locator('.columns input[name=username]').evaluate_all("els=>els.forEach(el=>el.value='')")
            await page.locator('form[data-action=create] input[name=admin_token]').fill('')
            started=time.monotonic()
            async def until(t):
                await asyncio.sleep(max(0,t-(time.monotonic()-started)))
            async def aim(locator):
                await locator.scroll_into_view_if_needed()
                box=await locator.bounding_box()
                await page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2,steps=20)
            async def type_field(form,name,value):
                el=form.locator('[name="'+name+'"]')
                await aim(el)
                await el.fill('')
                await el.press_sequentially(value,delay=110)
                await asyncio.sleep(.4)
            async def click(el):
                await aim(el)
                await el.click()
            async def shot(name):
                await page.screenshot(path=str(OUT/'preview'/name))
            async def stage(action):
                await page.evaluate("""action=>{document.body.classList.add('stage-mode');document.querySelectorAll('.columns>section').forEach(s=>s.classList.toggle('recording-active',s.querySelector('form').dataset.action===action));window.scrollTo(0,0)}""",action)
                await asyncio.sleep(.5)
            await shot('01-overview.png')
            await until(8)
            await stage('create')
            create=page.locator('form[data-action=create]')
            await type_field(create,'admin_token','recording-only-token')
            await type_field(create,'root_password','recording-root-password')
            await type_field(create,'username','demo_video')
            await type_field(create,'password','correct-password')
            await shot('02-typing-create-user.png')
            await until(28)
            await click(create.locator('button'))
            await page.get_by_text('Created demo_video@localhost. Register its YubiKey next.',exact=True).last.wait_for()
            await shot('03-user-created.png')
            await until(35)
            await stage('register')
            register=page.locator('form[data-action=register]')
            await type_field(register,'username','demo_video')
            await type_field(register,'password','correct-password')
            await until(45)
            await click(register.locator('button'))
            await page.locator('#choose-demo-key').wait_for()
            await until(49)
            await click(page.locator('#choose-demo-key'))
            await until(53)
            pin=page.locator('#demo-key-pin')
            await aim(pin)
            await pin.click()
            await pin.press_sequentially('654321',delay=350)
            await shot('04-registration-pin.png')
            await until(59)
            await click(page.locator('#submit-demo-pin'))
            await shot('04-registration-prompt.png')
            await until(65)
            await click(page.locator('#touch-demo-key'))
            await page.get_by_text('MySQL accepted registration. Test login next.',exact=True).last.wait_for()
            await shot('05-key-registered.png')
            await until(72)
            await stage('login')
            login=page.locator('form[data-action=login]')
            await type_field(login,'username','demo_video')
            await type_field(login,'password','correct-password')
            await until(83)
            await click(login.locator('button'))
            await page.locator('#choose-demo-key').wait_for()
            await until(88)
            await click(page.locator('#choose-demo-key'))
            await page.locator('#touch-demo-key').wait_for()
            assert await page.locator('#demo-key-pin').count()==0
            assert 'PIN' not in await page.locator('#demo-authenticator').inner_text()
            await shot('06-login-touch.png')
            await until(94)
            await click(page.locator('#touch-demo-key'))
            proof=page.locator('.proof')
            await page.wait_for_function("document.querySelector('.proof').textContent.includes('demo_video@localhost')")
            result=json.loads(await proof.inner_text())
            assert result['message']=='hello world'
            assert result['mysql_account']=='demo_video@localhost'
            assert result['server_version']=='8.4.0-protocol-fixture'
            await shot('06-login-result.png')
            await until(98)
            await page.evaluate("document.querySelectorAll('.columns>section').forEach(s=>s.classList.add('recording-active'))")
            await page.mouse.move(1450,600,steps=20)
            await until(108)
            assert not errors,errors
            assert not server.errors,server.errors
            video=page.video
            await context.close()
            await video.save_as(str(WORK/'walkthrough.webm'))
            await browser.close()
            (OUT/'source'/'validation.json').write_text(json.dumps({'account_created':AdminFixture.account_created,'login_pin_prompt':False,'login_user_verified':key.user_verified,'login_result':result,'browser_errors':errors,'protocol_errors':[str(e) for e in server.errors],'sql_commands':[s for s in server.commands if 'FINISH REGISTRATION' not in s]},indent=2))
            print('Recording complete: all three workflow results verified.',flush=True)
    finally:
        http.shutdown()
        server.close()
        flask_util.mysql.connector.connect=original_connect


if __name__=='__main__':
    asyncio.run(main())
