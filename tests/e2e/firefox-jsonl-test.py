"""Offline Firefox pipeline check using Camoufox's supported Playwright driver.

Run with the Camoufox Python environment after `camoufox fetch`.
Only browser assets are staged; all x.com requests are fulfilled locally.
"""
import json
import os
from pathlib import Path
import secrets
import socket
import shutil
import subprocess
import tempfile
import time

from camoufox.sync_api import Camoufox
from camoufox.addons import DefaultAddons
from marionette_driver.marionette import Marionette

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / 'tests/fixtures/sanitized'


def run():
    with tempfile.TemporaryDirectory(prefix='xtap-firefox-') as work:
        work = Path(work)
        addon = work / 'extension'
        addon.mkdir()
        for name in ['background.js', 'content-main.js', 'content-bridge.js', 'popup.html',
                     'popup.js', 'popup.css', 'debug.html', 'debug.js', 'debug.css']:
            shutil.copy2(ROOT / name, addon / name)
        for name in ['lib', 'icons']:
            shutil.copytree(ROOT / name, addon / name)
        manifest = json.loads((ROOT / 'manifest.firefox.json').read_text())
        (addon / 'manifest.json').write_text(json.dumps(manifest))
        token = secrets.token_urlsafe(32)
        (work / 'secret').write_text(token)
        def free_port():
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                return listener.getsockname()[1]
        port = free_port()
        control_port = free_port()
        output = work / 'output'
        config = dict(httpToken=token, httpPort=port, outputDir=str(output))
        background = addon / 'background.js'
        background.write_text(background.read_text().replace('// --- Init ---',
            '// --- Init ---\ngetTokenViaNative = async () => null;\nawait chrome.storage.local.set(' + json.dumps(config) + ');'))
        code = ('import sys;sys.path.insert(0,sys.argv[1]);import xtap_daemon as d;'
                'd.XTAP_SECRET=sys.argv[2];d.main()')
        env = {**os.environ, 'XTAP_DAEMON_PORT': str(port), 'XTAP_OUTPUT_DIR': str(output)}
        log = (work / 'daemon.log').open('w')
        daemon = None
        def start_daemon():
            return subprocess.Popen(['python3', '-c', code, str(ROOT / 'native-host'), str(work / 'secret')],
                                    env=env, stdout=log, stderr=log)
        launch = dict(headless=True, os='linux', addons=[str(addon)],
                      exclude_addons=[DefaultAddons.UBO], persistent_context=True,
                      user_data_dir=str(work / 'profile'), args=['-marionette'],
                      firefox_user_prefs={'marionette.port':control_port},
                      env={**os.environ, 'MOZ_REMOTE_ALLOW_SYSTEM_ACCESS':'1'})
        try:
            fixtures = {}
            expected = []
            for folder in sorted(SCENARIOS.iterdir()):
                if not folder.is_dir() or not (folder / 'fixture.json').exists():
                    continue
                fixture = json.loads((folder / 'fixture.json').read_text())
                fixtures[json.loads((folder / 'manifest.json').read_text())['endpoint']] = fixture
                expected.extend(json.loads(line) for line in (folder / 'expected.jsonl').read_text().splitlines())
            with Camoufox(**launch) as context:
                requests = []
                def serve(route):
                    requests.append(route.request.url)
                    endpoint = route.request.url.rsplit('/', 1)[-1]
                    if endpoint in fixtures:
                        route.fulfill(json=fixtures[endpoint])
                    elif route.request.resource_type == 'document':
                        script = ','.join('fetch(' + json.dumps('/i/api/graphql/offline/' + ep) + ').then(r=>r.json())' for ep in fixtures)
                        route.fulfill(content_type='text/html', body='<html><head></head><body>Offline xTap fixture test<script>Promise.all([' + script + ']).then(()=>document.body.dataset.loaded="yes")</script></body></html>')
                    else:
                        route.abort()
                context.route('**/*', serve)
                page = context.new_page()
                page.goto('https://x.com/xtap-offline-test')
                page.locator('body[data-loaded="yes"]').wait_for()
                control = Marionette('127.0.0.1', port=control_port)
                control.start_session()
                try:
                    control.set_context('chrome')
                    uuid = control.execute_script("return JSON.parse(Services.prefs.getStringPref('extensions.webextensions.uuids'))['xtap@mkubicek.dev']")
                    control.set_context('content')
                    status_tab = control.open(type='tab', focus=False)
                    control.switch_to_window(status_tab['handle'], focus=False)
                    control.navigate(f'moz-extension://{uuid}/popup.html')
                    def status():
                        return control.execute_async_script("const done=arguments[arguments.length-1]; browser.runtime.sendMessage({type:'GET_STATUS'}).then(done);", sandbox=None)
                    deadline = time.monotonic() + 20
                    state = status()
                    while state['buffered'] < len(expected) and time.monotonic() < deadline:
                        page.wait_for_timeout(100)
                        state = status()
                    assert state['buffered'] == len(expected), state
                    before = state['sessionCount']
                    assert before == len(expected), state
                    control.set_context('chrome')
                    control.execute_async_script("const done=arguments[arguments.length-1]; const {ExtensionParent}=ChromeUtils.importESModule('resource://gre/modules/ExtensionParent.sys.mjs'); ExtensionParent.GlobalManager.getExtension('xtap@mkubicek.dev').terminateBackground().then(done);", sandbox=None)
                    control.set_context('content')
                    state = status()
                    assert state['sessionCount'] == before, state
                    assert state['buffered'] == len(expected), state
                    print(f'PASS background restart: session count and {len(expected)} pending posts retained', flush=True)
                finally:
                    control.delete_session()
            # A full browser restart clears session storage. The durable queue
            # must still be delivered immediately when the daemon returns.
            daemon = start_daemon()
            with Camoufox(**launch) as context:
                context.route('**/*', lambda route: route.abort())
                page = context.new_page()
                deadline = time.monotonic() + 65
                actual = []
                while time.monotonic() < deadline:
                    actual = [json.loads(line) for p in output.glob('tweets-*.jsonl') for line in p.read_text().splitlines()]
                    if len(actual) >= len(expected):
                        break
                    page.wait_for_timeout(500)
                def canonical(rows):
                    return sorted(({k:v for k,v in r.items() if k != 'captured_at'} for r in rows), key=lambda r:r['id'])
                assert canonical(actual) == canonical(expected), f'captured {len(actual)} of {len(expected)} expected posts'
                assert all(url.startswith('https://x.com/') for url in requests)
                print(f'PASS Firefox: {len(actual)} posts exactly match fixtures; all page requests handled locally', flush=True)
        finally:
            if daemon is not None:
                daemon.terminate()
                daemon.wait(timeout=20)
            log.close()


if __name__ == '__main__':
    run()
