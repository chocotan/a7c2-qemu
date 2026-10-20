'use strict';
const $ = id => document.getElementById(id);
let token = location.hash.slice(1);
try {
  token ||= sessionStorage.getItem('a7c2-token') || '';
  if (token) sessionStorage.setItem('a7c2-token', token);
} catch (_) { /* Session storage may be disabled; the URL token still works. */ }
history.replaceState(null, '', '/');
const buttons = [...document.querySelectorAll('[data-key]')];
const labels = { disconnected:'已关闭', starting:'正在启动', running:'运行中', stopping:'正在关闭', exited:'已关闭', error:'运行错误' };
let state = null, disconnected = true, pending = false, polling = false, generation = 0;
let imageNumber = 0, imageURL = '', lastEvent = 0, catalogVersion = '';
let nextCapture = Date.now() + 30000;

async function request(path, payload) {
  const options = { headers:{ 'X-Session-Token':token }, signal:AbortSignal.timeout(8000), cache:'no-store' };
  if (payload !== undefined) {
    options.method = 'POST'; options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(payload);
  }
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try { message = (await response.json()).error || message; } catch (_) { /* Keep the HTTP error. */ }
    throw new Error(message);
  }
  return response;
}

function blockedReason(entry) {
  if (!entry) return '控制元数据尚未就绪';
  if (!entry.available) return entry.unavailable_reason;
  if (Object.keys(entry.positions || {}).length) return '位置拨盘请使用新版单窗口选择；此历史控制台未实现选位';
  if (disconnected) return '本机控制服务未连接';
  if (state?.state !== 'running') return 'VM 未就绪，请先 ON 并等待启动完成';
  if (pending || state.busy || state.pending) return '正在处理上一条操作，请稍候';
  return '';
}

function controls() {
  const status = disconnected ? '' : state?.state;
  $('start').disabled = pending || !status || !state.can_start;
  $('stop').disabled = pending || !status || !state.can_stop;
  $('start').title = disconnected ? '控制服务未连接' : 'ON：启动本控制台创建的 VM；不是固件电源事件';
  $('stop').title = disconnected ? '控制服务未连接' : 'OFF：关闭本控制台创建的 VM；只清理其拥有的进程组';
  $('refresh').disabled = !!blockedReason({available:true});
  $('save').disabled = pending || disconnected || !imageNumber;
  for (const button of buttons) {
    const entry = state?.controls?.[button.dataset.key];
    const reason = blockedReason(entry);
    button.disabled = !!reason;
    button.title = entry ? `${entry.label} · ${entry.verification}${entry.note ? '：' + entry.note : ''}${reason ? '。' + reason : ''}` : reason;
    button.setAttribute('aria-label', button.title);
    button.dataset.verified = String(!!entry?.verified);
    let badge = button.querySelector('small');
    if (entry && !entry.verified && !badge) { badge = document.createElement('small'); button.append(badge); }
    if (badge) { badge.textContent = '未验证'; badge.hidden = !!entry?.verified; }
    if (entry?.shortcuts?.length) button.setAttribute('aria-keyshortcuts', entry.shortcuts.join(' '));
  }
  $('control-wheel').setAttribute('aria-disabled', String(!!blockedReason(state?.controls?.CONTROL_LEFT)));
  $('control-wheel').title = blockedReason(state?.controls?.CONTROL_LEFT) || '拖动外圈旋转；控制轮语义未验证';
}

function renderCatalog() {
  const entries = state.controls || {};
  const version = JSON.stringify(entries);
  if (version === catalogVersion) return;
  catalogVersion = version;
  const list = $('key-catalog'); list.replaceChildren();
  for (const entry of Object.values(entries)) {
    const row = document.createElement('div'), name = document.createElement('strong');
    const tag = document.createElement('span'), code = document.createElement('code'), note = document.createElement('p');
    row.className = 'catalog-item'; name.textContent = entry.label;
    tag.textContent = entry.verification; tag.className = entry.verified ? '' : 'unverified-label';
    code.textContent = entry.code ? `${entry.code}${entry.status ? ' / status ' + entry.status : ' / press 1 → release 0'}` : '原生键码未知';
    note.textContent = [entry.note, entry.unavailable_reason].filter(Boolean).join('；');
    row.append(name, tag, document.createElement('br'), code, note); list.append(row);
  }
}

function render() {
  const power = state.power_state || (state.state === 'exited' ? 'disconnected' : state.state);
  const name = labels[state.state] || state.state;
  document.body.dataset.state = power;
  $('state').textContent = (state.mock ? 'HOST MOCK / ' : '') + power;
  $('power-state').textContent = power;
  $('start').setAttribute('aria-label', `ON 启动本次 VM，当前 ${power}`);
  $('stop').setAttribute('aria-label', `OFF 关闭本次 VM，当前 ${power}`);
  $('connection').textContent = state.mock ? 'Host 模拟验收 / ' + name : name;
  $('connection-note').textContent = state.busy ? (state.busy === 'snapshot' ? '正在获取并校验固件画面。' : '正在发送输入；实际响应请看固件画面。') : state.state === 'starting' ? '等待构建、运行锁与串口初始化完成。' : state.state === 'stopping' ? '正在清理本控制台创建的 VM。' : state.state === 'running' ? '串口通道就绪；按键效果以新固件画面为准。' : 'ON 可启动本次 VM；OFF 只关闭该 VM。';
  $('error-text').textContent = state.error;
  $('error-text').hidden = !state.error;
  $('image-status').textContent = !imageNumber ? '尚无本次快照' : state.mock ? 'HOST MOCK 测试图 / 非固件画面' : state.stale || state.state !== 'running' ? '旧快照 / 当前画面未确认' : '本次已校验快照';
  $('image-status').dataset.current = String(!!imageNumber && !state.stale && state.state === 'running');
  const frame = state.snapshot;
  if (frame && imageNumber === frame.number) {
    $('capture-info').textContent = `#${frame.number} · 事务 ${frame.sequence} · ${new Date(frame.captured_at * 1000).toLocaleTimeString('zh-CN', {hour12:false})}`;
    $('frame-note').textContent = `像素来源 ${frame.pixel_source_seq} · 事务号不变表示未观察到新提交`;
  }
  const list = $('event-list'); list.replaceChildren();
  for (const event of state.events) {
    const li = document.createElement('li'), time = document.createElement('time'), text = document.createElement('span');
    const date = new Date(event.time * 1000); time.dateTime = date.toISOString();
    time.textContent = date.toLocaleTimeString('zh-CN', {hour12:false}); text.textContent = event.message;
    li.append(time, text); list.append(li);
  }
  $('empty').hidden = state.events.length > 0;
  if (state.events[0]?.id > lastEvent) { lastEvent = state.events[0].id; $('feedback').textContent = state.events[0].message; }
  renderCatalog(); controls();
}

async function updateImage(frame, currentGeneration) {
  const response = await request('/api/snapshot');
  if (Number(response.headers.get('X-Snapshot-Number')) !== frame.number) throw new Error('快照版本已更新，将重试对应元数据');
  const url = URL.createObjectURL(await response.blob());
  const check = new Image(); check.src = url;
  try { await check.decode(); } catch (error) { URL.revokeObjectURL(url); throw error; }
  if (currentGeneration !== generation) { URL.revokeObjectURL(url); return; }
  const old = imageURL; imageURL = url; imageNumber = frame.number;
  $('firmware-image').src = url; $('firmware-image').hidden = false;
  $('firmware-image').alt = state.mock ? 'HOST MOCK 测试图，非固件画面' : `本次 VM 已校验固件快照 #${frame.number}，${state.stale ? '旧画面' : '可能包含固件空白画面'}`;
  $('screen-empty').hidden = true; $('image-error').hidden = true;
  if (old) URL.revokeObjectURL(old);
}

async function syncState() {
  const currentGeneration = generation;
  try {
    const result = await (await request('/api/state')).json();
    if (currentGeneration !== generation) return;
    state = result; disconnected = false;
    if (state.snapshot && imageNumber !== state.snapshot.number) {
      try { await updateImage(state.snapshot, currentGeneration); }
      catch (error) { state.stale = true; $('feedback').textContent = '新画面读取失败，保留旧图：' + error.message; }
    }
    if (currentGeneration === generation) render();
  } catch (error) {
    if (currentGeneration !== generation) return;
    disconnected = true; document.body.dataset.state = 'disconnected';
    $('state').textContent = 'disconnected'; $('power-state').textContent = 'disconnected';
    $('connection').textContent = '控制服务连接中断'; $('connection-note').textContent = error.message;
    $('image-status').textContent = imageNumber ? '旧快照 / 连接中断' : '尚无本次快照';
    $('image-status').dataset.current = 'false';
    $('feedback').textContent = '无法取得服务状态；VM 是否停止未知。' + (token ? '连接恢复后自动重试。' : '请使用入口给出的完整控制台地址。');
    controls();
  }
}

async function act(action, payload = {}, quiet = false) {
  if (pending || disconnected) return;
  pending = true; generation++; controls();
  try {
    await request('/api/' + action, payload);
    if (action === 'key') {
      $('feedback').textContent = '输入请求已排队；正在请求新快照，响应以固件画面变化为准。';
      try { await request('/api/snapshot', {}); }
      catch (error) { $('feedback').textContent = '输入已排队，但刷新请求失败：' + error.message; }
    } else if (!quiet) $('feedback').textContent = '请求已排队，等待实际完成。';
    nextCapture = Date.now() + Number($('interval').value) * 1000;
  } catch (error) { $('feedback').textContent = '请求失败：' + error.message; }
  finally { await syncState(); pending = false; controls(); }
}

async function poll() {
  if (!polling && !pending) {
    polling = true;
    try {
      await syncState();
      const seconds = Number($('interval').value);
      if (seconds && !blockedReason({available:true}) && Date.now() >= nextCapture) await act('snapshot', {}, true);
    } finally { polling = false; }
  }
  setTimeout(poll, 1000);
}

for (const button of buttons) button.addEventListener('click', () => {
  if (!button.disabled) act('key', {key:button.dataset.key});
});
$('start').addEventListener('click', () => act('start'));
$('stop').addEventListener('click', () => act('stop'));
$('refresh').addEventListener('click', () => act('snapshot'));
$('interval').addEventListener('change', () => { nextCapture = Date.now() + Number($('interval').value) * 1000; });
$('save').addEventListener('click', async () => {
  if ($('save').disabled) return;
  try {
    const response = await request('/api/save'), url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a'); link.href = url; link.download = 'a7c2-snapshot.png'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    $('feedback').textContent = '已提供已校验 PNG 下载' + (state?.stale ? '；这是旧快照。' : '。');
  } catch (error) { $('feedback').textContent = '保存失败：' + error.message; }
});
document.addEventListener('keydown', event => {
  if (event.repeat || event.ctrlKey || event.altKey || event.metaKey || event.target.closest('input,textarea,select,[contenteditable]')) return;
  if (event.key === 'Enter' && event.target.closest('button,summary,a')) return;
  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
  const entry = Object.values(state?.controls || {}).find(item => item.shortcuts.includes(key));
  if (!entry || blockedReason(entry)) return;
  event.preventDefault(); act('key', {key:entry.name});
});

// One detent per completed drag; visible left/right buttons provide keyboard access.
const ring = $('wheel-ring');
let drag = null;
ring.addEventListener('pointerdown', event => {
  if (event.button !== 0 || blockedReason(state?.controls?.CONTROL_LEFT)) return;
  const rect = ring.getBoundingClientRect();
  drag = {id:event.pointerId, x:rect.x + rect.width / 2, y:rect.y + rect.height / 2, angle:0, last:0};
  drag.last = Math.atan2(event.clientY - drag.y, event.clientX - drag.x);
  ring.setPointerCapture(event.pointerId); $('control-wheel').classList.add('dragging'); event.preventDefault();
});
ring.addEventListener('pointermove', event => {
  if (!drag || drag.id !== event.pointerId) return;
  const angle = Math.atan2(event.clientY - drag.y, event.clientX - drag.x);
  let delta = angle - drag.last;
  if (delta > Math.PI) delta -= Math.PI * 2;
  if (delta < -Math.PI) delta += Math.PI * 2;
  drag.angle += delta; drag.last = angle;
});
function endDrag(event, cancelled = false) {
  if (!drag || drag.id !== event.pointerId) return;
  const angle = drag.angle; drag = null; $('control-wheel').classList.remove('dragging');
  if (ring.hasPointerCapture(event.pointerId)) ring.releasePointerCapture(event.pointerId);
  const name = angle < 0 ? 'CONTROL_LEFT' : 'CONTROL_RIGHT';
  if (!cancelled && Math.abs(angle) >= Math.PI / 12 && !blockedReason(state?.controls?.[name])) act('key', {key:name});
}
ring.addEventListener('pointerup', event => endDrag(event));
ring.addEventListener('pointercancel', event => endDrag(event, true));
ring.addEventListener('lostpointercapture', event => endDrag(event, true));
$('firmware-image').addEventListener('error', () => {
  $('firmware-image').hidden = true; $('image-error').hidden = false;
  $('image-status').textContent = '画面读取失败';
});
poll();
