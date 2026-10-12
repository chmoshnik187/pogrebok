#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ver.py — ВЕРСИИ ПОГРЕБКА: снимки состояния + откаты.

Снимок = карта всех файлов (reports/ deploy/ bot/ tools/) с их sha1.
Содержимое хранится контент-адресно в reports/versions/objects/<sha1>.gz —
одинаковые файлы лежат в ОДНОМ экземпляре, поэтому снимки почти бесплатны
(новый снимок = только реально изменившиеся файлы).

Не версионируются (тяжёлое/секретное): uploads/, images/, homepack/,
bot/.env, reports/versions/ (сам склад), __pycache__.

Команды:
  python3 tools/ver.py snap "сообщение"          — снимок текущего состояния
  python3 tools/ver.py ls                        — список версий
  python3 tools/ver.py diff v1 v4                — что изменилось между версиями
  python3 tools/ver.py show v3                   — файлы версии
  python3 tools/ver.py get v3 reports/_shell3.html    — достать файл (в _peek/)
  python3 tools/ver.py get v3 reports/_shell3.html -  — ...или в stdout
  python3 tools/ver.py rewind v3                 — ПОЛНЫЙ откат (текущее состояние
                                                    сначала само сохранится в историю)
  python3 tools/ver.py rewind v3 bot/pogrebok_bot.py  — откатить только файл(ы)
  python3 tools/ver.py prune v5 v6               — выкинуть версии из истории (+GC)

Метки версий: v001, v002... (можно писать просто 1, 2, v1, v002).
"""
import gzip
import hashlib
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VDIR = os.path.join(ROOT, 'reports', 'versions')
ODIR = os.path.join(VDIR, 'objects')
MAN = os.path.join(VDIR, 'manifest.json')
MD = os.path.join(VDIR, 'VERSIONS.md')
PEEK = os.path.join(VDIR, '_peek')
TRASH = os.path.join(VDIR, '_trash')

INCLUDE = ['reports', 'deploy', 'bot', 'tools']
EXCL_PARTS = {'__pycache__', '.git', 'node_modules', '.mypy_cache', '.pytest_cache'}
EXCL_PREFIX = ('reports/versions/',)
EXCL_FILES = {'bot/.env'}
MAX_SIZE = 12 * 1024 * 1024


# ─────────────────────────── склад ───────────────────────────

def walk_files():
    """Все версионируемые файлы: [(rel, full), ...] отсортировано."""
    out = []
    for root in INCLUDE:
        base = os.path.join(ROOT, root)
        if not os.path.isdir(base):
            continue
        for dp, dn, fn in os.walk(base):
            rel_dir = os.path.relpath(dp, ROOT).replace(os.sep, '/')
            if rel_dir == '.':
                rel_dir = ''
            dn[:] = [d for d in dn if not excluded(rel_dir + '/' + d if rel_dir else d, True)]
            for f in fn:
                rel = (rel_dir + '/' + f) if rel_dir else f
                if excluded(rel, False):
                    continue
                full = os.path.join(dp, f)
                try:
                    sz = os.path.getsize(full)
                except OSError:
                    continue
                if sz > MAX_SIZE:
                    print(f'  (пропущен, >{MAX_SIZE // 1024 // 1024}MB: {rel})')
                    continue
                out.append((rel, full))
    return sorted(out)


def excluded(rel, is_dir):
    rel = rel.strip('/')
    if rel in EXCL_FILES:
        return True
    if any(rel == p.rstrip('/') or rel.startswith(p) for p in EXCL_PREFIX):
        return True
    return any(part in EXCL_PARTS for part in rel.split('/'))


def sha1(data):
    return hashlib.sha1(data).hexdigest()


def load_manifest():
    if not os.path.exists(MAN):
        return {'next': 1, 'versions': []}
    with open(MAN, encoding='utf-8') as f:
        return json.load(f)


def save_manifest(m):
    os.makedirs(VDIR, exist_ok=True)
    tmp = MAN + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(m, f, ensure_ascii=False)
    os.replace(tmp, MAN)


def store_object(data):
    h = sha1(data)
    p = os.path.join(ODIR, h + '.gz')
    if not os.path.exists(p):
        os.makedirs(ODIR, exist_ok=True)
        tmp = p + '.tmp'
        with gzip.open(tmp, 'wb', compresslevel=9) as f:
            f.write(data)
        os.replace(tmp, p)
    return h


def read_object(h):
    with gzip.open(os.path.join(ODIR, h + '.gz'), 'rb') as f:
        return f.read()


def find_version(m, label):
    s = str(label).strip().lower().lstrip('v')
    try:
        n = int(s)
    except ValueError:
        sys.exit(f'нет такой версии: {label}')
    for v in m['versions']:
        if v['n'] == n:
            return v
    sys.exit(f'нет такой версии: {label} (есть v001..v{m["next"] - 1:03d})')


def lab(v):
    return f"v{v['n']:03d}"


def stamp(ts=None):
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(ts or time.time()))


def delta(a, b):
    """(added, removed, changed) между двумя картами файлов."""
    af, bf = a or {}, b or {}
    added = sorted(set(bf) - set(af))
    removed = sorted(set(af) - set(bf))
    changed = sorted(k for k in set(af) & set(bf) if af[k]['sha'] != bf[k]['sha'])
    return added, removed, changed


def rewrite_md(m):
    lines = ['# ВЕРСИИ ПОГРЕБКА', '',
             'Снимки состояния (reports/ deploy/ bot/ tools/). Откат: '
             '`python3 tools/rewind` → `python3 tools/ver.py rewind vNNN`.', '',
             '| ver | дата | файлов | Δ от прошлой | сообщение |',
             '|---|---|---|---|---|']
    prev = None
    for v in m['versions']:
        a, r, c = delta(prev, v['files'])
        d = f'+{len(a)} −{len(r)} ~{len(c)}' if prev else '—'
        lines.append(f"| {lab(v)} | {stamp(v['ts'])} | {len(v['files'])} | {d} | {v['msg']} |")
        prev = v['files']
    with open(MD, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


# ─────────────────────────── команды ───────────────────────────

def cmd_snap(msg, force=False):
    files = {}
    for rel, full in walk_files():
        with open(full, 'rb') as f:
            data = f.read()
        files[rel] = {'sha': store_object(data), 'size': len(data)}
    m = load_manifest()
    if m['versions'] and m['versions'][-1]['files'] == files and not force:
        print(f'без изменений — снимок не создан (последний: {lab(m["versions"][-1])})')
        return None
    v = {'n': m['next'], 'ts': time.time(), 'msg': msg or 'снимок', 'files': files}
    m['versions'].append(v)
    m['next'] += 1
    save_manifest(m)
    rewrite_md(m)
    prev = m['versions'][-2]['files'] if len(m['versions']) > 1 else {}
    a, r, c = delta(prev, files)
    print(f'{lab(v)} · {stamp(v["ts"])} · файлов: {len(files)} · +{len(a)} −{len(r)} ~{len(c)} · {v["msg"]}')
    for x in a[:10]:
        print('   + ' + x)
    for x in r[:10]:
        print('   − ' + x)
    for x in c[:10]:
        print('   ~ ' + x)
    return lab(v)


def cmd_ls():
    m = load_manifest()
    if not m['versions']:
        print('версий пока нет — сделай: python3 tools/ver.py snap "сообщение"')
        return
    prev = None
    for v in m['versions']:
        a, r, c = delta(prev, v['files'])
        d = f'+{len(a)} −{len(r)} ~{len(c)}' if prev else f"{len(v['files'])} файлов"
        print(f"{lab(v)}  {stamp(v['ts'])}  [{d}]  {v['msg']}")
        prev = v['files']


def cmd_diff(la, lb):
    m = load_manifest()
    a, b = find_version(m, la), find_version(m, lb)
    added, removed, changed = delta(a['files'], b['files'])
    print(f'{lab(a)} → {lab(b)}')
    for x in added:
        print('  + ' + x)
    for x in removed:
        print('  − ' + x)
    for x in changed:
        print(f"  ~ {x}  ({a['files'][x]['size']} → {b['files'][x]['size']} б)")
    if not (added or removed or changed):
        print('  идентичны')


def cmd_show(label):
    m = load_manifest()
    v = find_version(m, label)
    print(f"{lab(v)} · {stamp(v['ts'])} · {v['msg']}")
    for rel in sorted(v['files']):
        print(f"  {v['files'][rel]['size']:>9}  {rel}")


def cmd_get(label, path, out):
    m = load_manifest()
    v = find_version(m, label)
    if path not in v['files']:
        sys.exit(f'в {lab(v)} нет файла {path}')
    data = read_object(v['files'][path]['sha'])
    if out == '-':
        sys.stdout.buffer.write(data)
        return
    if not out:
        os.makedirs(PEEK, exist_ok=True)
        out = os.path.join(PEEK, f"{lab(v)}__{path.replace('/', '__')}")
    with open(out, 'wb') as f:
        f.write(data)
    print(f'{lab(v)}:{path} → {os.path.relpath(out, ROOT)} ({len(data)} б)')


def _write(rel, data):
    full = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'wb') as f:
        f.write(data)


def cmd_rewind(label, paths):
    m = load_manifest()
    v = find_version(m, label)
    want = v['files']
    if paths:
        for p in paths:
            if p not in want:
                sys.exit(f'в {lab(v)} нет файла {p}')
        for p in paths:
            _write(p, read_object(want[p]['sha']))
            print(f'откачено: {p} ← {lab(v)}')
        return
    # полный откат: сначала страхуем текущее состояние
    cur_label = cmd_snap(f'auto: страховка перед откатом к {lab(v)}')
    n_write = n_trash = 0
    for rel, meta in sorted(want.items()):
        full = os.path.join(ROOT, rel)
        if os.path.exists(full):
            with open(full, 'rb') as f:
                if sha1(f.read()) == meta['sha']:
                    continue
        _write(rel, read_object(meta['sha']))
        n_write += 1
    # файлы, которых нет в целевой версии — не удаляем, а прячем в _trash
    on_disk = {rel for rel, _ in walk_files()}
    extra = sorted(on_disk - set(want))
    if extra:
        tdir = os.path.join(TRASH, time.strftime('%Y%m%d-%H%M%S'))
        for rel in extra:
            src = os.path.join(ROOT, rel)
            dst = os.path.join(tdir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            n_trash += 1
        print(f'лишние файлы ({n_trash}) спрятаны в {os.path.relpath(tdir, ROOT)}')
    print(f'откат к {lab(v)} («{v["msg"]}»): перезаписано {n_write}, убрано {n_trash}'
          + (f', страховка = {cur_label}' if cur_label else ''))


def cmd_prune(labels):
    m = load_manifest()
    victims = {find_version(m, x)['n'] for x in labels}
    if len(victims) == len(m['versions']):
        sys.exit('нельзя снести ВСЕ версии')
    m['versions'] = [v for v in m['versions'] if v['n'] not in victims]
    save_manifest(m)
    rewrite_md(m)
    # GC объектов
    keep = {meta['sha'] for v in m['versions'] for meta in v['files'].values()}
    freed = 0
    if os.path.isdir(ODIR):
        for f in os.listdir(ODIR):
            if f.endswith('.gz') and f[:-3] not in keep:
                freed += os.path.getsize(os.path.join(ODIR, f))
                os.remove(os.path.join(ODIR, f))
    print(f'снесено версий: {len(victims)}, освобождено: {freed // 1024} KB')


# ─────────────────────────── main ───────────────────────────

def main():
    args = sys.argv[1:]
    cmd = args[0] if args else 'ls'
    rest = args[1:]
    if cmd == 'snap':
        msg = 'снимок'
        force = '--force' in rest
        rest = [a for a in rest if a != '--force']
        if rest:
            msg = ' '.join(rest)
        cmd_snap(msg, force)
    elif cmd == 'ls':
        cmd_ls()
    elif cmd == 'diff':
        if len(rest) < 2:
            sys.exit('нужно: ver.py diff vA vB')
        cmd_diff(rest[0], rest[1])
    elif cmd == 'show':
        cmd_show(rest[0])
    elif cmd == 'get':
        if len(rest) < 2:
            sys.exit('нужно: ver.py get vN путь/к/файлу [out|-]')
        cmd_get(rest[0], rest[1], rest[2] if len(rest) > 2 else None)
    elif cmd == 'rewind':
        if not rest:
            sys.exit('нужно: ver.py rewind vN [файл ...]')
        cmd_rewind(rest[0], rest[1:])
    elif cmd == 'prune':
        if not rest:
            sys.exit('нужно: ver.py prune vN [vN ...]')
        cmd_prune(rest)
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
