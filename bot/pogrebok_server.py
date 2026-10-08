# -*- coding: utf-8 -*-
"""
ПОГРЕБОК-СЕРВЕР: сайт как единственная точка входа, телеграм — фоновым слоем.

Один процесс поднимает:
  1) бота (long-polling в отдельном потоке) — принимает txt/mp3 с телефона;
  2) HTTP API с CORS — сайт общается с ним напрямую, токен браузера не касается;
  3) (опционально) статику сайта, если задан POGREBOK_WWW — тогда это вообще
     один адрес: и сайт, и API, и бот-бэкенд.

ЭНДПОИНТЫ:
  GET  /api/ping                 -> {ok, bot}
  GET  /api/profile?id=<chat>    -> профиль {files,urls,locker,bot}
  POST /api/profile?id=<chat>    -> заменить профиль целиком (тело = json)
  POST /api/add?id=<chat>        -> {pl,a,t,url} добавить трек в плейлист pl
  GET  /                         -> index.html из POGREBOK_WWW (если задан)

ЗАПУСК:
  export POGREBOK_BOT_TOKEN=...      (или bot/.env)
  export POGREBOK_PORT=8777          (по умолчанию 8777)
  export POGREBOK_WWW=/path/to/site  (опционально)
  python pogrebok_server.py

САЙТ ПОДКЛЮЧАЕТСЯ так:  https://host/?bot=https://host&id=<chat_id>
"""
import os, json, time, threading, pathlib, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pogrebok_bot as B

PORT = int(os.environ.get('POGREBOK_PORT', '8777'))
WWW = os.environ.get('POGREBOK_WWW', '')

class H(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self._cors()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    def _cat_search(self, q):
        c = cat_load(); q = q.lower().strip(); out = []
        for k, e in c['tracks'].items():
            if q in e['t'].lower() or q in e['a'].lower():
                out.append({'key': k, **{x: e[x] for x in ('t','a','album','art','n') if x in e}, 'comments': len(e.get('comments', []))})
        for k, e in c['artists'].items():
            if q in k:
                out.append({'artist': e['name'], 'n': e['n'], 'top': sorted(e['top'].items(), key=lambda x: -x[1])[:5]})
        return out[:14]

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == '/api/ping':
            return self._json({'ok': True, 'bot': B.BOT_USERNAME})
        if u.path == '/api/search':
            return self._json({'ok': True, 'res': self._cat_search((q.get('q') or [''])[0])})
        if u.path == '/api/track':
            c = cat_load(); e = c['tracks'].get((q.get('key') or [''])[0])
            return self._json(e or {'error': 'not in catalog'}, 200 if e else 404)
        if u.path == '/api/profile':
            cid = (q.get('id') or [''])[0]
            if not cid.isdigit():
                return self._json({'error': 'id must be numeric'}, 400)
            return self._json(B.load(cid))
        if u.path in ('/', '/index.html') and WWW:
            p = pathlib.Path(WWW) / ('index.html' if u.path == '/' else u.path.lstrip('/'))
            if p.exists() and p.suffix in ('.html', '.js', '.css', '.png', '.jpg', '.svg'):
                body = p.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8' if p.suffix == '.html' else 'application/octet-stream')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
        return self._json({'error': 'not found'}, 404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        cid = (q.get('id') or [''])[0]
        if u.path != '/api/comment' and not cid.isdigit():
            return self._json({'error': 'id must be numeric'}, 400)
        n = int(self.headers.get('Content-Length', 0))
        try:
            body = json.loads(self.rfile.read(n).decode('utf-8')) if n else {}
        except Exception:
            return self._json({'error': 'bad json'}, 400)
        if u.path == '/api/profile':
            if not (body.get('files')):
                return self._json({'error': 'files required'}, 400)
            B.save(cid, body)
            return self._json({'ok': True})
        if u.path == '/api/comment':
            key = (q.get('key') or [''])[0]; c = cat_load(); e = c['tracks'].get(key)
            if not e: return self._json({'error': 'not in catalog'}, 404)
            e.setdefault('comments', []).append({'id': (body.get('id') or '?'), 'name': (body.get('name') or 'аноним из погреба')[:40], 'text': (body.get('text') or '')[:500], 'ts': int(time.time())})
            e['comments'] = e['comments'][-50:]
            cat_save(c); return self._json({'ok': True, 'n': len(e['comments'])})
        if u.path == '/api/add':
            a, t = (body.get('a') or '').strip(), (body.get('t') or '').strip()
            if not a or not t:
                return self._json({'error': 'a and t required'}, 400)
            prof = B.load(cid)
            if not prof['files']:
                return self._json({'error': 'profile empty: send a txt to the bot first'}, 400)
            i = int(body.get('pl') or 0) % len(prof['files'])
            prof['files'][i]['tracks'].insert(0, [a, t])
            if body.get('url'):
                prof['urls'][a.lower() + '||' + t.lower()] = body['url']
            B.save(cid, prof)
            return self._json({'ok': True, 'n': len(prof['files'][i]['tracks'])})
        return self._json({'error': 'not found'}, 404)

    def log_message(self, *a):
        pass


# ================= ОБЩАЯ БАЗА (каталог сообщества) =================
CAT_PATH = B.DATA / '_catalog.json'
def cat_load():
    if CAT_PATH.exists():
        try: return json.loads(CAT_PATH.read_text(encoding='utf-8'))
        except Exception: pass
    return {'tracks': {}, 'artists': {}, 'albums': {}}
def cat_save(c):
    CAT_PATH.write_text(json.dumps(c, ensure_ascii=False), encoding='utf-8')
def normkey(a, t): return a.strip().lower() + '||' + t.strip().lower()
GENIUS = os.environ.get('POGREBOK_GENIUS_TOKEN', '')
def genius_enrich(e):
    if not GENIUS or e.get('_g'): return
    e['_g'] = 1
    try:
        req = urllib.request.Request('https://api.genius.com/search?q=' + urllib.parse.quote(e['a'] + ' ' + e['t']),
                                     headers={'Authorization': 'Bearer ' + GENIUS})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
        r = (d.get('response') or {}).get('hits') or []
        if not r: return
        res = r[0].get('result') or {}
        if not e.get('art') and res.get('song_art_image_url'): e['art'] = res['song_art_image_url']
        if not e.get('album') and res.get('album'): e['album'] = res['album'].get('name')
        if not e.get('artist_img'): e['artist_img'] = ((res.get('primary_artist') or {}).get('image_url'))
    except Exception:
        pass
def merge_catalog(prof, cid):
    c = cat_load(); ch = False
    arts = prof.get('art') or {}; urls = prof.get('urls') or {}; albums = prof.get('albums') or {}
    for f in prof.get('files', []):
        for a, t in f['tracks']:
            k = normkey(a, t)
            e = c['tracks'].setdefault(k, {'t': t.strip(), 'a': a.strip(), 'by': [], 'n': 0})
            if cid not in e['by']: e['by'].append(cid); ch = True
            e['n'] = len(e['by'])
            if k in arts and not e.get('art'): e['art'] = arts[k]; ch = True
            if k in urls and not e.get('url'): e['url'] = urls[k]; ch = True
            if k in albums and not e.get('album'): e['album'] = albums[k]; ch = True
            if (not e.get('art') or not e.get('album')): genius_enrich(e); ch = True
            an = a.strip().lower()
            ae = c['artists'].setdefault(an, {'name': a.strip(), 'n': 0, 'top': {}})
            ae['n'] += 1; ae['top'][t.strip()] = ae['top'].get(t.strip(), 0) + 1; ch = True
            al = (albums.get(k) or '').strip()
            if al:
                ab = c['albums'].setdefault(al.lower(), {'name': al, 'tracks': []})
                if k not in ab['tracks']: ab['tracks'].append(k); ch = True
    if ch: cat_save(c)
_orig_save = B.save
def save_wrap(cid, prof):
    _orig_save(cid, prof)
    try: merge_catalog(prof, cid)
    except Exception as e: print('cat merge err', e)
B.save = save_wrap


def main():
    if not B.TOKEN:
        raise SystemExit('Задай POGREBOK_BOT_TOKEN (или bot/.env)')
    threading.Thread(target=B.main, daemon=True).start()
    print(f'погребок-сервер на :{PORT}' + (f' · сайт из {WWW}' if WWW else ''))
    ThreadingHTTPServer(('0.0.0.0', PORT), H).serve_forever()

if __name__ == '__main__':
    main()

def main():
    if not B.TOKEN:
        raise SystemExit('Задай POGREBOK_BOT_TOKEN (или bot/.env)')
    threading.Thread(target=B.main, daemon=True).start()
    print(f'погребок-сервер на :{PORT}' + (f' · сайт из {WWW}' if WWW else ''))
    ThreadingHTTPServer(('0.0.0.0', PORT), H).serve_forever()

if __name__ == '__main__':
    main()

