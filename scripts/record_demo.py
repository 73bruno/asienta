#!/usr/bin/env python3
"""Record the demo video: a scripted, 30-second run of `asienta --demo` in a real browser.

    pip install -e ".[dev]"                        (playwright; or use your Chrome with --chrome)
    python scripts/record_demo.py --chrome         -> docs/media/demo.mp4 and docs/media/demo.gif
    python scripts/record_demo.py --screenshots --chrome
    python scripts/record_demo.py --social --chrome

Frames come from the browser's own screencast (sharp text, unlike a screen recorder), a cursor
shows where it clicks and short captions say what is happening. Needs ffmpeg on the PATH.
Everything shown is demo data: fictional suppliers and ledger, a staged restaurant ticket.
"""
import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
SAMPLES = os.path.join(ROOT, 'asienta', 'demo', 'invoices')
OUT = os.path.join(ROOT, 'docs', 'media')

CAPTIONS = {
    'arrive': 'Invoices arrive by email, upload or phone photo',
    'email': 'Attachments are picked up; signature logos are set aside',
    'read': 'Any AI model reads it: Gemini, Claude, OpenAI or a local model',
    'check': 'Rules check every figure. This printed tax ID fails its check digit',
    'fix': 'One click fixes it with the one in your ledger',
    'split': 'Each line goes to the right account: the wine to drinks',
    'export': 'Export to Sage 50, A3, Holded, Xero, QuickBooks, CSV…',
    'done': 'One file, ready to import',
    'license': 'Open source · MIT · unlimited commercial use',
}

OVERLAY_JS = r"""
(() => {
  if (window.__demo) return;
  const css = document.createElement('style');
  css.textContent = `
    #demo-cursor{position:fixed;left:0;top:0;width:22px;height:22px;z-index:99999;pointer-events:none;
      transform:translate(-3px,-2px);transition:transform .05s}
    #demo-cursor svg{width:22px;height:22px;filter:drop-shadow(0 2px 3px rgba(0,0,0,.35))}
    .demo-ripple{position:fixed;z-index:99998;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;
      pointer-events:none;border:3px solid var(--accent);animation:demo-rip .5s ease-out forwards}
    @keyframes demo-rip{from{transform:scale(.3);opacity:1}to{transform:scale(1.4);opacity:0}}
    #demo-caption{position:fixed;left:50%;bottom:92px;transform:translate(-50%,12px);z-index:99990;opacity:0;
      background:rgba(17,17,20,.92);color:#fff;font:600 21px/1.35 Inter,system-ui,sans-serif;letter-spacing:-.01em;
      padding:13px 24px;border-radius:14px;box-shadow:0 18px 50px rgba(0,0,0,.35);transition:all .35s;max-width:78vw;
      text-align:center;backdrop-filter:blur(8px)}
    #demo-caption.on{opacity:1;transform:translate(-50%,0)}
`;
  document.head.append(css);
  const cur = document.createElement('div');
  cur.id = 'demo-cursor';
  cur.innerHTML = '<svg viewBox="0 0 24 24"><path d="M3 2l7.5 19 2.6-7.4L20.5 11z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  const cap = document.createElement('div'); cap.id = 'demo-caption';
  document.body.append(cur, cap);
  addEventListener('mousemove', e => { cur.style.left = e.clientX + 'px'; cur.style.top = e.clientY + 'px'; }, true);
  addEventListener('mousedown', e => {
    const r = document.createElement('div'); r.className = 'demo-ripple';
    r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
    document.body.append(r); setTimeout(() => r.remove(), 600);
  }, true);
  window.__demo = {
    caption(t) { if (!t) return cap.classList.remove('on'); cap.textContent = t; cap.classList.add('on'); },
  };
})();
"""


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_server(port, lang='en'):
    from asienta.app import App
    from asienta.cli import DEMO_INI
    from asienta.config import Settings
    from asienta.extraction.demo import DemoReader
    from asienta.server import make_server
    settings = Settings(DEMO_INI, overrides={'app': {'data': tempfile.mkdtemp(prefix='asienta-rec-'), 'language': lang},
                                             # white-label: the business's own name, not a product brand
                                             'brand': {'name': 'Demo Bistro', 'tagline': 'Supplier invoices'}})
    app = App(settings, reader=DemoReader(delay=(0.05, 0.1)), log=lambda m: None)
    app.ledger.refresh()
    threading.Thread(target=app.background, daemon=True).start()
    srv = make_server(app, '127.0.0.1', port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return app


def settle(app, timeout=30):
    for _ in range(int(timeout / 0.1)):
        if not app.db.with_status('reading'):
            return
        time.sleep(0.1)


class Recorder:
    """Chrome DevTools screencast: every painted frame with its timestamp."""

    def __init__(self, page, folder, width):
        self.page, self.folder, self.frames = page, folder, []
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on('Page.screencastFrame', self.frame)
        self.cdp.send('Page.startScreencast', {'format': 'jpeg', 'quality': 92, 'maxWidth': width, 'maxHeight': width,
                                               'everyNthFrame': 1})

    def frame(self, ev):
        import base64
        path = os.path.join(self.folder, f'{len(self.frames):06d}.jpg')
        with open(path, 'wb') as f:
            f.write(base64.b64decode(ev['data']))
        self.frames.append((ev['metadata']['timestamp'], path))
        try:
            self.cdp.send('Page.screencastFrameAck', {'sessionId': ev['sessionId']})
        except Exception:
            pass

    def stop(self):
        self.cdp.send('Page.stopScreencast')

    def encode(self, out_mp4, fps=30, tail=1.5):
        """Frames arrive only when something changes. Resample to a constant rate: every output
        frame is the latest captured frame at that instant, piped straight into ffmpeg."""
        self.frames.sort()
        t0 = self.frames[0][0]
        times = [t - t0 for t, _p in self.frames]
        total = times[-1] + tail
        ff = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', str(fps),
                               '-i', '-', '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p',
                               '-c:v', 'libx264', '-preset', 'slow', '-crf', '20', '-movflags', '+faststart', out_mp4],
                              stdin=subprocess.PIPE)
        k, cache = 0, {}
        for n in range(int(total * fps)):
            t = n / fps
            while k + 1 < len(times) and times[k + 1] <= t:
                k += 1
            path = self.frames[k][1]
            if path not in cache:
                cache.clear()
                with open(path, 'rb') as f:
                    cache[path] = f.read()
            ff.stdin.write(cache[path])
        ff.stdin.close()
        if ff.wait():
            raise RuntimeError('ffmpeg failed')


def gif(mp4, out, width=960, fps=12):
    pal = out + '.png'
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', mp4, '-vf',
                    f'fps={fps},scale={width}:-1:flags=lanczos,palettegen=stats_mode=diff', pal], check=True)
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', mp4, '-i', pal, '-lavfi',
                    f'fps={fps},scale={width}:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle',
                    out], check=True)
    os.remove(pal)


def run(chrome, keep_frames=False):
    from playwright.sync_api import sync_playwright
    port = free_port()
    app = start_server(port)
    app.load_samples()                         # the month so far, already read
    settle(app)
    app.reader.delay = (4.0, 4.2)              # the emailed ticket: slow enough to watch it being read
    base = f'http://localhost:{port}'
    os.makedirs(OUT, exist_ok=True)
    frames = tempfile.mkdtemp(prefix='asienta-frames-')
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome' if chrome else None, headless=True)
        ctx = browser.new_context(viewport={'width': 1440, 'height': 900}, device_scale_factor=2, locale='en-GB',
                                  bypass_csp=True)
        ctx.add_init_script("try{localStorage.setItem('asienta.lang','en')}catch(e){}")
        page = ctx.new_page()
        page.goto(base + '/#/review')
        page.wait_for_selector('table.list')
        page.evaluate(OVERLAY_JS)
        mouse = {'x': 900, 'y': 520}

        def wait(sec):
            page.wait_for_timeout(sec * 1000)          # keeps screencast frames flowing (time.sleep doesn't)

        def move(x, y, steps=18):
            page.mouse.move(x, y, steps=steps)
            mouse.update(x=x, y=y)

        def click(selector, pause=0.2):
            box = page.locator(selector).first.bounding_box()
            move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            wait(pause)
            page.mouse.down()
            page.mouse.up()

        def caption(key=None, hold=0.0):
            page.evaluate('t => window.__demo && window.__demo.caption(t)', CAPTIONS[key] if key else '')
            wait(hold)

        def overlay():
            page.evaluate(OVERLAY_JS)
            page.mouse.move(mouse['x'], mouse['y'])

        page.mouse.move(mouse['x'], mouse['y'])
        rec = Recorder(page, frames, 1920)
        # 1. an email arrives with a photographed ticket
        caption('arrive', 0.6)
        click('a.nav[href="#/mailbox"]')
        page.wait_for_selector('.mail')
        overlay()
        caption('arrive', 0.3)
        page.evaluate("fetch('/api/demo/email', {method: 'POST', headers: {'X-Asienta': '1'}}).then(() => go())")
        page.wait_for_selector('.email .brought')
        overlay()
        caption('email', 1.6)
        # 2. read by the AI, live
        click('.email a.brought')
        page.wait_for_selector('#live')
        overlay()
        caption('read')
        page.wait_for_selector('.live.ready', timeout=20000)
        wait(0.5)
        click('.go-on')
        page.wait_for_selector('#findings .finding.warning')
        overlay()
        # 3. checks and a one-click fix
        caption('check', 1.8)
        caption('fix', 0.2)
        click('#findings .finding .btn')
        page.wait_for_selector('#findings .finding.ok')
        wait(1.0)
        click('#btn-approve')
        wait(0.4)
        # 4. the split on a wholesaler's invoice
        med = app.db._one("SELECT id FROM invoices WHERE number = 'MED-26/0917'")['id']
        page.evaluate(f"location.hash = '#/invoice/{med}'")
        page.wait_for_selector('#findings')
        overlay()
        page.locator('.reason').first.scroll_into_view_if_needed()
        page.mouse.wheel(0, 380)
        wait(0.3)
        caption('split')
        move(1030, 505)
        wait(2.2)
        # approve every clean invoice behind the scenes (the video would be too long otherwise)
        page.evaluate("""async () => {
          const list = await (await fetch('/api/invoices?view=review')).json();
          for (const f of list) if (f.status === 'review' && !f.errors)
            await fetch(`/api/invoices/${f.id}/approve`, {method: 'POST', headers: {'X-Asienta': '1'}, body: '{}'});
        }""")
        # 5. export to any accounting program
        page.evaluate("location.hash = '#/approved'")
        page.wait_for_selector('.formats')
        overlay()
        caption('export')
        for fmt in ('a3', 'holded', 'xero', 'quickbooks', 'sage50'):
            click(f'.format[data-format="{fmt}"]', pause=0.1)
            page.wait_for_selector(f'.format.on[data-format="{fmt}"]')
            overlay()
            wait(0.35)
        click('.export .btn.primary')
        page.wait_for_selector('.batch-hero')
        overlay()
        caption('done')
        move(1330, 190)
        wait(1.5)
        caption('license', 2.2)
        rec.stop()
        browser.close()
    mp4 = os.path.join(OUT, 'demo.mp4')
    rec.encode(mp4)
    gif(mp4, os.path.join(OUT, 'demo.gif'))
    if not keep_frames:
        shutil.rmtree(frames, ignore_errors=True)
    print(f'{mp4}  ({len(rec.frames)} frames)')


def screenshots(chrome):
    """Clean screenshots of the main screens, light and dark."""
    from playwright.sync_api import sync_playwright
    port = free_port()
    app = start_server(port)
    app.load_samples()
    settle(app)
    base = f'http://localhost:{port}'
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome' if chrome else None, headless=True)
        for scheme in ('light', 'dark'):
            ctx = browser.new_context(viewport={'width': 1440, 'height': 900}, device_scale_factor=2,
                                      color_scheme=scheme)
            ctx.add_init_script("try{localStorage.setItem('asienta.lang','en')}catch(e){}")
            page = ctx.new_page()
            page.goto(base + '/#/review')
            page.wait_for_selector('table.list')
            time.sleep(0.8)
            page.screenshot(path=os.path.join(OUT, f'list-{scheme}.png'))
            first = app.db.listing('review')[0]['id']
            page.goto(base + f'/#/invoice/{first}')
            page.wait_for_selector('#findings')
            time.sleep(2.5)
            page.screenshot(path=os.path.join(OUT, f'invoice-{scheme}.png'))
            ctx.close()
        browser.close()
    print('screenshots in', OUT)


def social(chrome):
    """The 1280x640 image GitHub and social networks show when the repo is shared."""
    import base64

    from playwright.sync_api import sync_playwright
    shot = base64.b64encode(open(os.path.join(OUT, 'invoice-light.png'), 'rb').read()).decode()
    logo = open(os.path.join(ROOT, 'asienta', 'web', 'favicon.svg')).read()
    html = f"""<html><body style="margin:0;width:1280px;height:640px;overflow:hidden;font-family:Inter,system-ui,sans-serif;
      background:radial-gradient(900px 500px at 20% 30%,#312E81 0%,#0B0B12 75%);color:#fff;position:relative">
      <div style="position:absolute;left:72px;top:92px;width:560px">
        <div style="width:76px;height:76px">{logo}</div>
        <h1 style="font-size:78px;letter-spacing:-.045em;margin:26px 0 10px">Asienta</h1>
        <p style="font-size:30px;line-height:1.35;color:#C7C9F7;margin:0">Nobody started a business<br>
          <b style="color:#fff">to type invoices.</b></p>
        <p style="font-size:19px;line-height:1.6;color:#9FA2E8;margin:30px 0 0">Read by any AI model, cloud or local<br>
          Into Sage 50 · A3 · Holded · Xero · QuickBooks<br>
          Self-hosted · zero dependencies · MIT</p>
      </div>
      <img src="data:image/png;base64,{shot}" style="position:absolute;left:640px;top:70px;width:860px;border-radius:16px;
        box-shadow:0 30px 80px rgba(0,0,0,.6);border:1px solid rgba(255,255,255,.15)">
    </body></html>"""
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome' if chrome else None, headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 640}, device_scale_factor=1)
        page.set_content(html)
        page.wait_for_timeout(300)
        page.screenshot(path=os.path.join(OUT, 'social-preview.png'))
        browser.close()
    print('social preview in', OUT)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--chrome', action='store_true', help='use the installed Google Chrome')
    ap.add_argument('--screenshots', action='store_true')
    ap.add_argument('--social', action='store_true')
    ap.add_argument('--keep-frames', action='store_true')
    a = ap.parse_args()
    if a.screenshots:
        screenshots(a.chrome)
    elif a.social:
        social(a.chrome)
    else:
        run(a.chrome, a.keep_frames)
