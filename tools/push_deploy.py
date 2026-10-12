# -*- coding: utf-8 -*-
"""Синк папки deploy/ -> github.com/chmoshnik187/pogrebok.
Пушит только изменившиеся файлы (сравнение по sha). Удаления не делает.
Запуск: python3 tools/push_deploy.py [file ...]   (без аргументов — весь deploy/)"""
import base64, hashlib, json, os, subprocess, sys, urllib.request, urllib.error
ENV = dict(ln.split('=', 1) for ln in open('bot/.env', encoding='utf-8')
           if '=' in ln and not ln.strip().startswith('#') and not ln.startswith('#'))
TOK = ENV['POGREBOK_GH_TOKEN'].strip()
REPO = ENV.get('POGREBOK_GH_REPO', 'chmoshnik187/pogrebok').strip()
H = {'Authorization': f'Bearer {TOK}', 'Accept': 'application/vnd.github+json', 'User-Agent': 'pogrebok-sync'}

def call(m, p, body=None):
    req = urllib.request.Request(f'https://api.github.com/{p}', method=m, headers=H,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, (json.load(r) if 'json' in r.headers.get('Content-Type', '') else {})
    except urllib.error.HTTPError as e:
        return e.code, {}

def tree_files(root):
    out = []
    for dp, dn, fn in os.walk(root):
        for f in fn:
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, root).replace(os.sep, '/')
            out.append((rel, full))
    return sorted(out)

def main():
    only = [a for a in sys.argv[1:] if a != '--no-snap']
    if '--no-snap' not in sys.argv[1:]:
        # страховка: снимок состояния ПЕРЕД каждым пушем (tools/ver.py)
        try:
            subprocess.run([sys.executable, os.path.join('tools', 'ver.py'), 'snap',
                            'pre-push: ' + (', '.join(only) if only else 'весь deploy')],
                           check=False)
        except Exception as e:
            print('snap пропущен:', e)
    files = tree_files('deploy')
    pushed = skipped = 0
    for rel, full in files:
        if only and not any(rel == o or rel.endswith(o) for o in only):
            continue
        data = open(full, 'rb').read()
        b64 = base64.b64encode(data).decode()
        st, cur = call('GET', f'repos/{REPO}/contents/{rel}')
        if st == 200 and cur.get('sha'):
            if cur.get('sha') == hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest():
                skipped += 1
                continue
            body = {'message': f'update {rel}', 'content': b64, 'sha': cur['sha']}
        else:
            body = {'message': f'add {rel}', 'content': b64}
        st, _ = call('PUT', f'repos/{REPO}/contents/{rel}', body)
        print(('push ' if st in (200, 201) else f'FAIL{st} ') + rel)
        pushed += 1
    print(f'итог: запушено {pushed}, без изменений {skipped}')

if __name__ == '__main__':
    main()
