/* ПОГРЕБОК-ВОРКЕР: бот на вебхуках + облачное API, бесплатно на Cloudflare Workers.
   Привязки (Bindings): KV-неймспейс с именем POGREB.
   Переменные окружения: TG_TOKEN (секрет), BOT_USER (имя бота, по умолчанию pogrebok_room_bot),
   SITE (адрес Pages, для /my), GENIUS (опционально).
   Вебхук телеграма ставится на https://<worker>/tg
*/
const ENC = { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type' };
const j = (o, c = 200) => new Response(JSON.stringify(o), { status: c, headers: ENC });
const norm = s => (s || '').toLowerCase().replace(/[^a-zа-я0-9 ]/g, ' ').trim();
const keyOf = (a, t) => a.toLowerCase() + '||' + t.toLowerCase();

function parseTxt(text) {
  const out = [];
  for (const ln of text.split('\n')) {
    const m = ln.trim().match(/^\d+\.\s*(.+)$/); if (!m) continue;
    const rest = m[1]; const i = rest.indexOf(' - ');
    const a = i > 0 ? rest.slice(0, i).trim() : rest.trim();
    const t = i > 0 ? rest.slice(i + 3).trim() : '';
    if (a || t) out.push([a, t]);
  }
  return out;
}
const api = (T, m, body) => fetch(`https://api.telegram.org/bot${T}/${m}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const send = (T, chat, text) => api(T, 'sendMessage', { chat_id: chat, text, parse_mode: 'HTML', disable_web_page_preview: true });

async function getProf(env, id) { return (await env.POGREB.get('prof:' + id, 'json')) || { files: [], urls: {}, art: {}, albums: {}, locker: {} }; }
async function putProf(env, id, p) { await env.POGREB.put('prof:' + id, JSON.stringify(p)); await mergeCat(env, p, id); }
async function getCat(env) { return (await env.POGREB.get('catalog', 'json')) || { tracks: {}, artists: {}, albums: {} }; }
async function mergeCat(env, prof, cid) {
  const c = await getCat(env); let ch = false;
  for (const f of prof.files || []) for (const [a, t] of f.tracks) {
    const k = keyOf(a, t); const e = c.tracks[k] || (c.tracks[k] = { t: t.trim(), a: a.trim(), by: [], n: 0 });
    if (!e.by.includes(cid)) { e.by.push(cid); e.n = e.by.length; ch = true; }
    const art = (prof.art || {})[k], url = (prof.urls || {})[k], al = (prof.albums || {})[k];
    if (art && !e.art) { e.art = art; ch = true; } if (url && !e.url) { e.url = url; ch = true; } if (al && !e.album) { e.album = al; ch = true; }
    const an = a.trim().toLowerCase(); const ae = c.artists[an] || (c.artists[an] = { name: a.trim(), n: 0, top: {} });
    ae.n++; ae.top[t.trim()] = (ae.top[t.trim()] || 0) + 1; ch = true;
    if (al) { const ab = c.albums[al.toLowerCase()] || (c.albums[al.toLowerCase()] = { name: al, tracks: [] }); if (!ab.tracks.includes(k)) ab.tracks.push(k); ch = true; }
  }
  if (ch) await env.POGREB.put('catalog', JSON.stringify(c));
}
async function genius(env, e) {
  if (!env.GENIUS || e._g) return;
  e._g = 1;
  try {
    const d = await (await fetch('https://api.genius.com/search?q=' + encodeURIComponent(e.a + ' ' + e.t), { headers: { Authorization: 'Bearer ' + env.GENIUS } })).json();
    const r = ((d.response || {}).hits || [])[0]; if (!r) return;
    const res = r.result || {};
    if (!e.art && res.song_art_image_url) e.art = res.song_art_image_url;
    if (!e.album && res.album) e.album = res.album.name;
  } catch (e2) {}
}
async function itunes(q) {
  try { return await (await fetch('https://itunes.apple.com/search?term=' + encodeURIComponent(q) + '&limit=5&entity=song')).json(); } catch (e) { return { results: [] }; }
}
async function deezer(q) {
  try { return await (await fetch('https://api.deezer.com/search?q=' + encodeURIComponent(q) + '&limit=5')).json(); } catch (e) { return { total: 0 }; }
}

async function handleUpdate(env, T, u) {
  const msg = u.message; if (!msg) return;
  const chat = msg.chat.id;
  const prof = await getProf(env, chat);
  const BOT = env.BOT_USER || 'pogrebok_room_bot';
  if (msg.document && !msg.text) {
    const d = msg.document;
    if (!/\.txt$/i.test(d.file_name || '') && !(d.mime_type || '').startsWith('text')) return send(T, chat, 'Жду .txt файл экспорта.');
    const gf = await (await api(T, 'getFile', { file_id: d.file_id })).json();
    const text = await (await fetch(`https://api.telegram.org/file/bot${T}/${gf.result.file_path}`)).text();
    const tracks = parseTxt(text); if (!tracks.length) return send(T, chat, 'Не разобрал файл: нужен формат «1. Артист - Трек».');
    const name = (d.file_name || 'плейлист').replace(/\.txt$/i, '');
    prof.files = prof.files.filter(f => f.name !== name); prof.files.push({ name, tracks });
    await putProf(env, chat, prof);
    const n = prof.files.reduce((s, f) => s + f.tracks.length, 0);
    const link = env.SITE ? `${env.SITE}/?bot=${encodeURIComponent('https://' + BOT + '.workers.dev')}&id=${chat}` : '';
    return send(T, chat, `Принял: <b>${name}</b> · ${tracks.length} треков.\nВ профиле: ${n} треков.\n${link ? 'Твоя комната: ' + link : ''}`);
  }
  if (msg.audio && !msg.text) {
    const a = msg.audio.performer || 'неизвестный артист', t = msg.audio.title || (msg.audio.file_name || 'без названия').split('.')[0];
    prof.locker = prof.locker || {}; const sl = (await digest(keyOf(a, t))).slice(0, 12);
    prof.locker[sl] = { fid: msg.audio.file_id, a, t }; prof.bot = BOT;
    await putProf(env, chat, prof);
    return send(T, chat, `Положил в локер: <b>${a} — ${t}</b>\nСлушай: /play ${sl}`);
  }
  const text = (msg.text || '').trim();
  if (text.startsWith('/start')) {
    const p = text.slice(6).trim();
    if (p.startsWith('play_')) {
      const e = (prof.locker || {})[p.slice(5)];
      if (e) { await api(T, 'sendAudio', { chat_id: chat, audio: e.fid }); return send(T, chat, `🎧 ${e.a} — ${e.t} · твой локер`); }
      return send(T, chat, 'Не нашёл в локере. Пришли mp3 файлом.');
    }
    return send(T, chat, 'Я — погребок. Кидай .txt экспорт — соберу комнату.\nКидай mp3 — положу в локер и буду стримить тебе.\nКоманды: /my /stats /add /add! /del /find /locker /play');
  }
  if (text.startsWith('/my')) {
    const link = env.SITE ? `${env.SITE}/?bot=${encodeURIComponent('https://' + BOT + '.workers.dev')}&id=${chat}` : '';
    return send(T, chat, link || 'Профиль есть, но SITE не задан в переменных воркера.');
  }
  if (text.startsWith('/stats')) {
    if (!prof.files.length) return send(T, chat, 'Профиль пуст. Пришли .txt.');
    const n = prof.files.reduce((s, f) => s + f.tracks.length, 0);
    const arts = new Set(); prof.files.forEach(f => f.tracks.forEach(([a]) => a.split(/,|&/).forEach(p => p.trim() && arts.add(p.trim().toLowerCase()))));
    return send(T, chat, `Плейлистов: ${prof.files.length} · треков: ${n} · имён: ${arts.size}\n` + prof.files.map(f => `· ${f.name}: ${f.tracks.length}`).join('\n'));
  }
  if (text.startsWith('/find')) {
    const m = text.slice(5).trim().match(/^(.+?)\s+-\s+(.+)$/); if (!m) return send(T, chat, 'Формат: /find Артист - Трек');
    const [a, t] = [m[1].trim(), m[2].trim()]; const q = a + ' ' + t; const qq = encodeURIComponent(q);
    const it = await itunes(q); const hit = (it.results || []).some(r => norm(r.trackName).slice(0, 14) && (norm(t).slice(0, 14).includes(norm(r.trackName).slice(0, 14)) || norm(r.trackName).slice(0, 14).includes(norm(t).slice(0, 14))));
    const dz = await deezer(q);
    return send(T, chat, `<b>${a} — ${t}</b>\n${hit ? '✅' : '⛔'} Apple Music / iTunes${hit ? ' · есть превью' : ''}\n${dz.total ? '✅' : '⛔'} Deezer${dz.total ? ' · найдено ' + dz.total : ''}\n🔎 <a href="https://music.yandex.ru/search?text=${qq}">Яндекс</a> · 🔎 <a href="https://open.spotify.com/search/${qq}">Spotify</a> · 🔎 <a href="https://www.youtube.com/results?search_query=${qq}">YouTube</a> · 🔎 <a href="https://soundcloud.com/search?q=${qq}">SoundCloud</a> · 🔎 <a href="https://bandcamp.com/search?q=${qq}">Bandcamp</a>`);
  }
  if (text.startsWith('/locker')) {
    const lk = prof.locker || {}; const e = Object.entries(lk);
    return send(T, chat, e.length ? 'Твой локер:\n' + e.slice(0, 30).map(([sl, x]) => `· /play ${sl} — ${x.a} — ${x.t}`).join('\n') : 'Локер пуст. Пришли mp3 файлом.');
  }
  if (text.startsWith('/play')) {
    const e = (prof.locker || {})[text.slice(5).trim()];
    if (!e) return send(T, chat, 'Нет такого slug. Список: /locker');
    await api(T, 'sendAudio', { chat_id: chat, audio: e.fid });
    return send(T, chat, `🎧 ${e.a} — ${e.t}`);
  }
  if (text.startsWith('/add')) {
    const force = text.startsWith('/add!');
    const m = text.slice(force ? 5 : 4).trim().match(/^(.+?)\s+-\s+(.+?)(?:\s+(https?:\/\/\S+))?$/);
    if (!m) return send(T, chat, 'Формат: /add Артист - Трек [ссылка]  (или /add! для дубля)');
    const a = m[1].replace(/\s+/g, ' ').trim(), t = m[2].replace(/\s+/g, ' ').trim(), u = m[3];
    if (!prof.files.length) return send(T, chat, 'Сначала пришли .txt — создам профиль.');
    const k = keyOf(a, t);
    if (!force && prof.files.some(f => f.tracks.some(x => keyOf(x[0], x[1]) === k))) return send(T, chat, `Такой уже есть: <b>${a} — ${t}</b>. Дубль: /add! ${a} - ${t}`);
    prof.files[0].tracks.unshift([a, t]);
    if (u) prof.urls[k] = u;
    const it = await itunes(a + ' ' + t);
    let art = null;
    for (const r of it.results || []) if (norm(r.trackName) && (norm(t).slice(0, 14).includes(norm(r.trackName).slice(0, 14)) || norm(r.trackName).slice(0, 14).includes(norm(t).slice(0, 14)))) { art = (r.artworkUrl100 || '').replace('100x100bb', '600x600bb') || null; break; }
    if (art) prof.art[k] = art;
    await putProf(env, chat, prof);
    return send(T, chat, `Добавил: ${a} — ${t}` + (u ? ' · полный трек по ссылке' : '') + (art ? ' · 🖼 обложка подтянулась' : ' · 🖼 обложки в каталоге нет, сайт нарисует свою'));
  }
  if (text.startsWith('/del')) {
    const i = parseInt(text.slice(4).trim(), 10) - 1;
    if (!prof.files.length || !(i >= 0 && i < prof.files[0].tracks.length)) return send(T, chat, 'Нет такого номера.');
    const [a, t] = prof.files[0].tracks.splice(i, 1)[0];
    await putProf(env, chat, prof);
    return send(T, chat, `Удалил: ${a} — ${t}`);
  }
  return send(T, chat, 'Команды: /my /stats /add /del /find /locker /play или пришли .txt / mp3.');
}
async function digest(s) {
  const d = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, '0')).join('');
}

export default {
  async fetch(req, env) {
    const u = new URL(req.url); const T = env.TG_TOKEN;
    if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: ENC });
    if (u.pathname === '/tg' && req.method === 'POST') {
      const up = await req.json();
      try { await handleUpdate(env, T, up); } catch (e) { console.log('upd err', e); }
      return j({ ok: true });
    }
    const id = u.searchParams.get('id') || '';
    if (u.pathname === '/api/ping') return j({ ok: true, bot: env.BOT_USER || 'pogrebok_room_bot', mode: 'worker' });
    if (u.pathname === '/api/profile' && req.method === 'GET') return id ? j(await getProf(env, id)) : j({ error: 'id?' }, 400);
    if (u.pathname === '/api/profile' && req.method === 'POST') {
      const b = await req.json(); if (!b.files) return j({ error: 'files required' }, 400);
      await putProf(env, id, b); return j({ ok: true });
    }
    if (u.pathname === '/api/add' && req.method === 'POST') {
      const b = await req.json(); const p = await getProf(env, id);
      if (!p.files.length) return j({ error: 'profile empty' }, 400);
      const i = (b.pl || 0) % p.files.length;
      p.files[i].tracks.unshift([b.a, b.t]);
      if (b.url) p.urls[keyOf(b.a, b.t)] = b.url;
      if (b.album) p.albums[keyOf(b.a, b.t)] = b.album;
      await putProf(env, id, p); return j({ ok: true, n: p.files[i].tracks.length });
    }
    if (u.pathname === '/api/search') {
      const c = await getCat(env); const q = (u.searchParams.get('q') || '').toLowerCase(); const out = [];
      for (const [k, e] of Object.entries(c.tracks)) if (q && (e.t.toLowerCase().includes(q) || e.a.toLowerCase().includes(q))) out.push({ key: k, t: e.t, a: e.a, album: e.album, art: e.art, n: e.n, comments: (e.comments || []).length });
      for (const [k, e] of Object.entries(c.artists)) if (q && k.includes(q)) out.push({ artist: e.name, n: e.n, top: Object.entries(e.top).sort((x, y) => y[1] - x[1]).slice(0, 5) });
      return j({ ok: true, res: out.slice(0, 14) });
    }
    if (u.pathname === '/api/track') {
      const c = await getCat(env); const e = c.tracks[u.searchParams.get('key') || ''];
      return e ? j(e) : j({ error: 'not in catalog' }, 404);
    }
    if (u.pathname === '/api/comment' && req.method === 'POST') {
      const b = await req.json(); const c = await getCat(env); const e = c.tracks[u.searchParams.get('key') || ''];
      if (!e) return j({ error: 'not in catalog' }, 404);
      e.comments = (e.comments || []).concat([{ id: b.id || '?', name: (b.name || 'аноним из погреба').slice(0, 40), text: (b.text || '').slice(0, 500), ts: Math.floor(Date.now() / 1000) }]).slice(-50);
      await env.POGREB.put('catalog', JSON.stringify(c)); return j({ ok: true, n: e.comments.length });
    }
    if (u.pathname === '/') return Response.redirect(env.SITE || 'https://github.com/chmoshnik187/pogrebok', 302);
    return j({ error: 'not found' }, 404);
  }
};
