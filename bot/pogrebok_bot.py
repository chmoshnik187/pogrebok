# -*- coding: utf-8 -*-
"""
ПОГРЕБОК-БОТ: аккаунты без аккаунтов.
Ноль зависимостей кроме requests. Хранит профили в data/ и (опционально) пушит их
в GitHub-репозиторий, откуда сайт (GitHub Pages) читает их по прямой ссылке.

ЗАПУСК:
  pip install requests
  export POGREBOK_BOT_TOKEN="123:abc"          # токен от @BotFather
  export POGREBOK_GH_TOKEN="ghp_..."           # PAT с правом repo (опционально)
  export POGREBOK_GH_REPO="user/repo"          # репозиторий с сайтом (опционально)
  export POGREBOK_SITE="https://user.github.io/repo"   # адрес сайта (опционально)
  python pogrebok_bot.py

КОМАНДЫ:
  /start          hello
  /my             твоя персональная ссылка на сайт
  /add Артист - Трек [ссылка]   добавить трек в первый плейлист профиля
  /del N          удалить N-й трек первого плейлиста
  /stats          короткая сводка профиля
  просто файлом   прислать .txt экспорта -> создаст/перезапишет профиль
"""
import os, re, json, time, pathlib, base64, hashlib, urllib.parse, urllib.request

class _R:
    def __init__(self, data, status=200): self._d = data; self.status_code = status
    def json(self): return self._d
    @property
    def text(self): return self._t if hasattr(self,'_t') else json.dumps(self._d)

def _get(url, params=None, timeout=30, raw=False):
    if params: url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=timeout) as r:
        data = r.read()
    if raw:
        o = _R(None); o._t = data.decode('utf-8', 'replace'); return o
    return _R(json.loads(data.decode('utf-8')))

def _post(url, payload, timeout=30):
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return _R(json.loads(r.read().decode('utf-8')))

def _put_gh(url, payload, token, timeout=30):
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), method='PUT',
                                 headers={'Content-Type': 'application/json', 'Authorization': f'token {token}',
                                          'Accept': 'application/vnd.github+json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return _R(json.loads(r.read().decode('utf-8')))
    except Exception:
        return _R({}, 500)

class requests:
    @staticmethod
    def get(u, params=None, timeout=30): return _get(u, params, timeout)
    @staticmethod
    def post(u, json=None, timeout=30): return _post(u, json, timeout)
    @staticmethod
    def put(u, headers=None, json=None, timeout=30): return _put_gh(u, json, (headers or {}).get('Authorization','token ').split()[-1], timeout)

def _envfile():
    p = pathlib.Path(__file__).parent / '.env'
    out = {}
    if p.exists():
        for ln in p.read_text(encoding='utf-8').split('\n'):
            ln = ln.strip()
            if ln and not ln.startswith('#') and '=' in ln:
                k, v = ln.split('=', 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out
_EF = _envfile()
def _env(k, d=''):
    return os.environ.get(k) or _EF.get(k) or d
TOKEN = _env('POGREBOK_BOT_TOKEN')
GH_TOKEN = _env('POGREBOK_GH_TOKEN')
GH_REPO = _env('POGREBOK_GH_REPO')
SITE = _env('POGREBOK_SITE')
DATA = pathlib.Path(os.environ.get('POGREBOK_DATA', 'data'))
DATA.mkdir(exist_ok=True)

API = f'https://api.telegram.org/bot{TOKEN}'
BOT_USERNAME = os.environ.get('POGREBOK_BOT_USER', 'pogrebok_room_bot')

def parse_txt(text):
    out = []
    for ln in text.split('\n'):
        m = re.match(r'^\s*\d+\.\s*(.+)$', ln)
        if not m:
            continue
        rest = m.group(1).strip()
        if ' - ' in rest:
            a, t = rest.split(' - ', 1)
        else:
            a, t = rest, ''
        if a.strip() or t.strip():
            out.append([a.strip(), t.strip()])
    return out

def load(chat_id):
    p = DATA / f'{chat_id}.json'
    if p.exists():
        return json.loads(p.read_text(encoding='utf-8'))
    return {'files': [], 'urls': {}}

def save(chat_id, prof):
    (DATA / f'{chat_id}.json').write_text(json.dumps(prof, ensure_ascii=False), encoding='utf-8')
    push_gh(chat_id, prof)

def push_gh(chat_id, prof):
    if not (GH_TOKEN and GH_REPO):
        return
    path = f'data/{chat_id}.json'
    body = json.dumps(prof, ensure_ascii=False)
    r = requests.get(f'https://api.github.com/repos/{GH_REPO}/contents/{path}', timeout=20)
    sha = r.json().get('sha') if r.status_code == 200 else None
    payload = {'message': f'pogrebok: update {chat_id}', 'content': base64.b64encode(body.encode()).decode()}
    if sha:
        payload['sha'] = sha
    requests.put(f'https://api.github.com/repos/{GH_REPO}/contents/{path}', json=payload, timeout=30)

def public_url(chat_id):
    if GH_REPO:
        return f'https://raw.githubusercontent.com/{GH_REPO}/main/data/{chat_id}.json'
    return None

def site_link(chat_id):
    u = public_url(chat_id)
    if SITE and u:
        return f'{SITE}/?u={urllib.parse.quote(u, safe="")}'
    return u

def send(chat_id, text, parse='HTML'):
    requests.post(API + '/sendMessage', json={'chat_id': chat_id, 'text': text, 'parse_mode': parse,
                                              'disable_web_page_preview': True}, timeout=20)

def quick_stats(prof):
    n = sum(len(f['tracks']) for f in prof['files'])
    arts = set()
    for f in prof['files']:
        for a, t in f['tracks']:
            for p in re.split(r',|&', a):
                if p.strip():
                    arts.add(p.strip().lower())
    return n, len(arts)

def locker_slug(a,t):
    return hashlib.md5((a.lower()+'||'+t.lower()).encode()).hexdigest()[:12]

def norm_ru(s):
    return re.sub(r'[^a-zа-я0-9 ]', '', (s or '').lower()).strip()

def send_audio(chat, fid):
    req = urllib.request.Request(API+'/sendAudio', data=json.dumps({'chat_id':chat,'audio':fid}).encode(),
                                 headers={'Content-Type':'application/json'})
    try:
        urllib.request.urlopen(req, timeout=60); return True
    except Exception:
        return False

def handle(msg):
    chat = msg['chat']['id']
    if msg.get('document'):
        d = msg['document']
        if (d.get('file_name') or '').lower().endswith('.txt') or d.get('mime_type') == 'text/plain':
            fr = requests.get(API + '/getFile', params={'file_id': d['file_id']}, timeout=20).json()
            url = f"https://api.telegram.org/file/bot{TOKEN}/{fr['result']['file_path']}"
            text = requests.get(url, timeout=30).text
            tracks = parse_txt(text)
            if not tracks:
                send(chat, 'Не смог разобрать файл: нужен формат «1. Артист - Трек» построчно.')
                return
            prof = load(chat)
            name = re.sub(r'\.txt$', '', d['file_name'], flags=re.I)
            prof['files'] = [f for f in prof['files'] if f['name'] != name]
            prof['files'].append({'name': name, 'tracks': tracks})
            save(chat, prof)
            n, na = quick_stats(prof)
            link = site_link(chat)
            send(chat, f'Принял: <b>{name}</b> · {len(tracks)} треков.\nВсего в профиле: {n} треков, {na} имён.\n'
                       + (f'Твоя комната: {link}' if link else 'Профиль сохранён локально у бота.'))
        else:
            send(chat, 'Жду .txt файл экспорта (ymusicexport.ru или экспорт Яндекс Музыки).')
        return
    aud = msg.get('audio') or (msg.get('document') if (msg.get('document') or {}).get('mime_type','').startswith('audio') else None)
    if aud and not (msg.get('text') or '').strip():
        a = aud.get('performer') or 'неизвестный артист'
        t = aud.get('title') or (aud.get('file_name') or 'без названия').rsplit('.',1)[0]
        prof = load(chat)
        prof['locker'] = prof.get('locker', {})
        sl = locker_slug(a, t)
        prof['locker'][sl] = {'fid': aud['file_id'], 'a': a, 't': t}
        prof['bot'] = BOT_USERNAME
        save(chat, prof)
        send(chat, f' Положил в локер: <b>{a} — {t}</b>.\nСлушай в телеграме: /play {sl}\nИли на сайте кнопка «слушать в телеграме».')
        return
    text = (msg.get('text') or '').strip()
    if text.startswith('/start'):
        payload = text[6:].strip()
        if payload.startswith('play_'):
            sl = payload[5:]
            prof = load(chat)
            e = (prof.get('locker') or {}).get(sl)
            if e and send_audio(chat, e['fid']):
                send(chat, f'🎧 {e["a"]} — {e["t"]} · твой локер, стрим из твоего же облака')
            else:
                send(chat, 'Не нашёл такой трек в твоём локере. Пришли mp3 файлом — положу.')
            return
        send(chat, 'Я — погребок. Кидай .txt экспорта плейлистов — соберу комнату.\n'
                   'Кидай mp3 файлом — положу в локер и буду стримить тебе в телеграме.\n'
                   'Команды: /my /stats /add /del /locker /play SLUG')
    elif text.startswith('/my'):
        link = site_link(chat)
        send(chat, link or 'Профиль есть, но публичной ссылки нет: задай POGREBOK_GH_REPO и POGREBOK_SITE.')
    elif text.startswith('/play'):
        sl = text[5:].strip()
        prof = load(chat)
        e = (prof.get('locker') or {}).get(sl)
        if e and send_audio(chat, e['fid']):
            send(chat, f'🎧 {e["a"]} — {e["t"]}')
        else:
            send(chat, 'Нет такого slug в локере. Список: /locker')
    elif text.startswith('/locker'):
        prof = load(chat)
        lk = prof.get('locker') or {}
        if not lk:
            send(chat, 'Локер пуст. Пришли mp3/аудио файлом — положу.')
        else:
            send(chat, 'Твой локер:\n' + '\n'.join(f'· /play {sl} — {e["a"]} — {e["t"]}' for sl, e in list(lk.items())[:30]))
    elif text.startswith('/stats'):
        prof = load(chat)
        if not prof['files']:
            send(chat, 'Профиль пуст. Пришли .txt файл.')
            return
        n, na = quick_stats(prof)
        send(chat, f'Плейлистов: {len(prof["files"])} · треков: {n} · имён: {na}\n'
                   + '\n'.join(f'· {f["name"]}: {len(f["tracks"])}' for f in prof['files']))
    elif text.startswith('/find'):
        body = text[5:].strip()
        m = re.match(r'^(.+?)\s+-\s+(.+)$', body)
        if not m:
            send(chat, 'Формат: /find Артист - Название трека')
            return
        a, t = m.group(1).strip(), m.group(2).strip()
        q = urllib.parse.quote(a + ' ' + t)
        lines = []
        try:
            d = _get('https://itunes.apple.com/search', {'term': a + ' ' + t, 'limit': 5, 'entity': 'song'}).json()
            hit = any(norm_ru(r.get('trackName', '')) == norm_ru(t) or norm_ru(t)[:14] in norm_ru(r.get('trackName', '')) for r in d.get('results', []))
            lines.append(('✅ Apple Music / iTunes' if hit else '⛔ Apple Music / iTunes') + (' · есть 30-сек превью' if hit else ''))
        except Exception:
            lines.append('⛔ Apple Music / iTunes (не ответил)')
        try:
            d = _get('https://api.deezer.com/search', {'q': a + ' ' + t, 'limit': 5}).json()
            lines.append(('✅ Deezer' if d.get('total') else '⛔ Deezer') + (f' · найдено {d.get("total")}' if d.get('total') else ''))
        except Exception:
            lines.append('⛔ Deezer (не ответил)')
        lines.append('🔎 <a href="https://music.yandex.ru/search?text=' + q + '">Яндекс · поиск</a>')
        lines.append('🔎 <a href="https://open.spotify.com/search/' + q + '">Spotify · поиск</a>')
        lines.append('🔎 <a href="https://www.youtube.com/results?search_query=' + q + '">YouTube · поиск</a>')
        lines.append('🔎 <a href="https://soundcloud.com/search?q=' + q + '">SoundCloud · поиск</a>')
        lines.append('🔎 <a href="https://bandcamp.com/search?q=' + q + '">Bandcamp · поиск</a>')
        send(chat, f'<b>{a} — {t}</b>\n' + '\n'.join(lines))
        return
    elif text.startswith('/add'):
        force = text.startswith('/add!')
        body = text[5 if force else 4:].strip()
        m = re.match(r'^(.+?)\s+-\s+(.+?)(?:\s+(https?://\S+))?$', body)
        if not m:
            send(chat, 'Формат: /add Артист - Название трека [ссылка]  (или /add! чтобы добавить дубль)')
            return
        a = re.sub(r'\s+', ' ', m.group(1).strip())
        t = re.sub(r'\s+', ' ', m.group(2).strip())
        u = m.group(3)
        prof = load(chat)
        if not prof['files']:
            send(chat, 'Сначала пришли .txt файл — создам профиль.')
            return
        key = a.lower() + '||' + t.lower()
        if not force and any((x[0].lower() + '||' + x[1].lower()) == key for f in prof['files'] for x in f['tracks']):
            send(chat, f'Такой уже есть в профиле: <b>{a} — {t}</b>.\nЕсли точно нужен дубль — /add! {a} - {t}')
            return
        prof['files'][0]['tracks'].insert(0, [a, t])
        if u:
            prof['urls'][a.lower() + '||' + t.lower()] = u
        art = None
        try:
            d = _get('https://itunes.apple.com/search', {'term': a + ' ' + t, 'limit': 5, 'entity': 'song'}).json()
            for r in d.get('results', []):
                if norm_ru(r.get('trackName', '')) and (norm_ru(t)[:14] in norm_ru(r.get('trackName', '')) or norm_ru(r.get('trackName', ''))[:14] in norm_ru(t)):
                    art = (r.get('artworkUrl100') or '').replace('100x100bb', '600x600bb') or None
                    break
        except Exception:
            art = None
        if art:
            prof.setdefault('art', {})[a.lower() + '||' + t.lower()] = art
        save(chat, prof)
        send(chat, f'Добавил: {a} — {t}' + (' · полный трек по ссылке' if u else '') + (' · 🖼 обложка подтянулась из iTunes' if art else ' · 🖼 обложки в каталоге нет, сайт нарисует свою'))
    elif text.startswith('/del'):
        try:
            i = int(text[4:].strip()) - 1
        except ValueError:
            send(chat, 'Формат: /del N (номер трека в первом плейлисте)')
            return
        prof = load(chat)
        if prof['files'] and 0 <= i < len(prof['files'][0]['tracks']):
            a, t = prof['files'][0]['tracks'].pop(i)
            save(chat, prof)
            send(chat, f'Удалил: {a} — {t}')
        else:
            send(chat, 'Нет такого номера.')
    else:
        send(chat, 'Не понял. Команды: /my /stats /add /del или просто пришли .txt файл.')

def main():
    if not TOKEN:
        raise SystemExit('Задай POGREBOK_BOT_TOKEN (токен от @BotFather)')
    off = 0
    print('погребок-бот поднялся')
    while True:
        try:
            r = requests.get(API + '/getUpdates', params={'offset': off, 'timeout': 30}, timeout=40).json()
            for u in r.get('result', []):
                off = u['update_id'] + 1
                if 'message' in u:
                    handle(u['message'])
        except Exception as e:
            print('err', e)
            time.sleep(3)

if __name__ == '__main__':
    main()
