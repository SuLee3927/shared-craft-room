const parts = location.pathname.split('/').filter(Boolean);
const key = parts[1];
const base = `/api/${encodeURIComponent(key)}`;
const $ = selector => document.querySelector(selector);
let items = [];
let choosing = null;

async function req(url, options = {}) {
  const response = await fetch(url, {headers: {'Content-Type': 'application/json'}, ...options});
  const data = await response.json();
  if (!response.ok || !data.ok) throw Error(data.error || '作品没放稳');
  return data;
}

function esc(value) {
  return String(value).replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[character]);
}

function date(value) {
  return new Intl.DateTimeFormat('zh-CN', {month: 'long', day: 'numeric'}).format(new Date(value));
}

function preloadImage(src) {
  return new Promise(resolve => {
    const image = new Image();
    image.onload = image.onerror = resolve;
    image.src = src;
  });
}

async function prepareWall() {
  const urls = [];
  items.filter(item => item.featured_slot).forEach(item => urls.push(`${base}/gallery/${item.id}.png`));
  items.filter(item => item.kind === 'bead' && item.charm_slot).forEach(item => urls.push(`${base}/gallery/${item.id}/display.png`));
  const room = $('.room-bg');
  const roomReady = room.complete ? (room.decode ? room.decode().catch(() => {}) : Promise.resolve()) : new Promise(resolve => {
    room.onload = room.onerror = resolve;
  });
  await Promise.all([roomReady, ...[...new Set(urls)].map(preloadImage)]);
  drawWall();
  requestAnimationFrame(() => $('.wall').classList.add('ready'));
}

function drawWall() {
  for (let slot = 1; slot <= 3; slot += 1) {
    const button = $(`[data-slot="${slot}"]`);
    const item = items.find(entry => entry.featured_slot === slot);
    button.innerHTML = item
      ? `<img src="${base}/gallery/${item.id}.png" alt="${esc(item.title)}">`
      : '<span>选择作品</span>';
    button.dataset.id = item?.id || '';
  }
  const stand = $('#stand-slot');
  const standingItem = items.find(entry => entry.featured_slot === 4);
  stand.innerHTML = standingItem ? `<img src="${base}/gallery/${standingItem.id}.png" alt="${esc(standingItem.title)}">` : '';
  stand.dataset.id = standingItem?.id || '';
  const beads = items.filter(item => item.kind === 'bead' && item.charm_slot);
  $('#charms').innerHTML = beads.map(item => `
    <button class="charm charm-slot-${item.charm_slot}" data-open="${item.id}" aria-label="查看${esc(item.title)}">
      <img src="${base}/gallery/${item.id}/display.png" alt="${esc(item.title)}">
    </button>`).join('');
  document.querySelectorAll('.charm').forEach(button => {
    button.onclick = () => openWork(button.dataset.open);
  });
}

function actionButtons(item, selectId) {
  const outside = item.charm_slot || item.featured_slot ? `<button class="unshow" data-unshow="${item.id}">从外面取下</button>` : '';
  if (item.kind === 'bead' && item.has_pouch) return `${outside}<button class="hang" data-hang="${item.id}">挂到袋架</button>`;
  const stand = item.kind === 'sketch' ? `<button data-stand="${item.id}">摆到桌上</button>` : '';
  return `${outside}${stand}<button class="feature" data-feature="${item.id}">${selectId === item.id ? '请选择墙上的画框' : '裱到画框'}</button>`;
}

function openDrawer(selectId = null) {
  choosing = selectId;
  $('#works').innerHTML = items.length ? `<div class="work-grid">${items.map(item => `
    <article class="work">
      <button class="preview" data-open="${item.id}"><img src="${base}/gallery/${item.id}.png" alt="${esc(item.title)}"></button>
      <strong>${esc(item.title)}</strong>
      <small>${esc(item.authors.join('、') || '共同创作')} · ${date(item.created_at)}</small>
      <div class="actions"><button data-remove="${item.id}">撤下</button>${actionButtons(item, selectId)}</div>
    </article>`).join('')}</div>` : '<div class="empty"><b>♡</b><p>还没有收入作品。</p></div>';
  bind();
  $('#drawer').classList.add('open');
  $('#drawer').setAttribute('aria-hidden', 'false');
  $('#shade').hidden = false;
}

function closeDrawer() {
  $('#drawer').classList.remove('open');
  $('#drawer').setAttribute('aria-hidden', 'true');
  $('#shade').hidden = true;
  choosing = null;
}

function bind() {
  document.querySelectorAll('[data-open]').forEach(button => button.onclick = () => openWork(button.dataset.open));
  document.querySelectorAll('[data-feature]').forEach(button => button.onclick = () => {
    const selected = button.dataset.feature;
    closeDrawer();
    choosing = selected;
    $('#status').textContent = '现在点墙上的一个画框';
  });
  document.querySelectorAll('[data-stand]').forEach(button => button.onclick = () => feature(button.dataset.stand, 4));
  document.querySelectorAll('[data-hang]').forEach(button => button.onclick = () => hang(button.dataset.hang, true));
  document.querySelectorAll('[data-unshow]').forEach(button => button.onclick = () => unshow(button.dataset.unshow));
  document.querySelectorAll('[data-remove]').forEach(button => button.onclick = () => removeWork(button.dataset.remove));
}

async function hang(id, enabled) {
  try {
    items = (await req(`${base}/gallery/${id}`, {method: 'POST', body: JSON.stringify({action: 'hang', enabled})})).items;
    drawWall();
    openDrawer();
    $('#status').textContent = enabled ? '已经挂到合适的透明袋里' : '已经从袋架取下';
  } catch (error) {
    $('#status').textContent = error.message;
  }
}

async function unshow(id) {
  const item = items.find(entry => entry.id === id);
  if (item?.charm_slot) await hang(id, false);
  else await feature(id, null);
}

async function feature(id, slot) {
  try {
    items = (await req(`${base}/gallery/${id}`, {method: 'POST', body: JSON.stringify({action: 'feature', slot})})).items;
    drawWall();
    closeDrawer();
    $('#status').textContent = slot === 4 ? '已经摆到桌上的画架' : slot ? `已经裱进第 ${slot} 个画框` : '已经从展示位取下';
  } catch (error) {
    $('#status').textContent = error.message;
  }
}

document.querySelectorAll('.frame-slot').forEach(button => button.onclick = () => {
  if (choosing) feature(choosing, +button.dataset.slot);
  else if (button.dataset.id) openWork(button.dataset.id);
  else openDrawer();
});
$('#stand-slot').onclick = () => {
  const id = $('#stand-slot').dataset.id;
  if (id) openWork(id);
  else openDrawer();
};

function openWork(id) {
  const item = items.find(entry => entry.id === id);
  const dialog = $('#viewer');
  dialog.querySelector('img').src = `${base}/gallery/${id}.png`;
  dialog.querySelector('strong').textContent = item.title;
  dialog.querySelector('span').textContent = `${item.authors.join('、') || '共同创作'} · ${date(item.created_at)}`;
  dialog.showModal();
}

async function removeWork(id) {
  if (!confirm('从作品间撤下吗？原作会保留。')) return;
  try {
    await req(`${base}/gallery/${id}`, {method: 'DELETE'});
    items = items.filter(item => item.id !== id);
    drawWall();
    openDrawer();
  } catch (error) {
    $('#status').textContent = error.message;
  }
}

$('#open-all').onclick = () => openDrawer();
$('#close').onclick = closeDrawer;
$('#shade').onclick = closeDrawer;
$('#viewer .viewer-close').onclick = () => $('#viewer').close();

req(`${base}/gallery`).then(async data => {
  items = data.items;
  await prepareWall();
  $('#status').textContent = `这里收藏了 ${items.length} 件作品`;
}).catch(error => $('#status').textContent = error.message);
