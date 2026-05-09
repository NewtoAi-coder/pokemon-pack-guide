/* Personal sync via passphrase — no accounts, no email.
 *
 * The user picks a passphrase they'll remember on both devices. We
 * encrypt their localStorage state client-side with a PBKDF2-derived
 * AES-GCM key, then push the ciphertext to Supabase keyed by an opaque
 * SHA-256 of the passphrase. The server never sees the plaintext or
 * anything that identifies a user.
 *
 * Loaded by binder.html and binders.html. Exposes window.BinderSync
 * with a small API:
 *
 *   BinderSync.isConfigured()     // SUPABASE_URL filled in?
 *   BinderSync.hasPassphrase()    // saved on this device?
 *   BinderSync.getStoredPassphrase()
 *   BinderSync.setStoredPassphrase(p)   // null to clear
 *   BinderSync.getLastSyncedAt()  // ms epoch, 0 if never
 *   BinderSync.syncOnce(passphrase) -> { local, cloud, merged }
 *   BinderSync.wipeCloud(passphrase)
 *   BinderSync.promptPassphrase(opts) -> Promise<string|null>
 *   BinderSync.openSettingsMenu(anchorEl, callbacks)
 *
 * Pages listen for a "binderSync:complete" CustomEvent on window and
 * re-read localStorage + re-render after a successful sync.
 *
 * Configure these with your Supabase project URL + anon key:
 *   supabase.com → your project → Settings → API
 * Anon key is safe in client code — security comes from client-side
 * encryption, not from hiding the key.
 */
(function (window) {
  'use strict';

  const SUPABASE_URL = 'https://vzmrpywrkyzqbarqwpna.supabase.co';
  // New-format publishable key (replaces the legacy "anon" eyJ... key).
  // supabase-js v2 accepts both formats; this is verified working against
  // the project's REST API (PGRST205 post-auth response on binder_sync).
  const SUPABASE_ANON_KEY = 'sb_publishable_xd3_-c7lQS99QdtLAJvRGg_QJr0g1P-';

  // localStorage keys we own
  const PASSPHRASE_KEY = 'binder_sync_passphrase';
  const LAST_SYNCED_KEY = 'binder_sync_last_at';

  // Crypto parameters
  const PBKDF2_ITERATIONS = 100000;
  const SALT_LENGTH = 16;
  const IV_LENGTH = 12;
  const KEY_HASH_NAMESPACE = 'binder-sync-v1:';

  let supabaseClient = null;

  function isConfigured() {
    return !SUPABASE_URL.startsWith('YOUR_') && !SUPABASE_ANON_KEY.startsWith('YOUR_');
  }

  function ensureSupabase() {
    if (!isConfigured()) throw new Error('Sync is not configured yet — Supabase URL/key missing in sync.js');
    if (!window.supabase) throw new Error('Supabase JS not loaded');
    if (!supabaseClient) {
      supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
    }
    return supabaseClient;
  }

  // ----- buffer helpers -----

  function bufToHex(buf) {
    return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
  }
  function hexToBuf(hex) {
    const out = new Uint8Array(hex.length / 2);
    for (let i = 0; i < hex.length; i += 2) out[i / 2] = parseInt(hex.substr(i, 2), 16);
    return out.buffer;
  }
  function bufToBase64(buf) {
    const bytes = new Uint8Array(buf);
    let s = '';
    for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s);
  }
  function base64ToBuf(b64) {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes.buffer;
  }
  function strToBuf(s) { return new TextEncoder().encode(s); }
  function bufToStr(b) { return new TextDecoder().decode(b); }

  // ----- crypto -----

  async function deriveKey(passphrase, saltBuf) {
    const baseKey = await crypto.subtle.importKey(
      'raw', strToBuf(passphrase), { name: 'PBKDF2' }, false, ['deriveKey']
    );
    return crypto.subtle.deriveKey(
      { name: 'PBKDF2', salt: saltBuf, iterations: PBKDF2_ITERATIONS, hash: 'SHA-256' },
      baseKey,
      { name: 'AES-GCM', length: 256 },
      false,
      ['encrypt', 'decrypt']
    );
  }

  async function keyHashOf(passphrase) {
    const data = strToBuf(KEY_HASH_NAMESPACE + passphrase);
    const hash = await crypto.subtle.digest('SHA-256', data);
    return bufToHex(hash);
  }

  async function encryptJson(obj, passphrase) {
    const salt = crypto.getRandomValues(new Uint8Array(SALT_LENGTH));
    const iv = crypto.getRandomValues(new Uint8Array(IV_LENGTH));
    const key = await deriveKey(passphrase, salt);
    const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, strToBuf(JSON.stringify(obj)));
    return JSON.stringify({
      v: 1,
      salt: bufToHex(salt),
      iv: bufToHex(iv),
      ct: bufToBase64(ct)
    });
  }

  async function decryptJson(blob, passphrase) {
    const env = JSON.parse(blob);
    if (env.v !== 1) throw new Error('Unknown sync blob version: ' + env.v);
    const salt = new Uint8Array(hexToBuf(env.salt));
    const iv = new Uint8Array(hexToBuf(env.iv));
    const key = await deriveKey(passphrase, salt);
    const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, base64ToBuf(env.ct));
    return JSON.parse(bufToStr(pt));
  }

  // ----- local state I/O -----

  // Pull every binder-related localStorage entry — the qty-per-slot maps,
  // per-set view modes, and the directory mode. Skip our own metadata
  // (passphrase, last-synced-at) so they don't leak into the cloud blob.
  function gatherLocalState() {
    const out = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (
        k === PASSPHRASE_KEY ||
        k === LAST_SYNCED_KEY
      ) continue;
      if (
        k.startsWith('binder_have_') ||
        k.startsWith('binder_mode_') ||
        k === 'binders_directory_mode'
      ) {
        out[k] = localStorage.getItem(k);
      }
    }
    return out;
  }

  function applyLocalState(state) {
    for (const k in state) localStorage.setItem(k, state[k]);
  }

  // Merge two state maps. binder_have_* values are JSON-encoded qty
  // objects — merge with max-qty-per-slot (deletions don't propagate;
  // the user accepts that tradeoff for personal use). All other keys
  // are scalars; cloud wins (it's the user's most recent expressed
  // preference from another device).
  function mergeState(local, cloud) {
    const merged = Object.assign({}, local);
    for (const k in cloud) {
      if (k.startsWith('binder_have_')) {
        let l = {}, c = {};
        try { l = JSON.parse(local[k] || '{}') || {}; } catch (e) {}
        try { c = JSON.parse(cloud[k] || '{}') || {}; } catch (e) {}
        const out = {};
        const keys = new Set([...Object.keys(l), ...Object.keys(c)]);
        for (const slot of keys) {
          const lv = +l[slot] || 0, cv = +c[slot] || 0;
          const m = Math.max(lv, cv);
          if (m > 0) out[slot] = m;
        }
        merged[k] = JSON.stringify(out);
      } else {
        merged[k] = cloud[k];
      }
    }
    return merged;
  }

  // ----- public passphrase storage -----

  function getStoredPassphrase() { return localStorage.getItem(PASSPHRASE_KEY); }
  function setStoredPassphrase(p) {
    if (p) localStorage.setItem(PASSPHRASE_KEY, p);
    else localStorage.removeItem(PASSPHRASE_KEY);
  }
  function getLastSyncedAt() {
    const v = localStorage.getItem(LAST_SYNCED_KEY);
    return v ? parseInt(v, 10) : 0;
  }
  function setLastSyncedAt(t) { localStorage.setItem(LAST_SYNCED_KEY, String(t)); }
  function hasPassphrase() { return !!getStoredPassphrase(); }

  // ----- core sync -----

  async function syncOnce(passphrase) {
    const sb = ensureSupabase();
    const keyHash = await keyHashOf(passphrase);
    const local = gatherLocalState();

    // Pull
    const { data: row, error: pullErr } = await sb
      .from('binder_sync')
      .select('ciphertext')
      .eq('key_hash', keyHash)
      .maybeSingle();
    if (pullErr) throw pullErr;

    let cloud = {};
    if (row && row.ciphertext) {
      try {
        cloud = await decryptJson(row.ciphertext, passphrase);
      } catch (e) {
        const err = new Error('Wrong passphrase, or cloud data is corrupted.');
        err.cause = e;
        throw err;
      }
    }

    // Merge
    const merged = mergeState(local, cloud);

    // Apply locally
    applyLocalState(merged);

    // Encrypt + push
    const blob = await encryptJson(merged, passphrase);
    const { error: pushErr } = await sb.from('binder_sync').upsert({
      key_hash: keyHash,
      ciphertext: blob,
      updated_at: new Date().toISOString()
    });
    if (pushErr) throw pushErr;

    setLastSyncedAt(Date.now());

    const stats = {
      localKeys: Object.keys(local).length,
      cloudKeys: Object.keys(cloud).length,
      mergedKeys: Object.keys(merged).length
    };

    window.dispatchEvent(new CustomEvent('binderSync:complete', { detail: stats }));
    return stats;
  }

  async function wipeCloud(passphrase) {
    const sb = ensureSupabase();
    const keyHash = await keyHashOf(passphrase);
    const { error } = await sb.from('binder_sync').delete().eq('key_hash', keyHash);
    if (error) throw error;
  }

  // ----- minimal modal UI -----
  // Self-contained so binder.html / binders.html don't need their own
  // markup. Built lazily on first use.

  let activeModal = null;

  function closeModal() {
    if (activeModal) {
      activeModal.remove();
      activeModal = null;
    }
  }

  function ensureModalStyles() {
    if (document.getElementById('binder-sync-modal-styles')) return;
    const css = `
      .bs-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:1000;display:flex;align-items:center;justify-content:center;padding:20px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}
      .bs-modal{background:#1a1a1a;border:1px solid #333;border-radius:12px;padding:22px;max-width:440px;width:100%;color:#eee;box-shadow:0 12px 40px rgba(0,0,0,0.6);}
      .bs-title{font-size:1.1rem;font-weight:700;margin-bottom:8px;color:#fff;}
      .bs-body{font-size:0.9rem;line-height:1.45;color:#bbb;margin-bottom:14px;}
      .bs-body b{color:#ddd;}
      .bs-input{width:100%;padding:10px 12px;background:#0a0a0a;border:1px solid #333;border-radius:6px;color:#fff;font-size:0.95rem;font-family:inherit;}
      .bs-input:focus{border-color:#4a9eff;outline:none;}
      .bs-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:14px;}
      .bs-btn{padding:9px 14px;border-radius:6px;border:1px solid #333;background:#2a2a2a;color:#eee;cursor:pointer;font-size:0.88rem;font-weight:600;}
      .bs-btn:hover{background:#3a3a3a;}
      .bs-btn.primary{background:#4a9eff;border-color:#4a9eff;color:#fff;}
      .bs-btn.primary:hover{background:#3a8edf;}
      .bs-btn.danger{background:#a23131;border-color:#c14242;color:#fff;}
      .bs-btn.danger:hover{background:#c14242;}
      .bs-error{color:#ff8a8a;font-size:0.85rem;margin-top:8px;display:none;}
      .bs-menu{position:absolute;background:#1a1a1a;border:1px solid #333;border-radius:8px;padding:4px;min-width:200px;box-shadow:0 8px 24px rgba(0,0,0,0.6);z-index:900;}
      .bs-menu-item{display:block;width:100%;text-align:left;padding:8px 12px;background:transparent;border:0;color:#ddd;cursor:pointer;font-size:0.85rem;border-radius:5px;}
      .bs-menu-item:hover{background:#2a2a2a;}
      .bs-menu-item.danger{color:#ff8a8a;}
      .bs-menu-divider{height:1px;background:#2a2a2a;margin:4px 0;}
    `;
    const tag = document.createElement('style');
    tag.id = 'binder-sync-modal-styles';
    tag.textContent = css;
    document.head.appendChild(tag);
  }

  function promptPassphrase(opts) {
    opts = opts || {};
    ensureModalStyles();
    closeModal();
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.className = 'bs-overlay';
      overlay.innerHTML = `
        <div class="bs-modal" role="dialog" aria-modal="true">
          <div class="bs-title">${opts.title || 'Set up sync'}</div>
          <div class="bs-body">${opts.body ||
            'Pick a passphrase you can remember on every device. <b>This is end-to-end encrypted</b> — we can\'t recover it if you forget. Don\'t reuse a real password.'}</div>
          <input type="password" class="bs-input" id="bs-pass" autocomplete="off" autocapitalize="off" placeholder="Your passphrase" />
          <div class="bs-error" id="bs-err"></div>
          <div class="bs-actions">
            <button class="bs-btn" id="bs-cancel">Cancel</button>
            <button class="bs-btn primary" id="bs-ok">${opts.okLabel || 'Set passphrase'}</button>
          </div>
        </div>`;
      document.body.appendChild(overlay);
      activeModal = overlay;

      const input = overlay.querySelector('#bs-pass');
      const err = overlay.querySelector('#bs-err');
      input.focus();

      function done(value) {
        closeModal();
        resolve(value);
      }
      overlay.querySelector('#bs-cancel').onclick = () => done(null);
      overlay.querySelector('#bs-ok').onclick = () => {
        const v = input.value.trim();
        if (v.length < 4) {
          err.textContent = 'Use at least 4 characters.';
          err.style.display = 'block';
          return;
        }
        done(v);
      };
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') overlay.querySelector('#bs-ok').click();
        if (e.key === 'Escape') done(null);
      });
      overlay.addEventListener('click', (e) => { if (e.target === overlay) done(null); });
    });
  }

  function confirm(opts) {
    ensureModalStyles();
    closeModal();
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.className = 'bs-overlay';
      const okClass = opts.danger ? 'bs-btn danger' : 'bs-btn primary';
      overlay.innerHTML = `
        <div class="bs-modal" role="dialog" aria-modal="true">
          <div class="bs-title">${opts.title || 'Are you sure?'}</div>
          <div class="bs-body">${opts.body || ''}</div>
          <div class="bs-actions">
            <button class="bs-btn" id="bs-cancel">Cancel</button>
            <button class="${okClass}" id="bs-ok">${opts.okLabel || 'Confirm'}</button>
          </div>
        </div>`;
      document.body.appendChild(overlay);
      activeModal = overlay;
      overlay.querySelector('#bs-cancel').onclick = () => { closeModal(); resolve(false); };
      overlay.querySelector('#bs-ok').onclick = () => { closeModal(); resolve(true); };
      overlay.addEventListener('click', (e) => { if (e.target === overlay) { closeModal(); resolve(false); } });
    });
  }

  // Settings dropdown anchored to a gear button.
  function openSettingsMenu(anchorEl, callbacks) {
    ensureModalStyles();
    // Close any existing menu first
    const existing = document.querySelector('.bs-menu');
    if (existing) { existing.remove(); return; }

    const menu = document.createElement('div');
    menu.className = 'bs-menu';
    menu.innerHTML = `
      <button class="bs-menu-item" data-act="change">Change passphrase</button>
      <button class="bs-menu-item" data-act="clear">Clear passphrase from this device</button>
      <div class="bs-menu-divider"></div>
      <button class="bs-menu-item danger" data-act="wipe">Wipe cloud data</button>
    `;
    document.body.appendChild(menu);

    const r = anchorEl.getBoundingClientRect();
    const top = window.scrollY + r.bottom + 6;
    let left = window.scrollX + r.right - menu.offsetWidth;
    if (left < 8) left = 8;
    menu.style.top = top + 'px';
    menu.style.left = left + 'px';

    function close() {
      menu.remove();
      document.removeEventListener('click', onDocClick, true);
      document.removeEventListener('keydown', onKey);
    }
    function onDocClick(e) {
      if (!menu.contains(e.target) && e.target !== anchorEl) close();
    }
    function onKey(e) { if (e.key === 'Escape') close(); }
    setTimeout(() => {
      document.addEventListener('click', onDocClick, true);
      document.addEventListener('keydown', onKey);
    }, 0);

    menu.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-act]');
      if (!btn) return;
      const act = btn.dataset.act;
      close();
      if (act === 'change' && callbacks.onChange) callbacks.onChange();
      else if (act === 'clear' && callbacks.onClear) callbacks.onClear();
      else if (act === 'wipe' && callbacks.onWipe) callbacks.onWipe();
    });
  }

  // ----- public API -----

  window.BinderSync = {
    isConfigured,
    hasPassphrase,
    getStoredPassphrase,
    setStoredPassphrase,
    getLastSyncedAt,
    syncOnce,
    wipeCloud,
    promptPassphrase,
    confirm,
    openSettingsMenu
  };
})(window);
