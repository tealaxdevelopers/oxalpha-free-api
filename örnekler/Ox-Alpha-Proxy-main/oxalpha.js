const fs = require('fs');
const path = require('path');
let chromium=null;
try{ ({ chromium } = require('playwright')); }catch(e){ console.warn('[ox-alpha] playwright not installed — fetch mode only, run npm install to enable browser'); }

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const homeUrl = () => process.env.OX_ALPHA_URL || process.env.HOME_URL || 'https://oxalpha.com/chat';
const apiUrl = () => process.env.OX_ALPHA_API_URL || 'https://oxalpha.com/api/chat';
const MOBILE_UA =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1';
const RESET_MARKER = '__OX_RESET__';
const MAX_COMPOSER_MSG = parseInt(process.env.MAX_PROMPT || '500000', 10);

// Ox Alpha selectors — mapped from actual oxalpha.com/chat React markup
// Includes fallbacks for future UI renames + heuristic healing.
const SEL = {
  composer: ['.input-box', '.empty-input-box', '[data-testid="composer"]', 'main form', '.chat-area form'],
  textarea: ['.input-box textarea', '.empty-input-box textarea', 'textarea[placeholder]', 'form textarea', '[contenteditable="true"]'],
  submit: ['.send-btn', 'button.send-btn', 'button[aria-label*="Send"]', 'button[type="submit"]', 'form button'],
  stop: ['.stop-btn', 'button.stop-btn', 'button[aria-label*="Stop"]', 'button[data-stop-generating]'],
  file: ['input[type="file"]', '.ox-attach input', 'form input[type="file"]'],
  assistant: ['.msg-assistant', '.msg.msg-assistant', '[data-message-role="assistant"]', '.messages-col .msg-assistant'],
  roles: ['.msg', '.msg-user', '.msg-assistant', '[data-message-role]'],
  userInner: ['.msg-user .msg-bubble', '.msg-bubble', '[data-user-message-copy]'],
  assistantStreaming: ['.msg-assistant[data-streaming]', '.typing-dots', '.ox-status'],
  gate: ['[data-conversation-gate-panel]', '.ox-verify', '.verify-modal'],
  retry: ['[data-safety-retry]', '.ox-retry', 'button:has-text("Retry")'],
  inner: ['.prose', '.msg-bubble', '.markdown', '[data-stream-target]', '.msg-content'],
};

const HEURISTICS = {
  composer: ['textarea', '[contenteditable="true"]', '[role="textbox"]', 'form'],
  textarea: ['textarea', '[contenteditable="true"]'],
  submit: ['button[type="submit"]', 'button[aria-label*="send" i]', '.send-btn'],
  stop: ['button[aria-label*="stop" i]', '.stop-btn'],
  file: ['input[type="file"]'],
  assistant: ['.msg-assistant', '[data-message-author-role="assistant"]', '.markdown'],
  roles: ['.msg', '[data-message-author-role]', 'article'],
  userInner: ['.msg-bubble', '.whitespace-pre-wrap'],
  inner: ['.prose', '.markdown', '.msg-bubble', '[data-message-text]'],
};

const CHALLENGE_TITLE = 'Just a moment...';

class OxAlphaDriver {
  constructor({ headed = false, profileDir = null, timeoutMs = 180000, stateFile = null, selectorsFile = null } = {}) {
    this.headed = headed;
    this.profileDir = profileDir;
    this.timeoutMs = timeoutMs;
    this.stateFile = stateFile;
    this.selectorsFile = selectorsFile || process.env.SELECTORS_FILE || path.join(__dirname, 'selectors.json');
    this.context = null;
    this.page = null;
    this.pages = {};
    this._initialPage = null;
    this._deltas = {};
    this.ready = false;
    this.busy = false;
    this._startPromise = null;
    this._selCache = {};
    try {
      const loaded = JSON.parse(fs.readFileSync(this.selectorsFile, 'utf8'));
      if (loaded && typeof loaded === 'object') this._selCache = loaded;
    } catch {}
    this.selOrder = {};
    for (const slot of Object.keys(SEL)) {
      const seen = [];
      const list = [];
      for (const s of [this._selCache[slot], ...SEL[slot], ...(HEURISTICS[slot] || [])]) {
        if (s && !seen.includes(s)) {
          seen.push(s);
          list.push(s);
        }
      }
      this.selOrder[slot] = list;
    }
    // fetch mode state
    this._csrf = null;
    this._cookies = '';
  }

  async _healSelectors(page) {
    try {
      const report = await page.evaluate((sel) => {
        const out = {};
        for (const slot of Object.keys(sel)) {
          let found = null;
          for (const s of sel[slot]) {
            if (s && document.querySelector(s)) {
              found = s;
              break;
            }
          }
          out[slot] = found;
        }
        return out;
      }, this.selOrder);
      let changed = false;
      for (const slot of Object.keys(report)) {
        const s = report[slot];
        if (s && this._selCache[slot] !== s) {
          this._selCache[slot] = s;
          changed = true;
        }
      }
      if (changed) {
        try {
          fs.writeFileSync(this.selectorsFile, JSON.stringify(this._selCache, null, 2));
          console.log('[ox-alpha] selectors healed →', this.selectorsFile);
        } catch {}
      }
    } catch {}
  }

  static _isClosedError(e) {
    const m = String((e && e.message) || e || '');
    return (
      m.includes('browser has been closed') ||
      m.includes('context has been closed') ||
      m.includes('Target closed') ||
      m.includes('Target page, context or browser has been closed') ||
      m.includes('Session closed') ||
      m.includes('Execution context was destroyed') ||
      m.includes('Browser has been disconnected') ||
      m.includes('Connection closed') ||
      m.includes('Target crashed') ||
      m.includes('navigated to a different page')
    );
  }

  async _alive() {
    if (!this.context) return false;
    if (this.page) {
      try {
        await this.page.evaluate(() => 1);
        return true;
      } catch (e) {
        if (OxAlphaDriver._isClosedError(e)) return false;
        return true;
      }
    }
    return false;
  }

  async _relaunch() {
    try {
      if (this.context) await this.context.close().catch(() => {});
    } catch {}
    this.context = null;
    this.page = null;
    this.pages = {};
    this._initialPage = null;
    this._deltas = {};
    this.ready = false;
    this.busy = false;
    this._startPromise = null;
    console.log('[ox-alpha] browser was dead — relaunching');
    await this.start();
  }

  // ---- csrf + cookie fetch for direct API mode ----
  async _fetchCsrf(page) {
    try {
      const csrf = await page.evaluate(() => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : null;
      });
      if (csrf) this._csrf = csrf;
      const cookies = await this.context.cookies().catch(() => []);
      this._cookies = cookies.map((c) => `${c.name}=${c.value}`).join('; ');
      return csrf;
    } catch {
      return null;
    }
  }

  async _getTurnstileToken(page, timeoutMs=15000){
    // Auto-solve Turnstile: wait for cf-turnstile-response input to be filled by the widget
    const start = Date.now();
    while(Date.now() - start < timeoutMs){
      try{
        const tok = await page.evaluate(()=>{
          const el = document.querySelector('input[name="cf-turnstile-response"]');
          return el ? el.value : null;
        });
        if(tok && tok.length>20) return tok;
        // also check widget iframe already rendered means challenge ready
        const hasWidget = await page.evaluate(()=> !!document.querySelector('iframe[src*="challenges.cloudflare.com"], .ox-verify-widget iframe'));
        if(hasWidget){
          // give widget time to auto-solve
          // try to trigger verification by focusing widget
        }
      }catch{}
      await new Promise(r=>setTimeout(r, 500));
    }
    return null;
  }

  async _tryFetchAPI(chatId, message, onDelta, images) {
    // Fast path: direct POST to /api/chat using browser cookies/csrf
    // Ox Alpha streams SSE; we parse and forward deltas.
    try {
      if (!this.page || !this._csrf) await this._fetchCsrf(this.page);
      if (!this._csrf) return null;
      const headers = {
        'content-type': 'application/json',
        'x-csrf-token': this._csrf,
        'x-requested-with': 'XMLHttpRequest',
        cookie: this._cookies,
        accept: 'text/event-stream',
      };
      // Build messages like frontend does
      const body = JSON.stringify({
        messages: [{ role: 'user', content: message }],
        model: process.env.MODEL_ID || 'z-ai/glm-5.3-flash',
      });
      const res = await this.page.evaluate(async ({ url, headers, body }) => {
        const r = await fetch(url, { method: 'POST', headers, body, credentials: 'include' });
        const text = await r.text();
        return { ok: r.ok, status: r.status, text, headers: Object.fromEntries(r.headers.entries()) };
      }, { url: apiUrl(), headers, body }).catch(() => null);
      if(res && res.status===428){
        // Turnstile required — wait for fresh token and retry once
        const fresh = await this._getTurnstileToken(this.page, 12000).catch(()=>null);
        if(fresh){
          headers['x-turnstile-token']=fresh;
          const retry = await this.page.evaluate(async ({ url, headers, body }) => {
            const r = await fetch(url, { method: 'POST', headers, body, credentials: 'include' });
            const text = await r.text();
            return { ok: r.ok, status: r.status, text, headers: Object.fromEntries(r.headers.entries()) };
          }, { url: apiUrl(), headers, body }).catch(()=>null);
          if(retry && retry.ok){
            res = retry;
          } else {
            return null;
          }
        } else {
          return null;
        }
      }
      if (!res || !res.ok) return null;
      const lines = res.text.split('\n');
      let out = '';
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6).trim();
          if (data === '[DONE]') break;
          try {
            const j = JSON.parse(data);
            const c = j.choices?.[0]?.delta || {};
            const delta = c.content || j.content || j.delta || j.text || '';
            const reasoning = c.reasoning_content || c.reasoning || j.reasoning || '';
            if (reasoning && onDelta) onDelta(JSON.stringify({t:'reasoning', d: reasoning}));
            if (delta) {
              out += delta;
              if (onDelta) onDelta(JSON.stringify({t:'content', d: delta}));
            }
          } catch {
            if (data) {
              out += data;
              if (onDelta) onDelta(JSON.stringify({t:'content', d: data}));
            }
          }
        }
      }
      if (out) return { error: null, text: out };
      return null;
    } catch {
      return null;
    }
  }

  async start() {
    if(!chromium){
      this.ready = true;
      console.log('[ox-alpha] no browser, fetch-only mode');
      return true;
    }
    if (this._startPromise) {
      try {
        await this._startPromise;
        if (await this._alive()) return true;
      } catch {}
      this._startPromise = null;
    }
    this._startPromise = (async () => {
      const opts = {
        headless: !this.headed,
        viewport: { width: 1366, height: 900 },
        userAgent: MOBILE_UA,
        locale: 'en-US',
        args: [
          '--no-sandbox',
          '--disable-dev-shm-usage',
          '--disable-blink-features=AutomationControlled',
          '--lang=en-US',
        ],
      };
      if (this.profileDir) {
        this.context = await chromium.launchPersistentContext(this.profileDir, opts);
        this.page = this.context.pages()[0] || (await this.context.newPage());
      } else {
        this.context = await chromium.launch(opts);
        this.page = await this.context.newPage();
      }
      await this._preparePage(this.page);
      await this._openConversation(this.page);
      this._initialPage = this.page;
      await this._fetchCsrf(this.page).catch(() => {});
      this.ready = true;
      console.log('[ox-alpha] ready');
    })();
    return this._startPromise;
  }

  async _preparePage(page) {
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
      window.__pick = (list) => {
        for (const s of list) {
          const el = document.querySelector(s);
          if (el) return el;
        }
        return null;
      };
      window.__pickAll = (list) => {
        for (const s of list) {
          const els = document.querySelectorAll(s);
          if (els.length) return Array.from(els);
        }
        return [];
      };
      window.__innerOf = (el, list) => {
        for (const s of list) {
          const i = el.querySelector(s);
          if (i) return i;
        }
        return null;
      };
    });
    page.setDefaultTimeout(30000);
    await page.exposeFunction('__oxStreamDelta', (payload) => {
      const cb = this._deltas[page.__oxChatId];
      if (cb) {
        try{
          const j = JSON.parse(payload);
          if(j && j.t) cb(j);
          else cb({t:'content', d: String(payload)});
        }catch{
          cb({t:'content', d: String(payload)});
        }
      }
    });
  }

  async _openConversation(page) {
    const savedUrl = this.stateFile ? await this._readStateUrl() : null;
    if (savedUrl) {
      try {
        await page.goto(savedUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
        if (await this.waitForComposer(60000, page)) {
          console.log('[ox-alpha] restored:', savedUrl);
          return;
        }
        console.log('[ox-alpha] saved url unreachable, fallback');
        await page.goto(homeUrl(), { waitUntil: 'domcontentloaded', timeout: 60000 });
      } catch {
        await page.goto(homeUrl(), { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
      }
    } else {
      await page.goto(homeUrl(), { waitUntil: 'domcontentloaded', timeout: 60000 });
    }
    await this.waitForComposer(120000, page);
  }

  async ensureChat(chatId, retried = false) {
    await this.start();
    if (this.pages[chatId]) {
      try {
        await this.pages[chatId].evaluate(() => 1);
        return this.pages[chatId];
      } catch (e) {
        if (OxAlphaDriver._isClosedError(e)) delete this.pages[chatId];
        else return this.pages[chatId];
      }
    }
    let page;
    try {
      if (this._initialPage) {
        page = this._initialPage;
        this._initialPage = null;
      } else {
        page = await this.context.newPage();
        await this._preparePage(page);
        await this._openConversation(page);
      }
    } catch (e) {
      if (OxAlphaDriver._isClosedError(e) && !retried) {
        await this._relaunch();
        return this.ensureChat(chatId, true);
      }
      throw e;
    }
    page.__oxChatId = chatId;
    this.pages[chatId] = page;
    this.page = page;
    return page;
  }

  async waitForComposer(timeout = 90000, page = this.page) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      let state = null;
      try {
        state = await page.evaluate((sel) => ({
          title: document.title,
          hasComposer: !!window.__pick(sel.composer) || !!document.querySelector('textarea'),
        }), this.selOrder);
      } catch {
        state = { title: '', hasComposer: false };
      }
      if (state.hasComposer) {
        await this._healSelectors(page).catch(() => {});
        return true;
      }
      if (state.title === CHALLENGE_TITLE) {
        console.log('[ox-alpha] challenge, reloading...');
        await page.reload({ waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
        await sleep(500);
        continue;
      }
      await sleep(500);
    }
    throw new Error('Ox Alpha composer did not appear');
  }

  async _fileInputLocator(page) {
    try {
      const taSel = await page.evaluate((taSels) => {
        for (const s of taSels) if (document.querySelector(s)) return s;
        return null;
      }, this.selOrder.textarea);
      if (taSel) {
        const inner = page.locator(`form:has(${taSel}) input[type="file"]`).first();
        if ((await inner.count()) > 0) return inner;
        const attach = page.locator('.ox-attach input[type="file"]').first();
        if ((await attach.count()) > 0) return attach;
        const attachBtn = page.locator('.ox-attach, .attach-btn, [data-testid*="attach"], button[aria-label*="attach" i], button[aria-label*="upload" i], button[aria-label*="file" i]').first();
        if ((await attachBtn.count()) > 0) {
          await attachBtn.click().catch(() => {});
          await sleep(500);
          const after = page.locator('input[type="file"]').last();
          if ((await after.count()) > 0) return after;
        }
      }
      const all = page.locator('input[type="file"]');
      const cnt = await all.count();
      if (cnt > 0) return all.last();
      const created = await page.evaluate(() => {
        const existing = document.querySelector('input[type="file"]');
        if (existing) return true;
        const inp = document.createElement('input');
        inp.type = 'file';
        inp.accept = 'image/*';
        inp.style.cssText = 'position:fixed;top:-9999px;left:-9999px;opacity:0;pointer-events:none';
        inp.dataset.oxProxy = '1';
        document.body.appendChild(inp);
        return true;
      });
      if (created) {
        const proxy = page.locator('input[data-ox-proxy="1"]').first();
        if ((await proxy.count()) > 0) return proxy;
      }
      return null;
    } catch {
      return null;
    }
  }

  async _waitForAttachments(page, timeoutMs = 45000) {
    const start = Date.now();
    const deadline = start + timeoutMs;
    let sawFiles = false;
    while (Date.now() < deadline) {
      const st = await page
        .evaluate(({ fileSels, taSels }) => {
          const ta = window.__pick(taSels);
          const form = ta ? ta.closest('form') || ta.closest('.input-box') || ta.closest('.empty-input-box') : null;
          const input = (form && form.querySelector('input[type="file"]')) || window.__pick(fileSels);
          const hasFiles = !!(input && input.files && input.files.length);
          const scope = form || document;
          const thumbs = Array.from(scope.querySelectorAll('img')).filter((im) => {
            const alt = (im.getAttribute('alt') || '').toLowerCase();
            const src = (im.getAttribute('src') || '').toLowerCase();
            return /attachment|upload|preview|thumb/.test(alt) || /^data:image|^blob:/.test(src) || !!im.closest('.ox-chip');
          });
          const processing = !!scope.querySelector('[data-testid*="progress"], [role="progressbar"]');
          const chip = !!scope.querySelector('.ox-chip, .ox-fchip, .ox-attach-strip');
          return { hasFiles, thumbs: thumbs.length, processing, chip };
        }, { fileSels: this.selOrder.file, taSels: this.selOrder.textarea })
        .catch(() => ({ hasFiles: false, thumbs: 0, processing: false, chip: false }));
      if ((st.thumbs > 0 || st.chip) && !st.processing) return true;
      if (st.hasFiles) sawFiles = true;
      if (Date.now() - start > 8000 && !st.hasFiles && !st.thumbs && !st.chip && sawFiles) return false;
      if (Date.now() - start > 8000 && !sawFiles) return false;
      await sleep(300);
    }
    return false;
  }

  async status() {
    if (!this.page) return { ready: false, error: 'not_started' };
    try {
      const s = await this.page.evaluate((sel) => {
        const gatePanel = window.__pick(sel.gate);
        const retry = window.__pick(sel.retry);
        const composer = window.__pick(sel.composer) || document.querySelector('textarea');
        return {
          gated: !!(gatePanel || document.documentElement.hasAttribute('data-conversation-gated')),
          retryAfter: retry ? retry.getAttribute('data-retry-after') || '' : '',
          composerReady: !!composer,
          title: document.title,
        };
      }, this.selOrder);
      const captcha = this.page.frames().some((f) => (f.url() || '').includes('challenges.cloudflare.com') || (f.url() || '').includes('captcha'));
      return { ready: this.ready, ...s, captcha, challenge: s.title === CHALLENGE_TITLE };
    } catch {
      return { ready: this.ready, error: 'page_unavailable' };
    }
  }

  async _readStateUrl() {
    try {
      return JSON.parse(fs.readFileSync(this.stateFile, 'utf8')).conversationUrl || null;
    } catch {
      return null;
    }
  }

  async getLastAssistantText(chatId) {
    const page = this.pages[chatId];
    if (!page) return '';
    try {
      return await page.evaluate((sel) => {
        const els = window.__pickAll(sel.assistant);
        if (!els.length) return '';
        const el = els[els.length - 1];
        const inner = window.__innerOf(el, sel.inner);
        return inner ? inner.textContent : el.textContent;
      }, this.selOrder);
    } catch {
      return '';
    }
  }

  async getHistory(chatId) {
    const page = this.pages[chatId];
    if (!page) return [];
    try {
      return await page.evaluate((sel) => {
        const out = [];
        for (const el of window.__pickAll(sel.roles)) {
          if (el.closest('[hidden]')) continue;
          if (el.matches && el.matches('.typing-dots, .ox-status')) continue;
          const role =
            el.getAttribute('data-message-role') ||
            el.getAttribute('data-message-author-role') ||
            (el.classList.contains('msg-user') ? 'user' : el.classList.contains('msg-assistant') ? 'assistant' : null);
          if (!role || (role !== 'user' && role !== 'assistant')) continue;
          const inner = window.__innerOf(el, sel.inner.concat(sel.userInner));
          const text = inner ? inner.textContent.trim() : el.textContent.trim();
          if (text) out.push({ role, text });
        }
        return out;
      }, this.selOrder);
    } catch {
      return [];
    }
  }

  async submit({ chatId, message, onDelta = null, images = null }) {
    const deadline = Date.now() + this.timeoutMs;
    while (this.busy) {
      if (Date.now() > deadline) throw new Error('browser is busy');
      await sleep(250);
    }
    const page = await this.ensureChat(chatId);
    this.page = page;
    this.busy = true;
    if (onDelta) this._deltas[chatId] = onDelta;
    try {
      // Try fast fetch path first (no DOM streaming needed)
      if (!images || !images.length) {
        const fast = await this._tryFetchAPI(chatId, message, onDelta, images).catch(() => null);
        if (fast && fast.text) return fast;
      }

      await this._healSelectors(page).catch(() => {});
      if (message.length > MAX_COMPOSER_MSG) {
        throw new Error('message too large (' + Math.round(message.length / 1024) + ' KB). Split it.');
      }
      const baseline = await this.getLastAssistantText(chatId);
      const baselineCount = await page.evaluate((sel) => window.__pickAll(sel.assistant).length, this.selOrder).catch(() => 0);

      let filled = false;
      let fillLen = 0;
      for (let attempt = 0; attempt < 3 && !filled; attempt++) {
        const st = await page
          .evaluate(
            ({ text, taSels }) => {
              const ta = window.__pick(taSels);
              if (!ta) return { ok: false, reason: 'composer textarea not found' };
              if (ta.tagName === 'TEXTAREA') {
                const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                setter.call(ta, text);
                ta.dispatchEvent(new Event('input', { bubbles: true }));
              } else {
                ta.focus();
                document.execCommand('insertText', false, text);
                ta.dispatchEvent(new Event('input', { bubbles: true }));
              }
              const val = ta.value !== undefined ? ta.value : ta.textContent;
              return { ok: val === text, len: (val || '').length };
            },
            { text: message, taSels: this.selOrder.textarea }
          )
          .catch(() => ({ ok: false, reason: 'evaluate failed' }));
        if (st.reason) throw new Error(st.reason);
        filled = st.ok;
        fillLen = st.len || 0;
        if (!filled) await sleep(300);
      }
      if (!filled) throw new Error('Ox Alpha did not accept the message (' + Math.round(message.length / 1024) + ' KB — holds ' + Math.round(fillLen / 1024) + ' KB)');

      if (images && images.length) {
        const fileOpts = images.map((im) => ({
          name: im.name || 'image.png',
          mimeType: im.mimeType || 'image/png',
          buffer: im.buffer,
        }));
        let attached = false;
        try {
          for (let attempt = 0; attempt < 3 && !attached; attempt++) {
            const fileInput = await this._fileInputLocator(page);
            if (!fileInput) { console.warn('[ox-alpha] file input not found — sending without images'); break; }
            await fileInput.setInputFiles(fileOpts).catch(() => { throw new Error('could not attach image'); });
            attached = await this._waitForAttachments(page, 9000);
            if (!attached && attempt < 2) {
              await sleep(500);
              await fileInput.setInputFiles([]).catch(() => {});
            }
          }
        } catch (imgErr) {
          console.warn('[ox-alpha] image attachment failed:', imgErr.message);
        }
        if (!attached) {
          message += `\n\n[System note: the user attached ${images.length} image(s) (${fileOpts.map(f=>f.name).join(', ')}), but file upload to Ox Alpha is currently unavailable. Briefly tell the user you cannot see the attached image(s) and suggest they retry or describe the image in words.]`;
          await page.evaluate(({ text, taSels }) => {
            const ta = window.__pick ? window.__pick(taSels) : document.querySelector(taSels[0]);
            if (!ta) return;
            if ('value' in ta) {
              ta.value = (ta.value || '') + `\n\n[System note: attached image(s) could not be uploaded, tell the user you cannot see them.]`;
              ta.dispatchEvent(new Event('input', { bubbles: true }));
            }
          }, { text: message, taSels: this.selOrder.textarea }).catch(() => {});
        }
      }

      const btnOk = async () => {
        const st = await page
          .evaluate(
            ({ btnSels, stopSels }) => {
              if (window.__pick(stopSels)) return { sending: true };
              const btn = window.__pick(btnSels);
              if (!btn) return { none: true };
              return { disabled: !!btn.disabled };
            },
            { btnSels: this.selOrder.submit, stopSels: this.selOrder.stop }
          )
          .catch(() => ({ none: true }));
        if (st.sending) return true;
        if (st.none) return true;
        return !st.disabled;
      };
      let sendReady = await btnOk();
      if (!sendReady) {
        const focused = await page.evaluate((taSels) => {
          const ta = window.__pick(taSels);
          if (!ta) return false;
          ta.focus();
          return true;
        }, this.selOrder.textarea).catch(() => false);
        if (focused) {
          await page.keyboard.press('ControlOrMeta+a').catch(() => {});
          await page.keyboard.press('Delete').catch(() => {});
          await page.keyboard.insertText(message).catch(() => {});
          for (let i = 0; i < 20 && !sendReady; i++) {
            await sleep(250);
            sendReady = await btnOk();
          }
        }
      }
      if (!sendReady) throw new Error('send button stayed disabled — try splitting message');

      await page.evaluate(
        ({ sel, resetMarker, baseline }) => {
          window.__oxSeen = baseline;
          if (window.__oxObs) {
            window.__oxObs.disconnect();
            window.__oxObs = null;
          }
          const lastAssistant = () => {
            const els = window.__pickAll(sel.assistant);
            return els.length ? els[els.length - 1] : null;
          };
          const extract = (el) => {
            const inner = window.__innerOf(el, sel.inner);
            return inner ? inner.textContent : el.textContent;
          };
          window.__oxThinkSeen = "";
          const extractThink = (el) => {
            const cand = el.querySelector('.ox-msg-think, [data-thinking], .gemini-think-body, .reasoning, think');
            if(cand) return cand.textContent;
            const det = el.querySelector('details');
            if(det && /thinking/i.test(det.textContent.slice(0,60))) return det.textContent;
            return "";
          };
          const obs = new MutationObserver(() => {
            const el = lastAssistant();
            if (!el) return;
            const text = extract(el);
            const think = extractThink(el);
            if (think && think !== window.__oxThinkSeen) {
              const addedThink = think.startsWith(window.__oxThinkSeen) ? think.slice(window.__oxThinkSeen.length) : think;
              window.__oxThinkSeen = think;
              if (addedThink) window.__oxStreamDelta(JSON.stringify({t:'reasoning', d: addedThink}));
            }
            if (text.startsWith(window.__oxSeen)) {
              const added = text.slice(window.__oxSeen.length);
              window.__oxSeen = text;
              if (added) window.__oxStreamDelta(JSON.stringify({t:'content', d: added}));
            } else {
              window.__oxSeen = text;
              window.__oxStreamDelta(JSON.stringify({t:'reset'}));
              if (text) window.__oxStreamDelta(JSON.stringify({t:'content', d: text}));
            }
          });
          obs.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['data-message-streaming'] });
          window.__oxObs = obs;
        },
        { sel: this.selOrder, resetMarker: RESET_MARKER, baseline }
      );

      const trySend = async () => {
        await page.evaluate(
          ({ cSels, bSels }) => {
            const form = window.__pick(cSels);
            const btn = window.__pick(bSels);
            if (btn && typeof btn.click === 'function') btn.click();
            else if (form && typeof form.requestSubmit === 'function') form.requestSubmit();
          },
          { cSels: this.selOrder.composer, bSels: this.selOrder.submit }
        );
      };
      await trySend();

      const sendCheck = async () => {
        return await page
          .evaluate(
            ({ taSels, stopSels }) => {
              if (window.__pick(stopSels)) return true;
              const ta = window.__pick(taSels);
              if (!ta || !ta.value) return true;
              return false;
            },
            { taSels: this.selOrder.textarea, stopSels: this.selOrder.stop }
          )
          .catch(() => false);
      };
      let sent = await sendCheck();
      for (let i = 0; i < 20 && !sent; i++) {
        await sleep(250);
        sent = await sendCheck();
      }
      if (!sent) {
        await page.evaluate((taSels) => {
          const ta = window.__pick(taSels);
          if (ta) ta.focus();
        }, this.selOrder.textarea).catch(() => {});
        await page.keyboard.press('Enter').catch(() => {});
        for (let i = 0; i < 6 && !sent; i++) {
          await sleep(250);
          sent = await sendCheck();
        }
      }
      if (!sent) throw new Error('composer did not clear — page layout may have changed');

      const result = await this.waitForCompletion(baseline, page, baselineCount);
      await page.evaluate(() => {
        if (window.__oxObs) {
          window.__oxObs.disconnect();
          window.__oxObs = null;
        }
      }).catch(() => {});
      return result;
    } finally {
      delete this._deltas[chatId];
      this.busy = false;
    }
  }

  async waitForCompletion(baseline, page, baselineCount = 0) {
    const started = Date.now();
    let lastText = '';
    let lastCount = 0;
    let stable = 0;
    let gateTries = 0;
    while (Date.now() - started < this.timeoutMs) {
      let state = null;
      try {
        state = await page.evaluate((sel) => {
          const els = window.__pickAll(sel.assistant);
          const el = els.length ? els[els.length - 1] : null;
          const streamingEl = window.__pick(sel.assistantStreaming) || document.querySelector('.typing-dots') || document.querySelector('.ox-status');
          const stopBtn = window.__pick(sel.stop);
          const gatePanel = window.__pick(sel.gate);
          const retry = window.__pick(sel.retry);
          let text = '';
          if (el) {
            const inner = window.__innerOf(el, sel.inner);
            text = inner ? inner.textContent : el.textContent;
          }
          return {
            text,
            count: els.length,
            streaming: !!streamingEl,
            submitting: !!stopBtn,
            gate: !!gatePanel,
            retry: !!retry,
            retryDisabled: retry ? retry.disabled : false,
            retryAfter: retry ? retry.getAttribute('data-retry-after') : null,
          };
        }, this.selOrder);
      } catch {
        await sleep(200);
        continue;
      }
      if (state.gate) {
        if (state.retry && !state.retryDisabled && gateTries < 3) {
          gateTries += 1;
          console.log(`[ox-alpha] safety gate retry ${gateTries}`);
          await page.evaluate(() => {
            const r = document.querySelector('[data-safety-retry], .ox-retry');
            if (r) r.click();
          }).catch(() => {});
          await sleep(500);
          continue;
        }
        return { error: 'rate_limited', retryAfter: state.retryAfter, text: state.text.trim() };
      }
      const fresh = state.text !== baseline || state.count > baselineCount;
      if (fresh && state.text) {
        if (state.text !== lastText || state.count !== lastCount) {
          lastText = state.text;
          lastCount = state.count;
          stable = 0;
        } else {
          stable += 1;
        }
        if (!state.streaming && !state.submitting && stable >= 4) {
          return { error: null, text: state.text.trim() };
        }
      }
      await sleep(250);
    }
    return { error: 'timeout', text: lastText.trim() };
  }

  async resetSession() {
    try {
      await this.context.clearCookies();
    } catch {}
    for (const page of Object.values(this.pages)) {
      try {
        await page.goto(homeUrl(), { waitUntil: 'domcontentloaded', timeout: 60000 });
        await this.waitForComposer(90000, page);
      } catch {}
    }
    if (this._initialPage) {
      try {
        await this._initialPage.goto(homeUrl(), { waitUntil: 'domcontentloaded', timeout: 60000 });
        await this.waitForComposer(90000, this._initialPage);
      } catch {}
    }
    this._csrf = null;
    console.log('[ox-alpha] session cleared');
  }

  async stop() {
    const page = this.page;
    if (!page) return;
    await page.evaluate((sel) => {
      const b = window.__pick(sel.stop);
      if (b) b.click();
    }, this.selOrder).catch(() => {});
  }

  async closeChat(chatId) {
    const page = this.pages[chatId];
    if (!page) return;
    try {
      await page.close();
    } catch {}
    delete this.pages[chatId];
    delete this._deltas[chatId];
    if (this.page === page) {
      const next = Object.values(this.pages)[0];
      this.page = next || this._initialPage || null;
    }
  }

  async dispose() {
    try {
      await this.context.close();
    } catch {}
    this.context = null;
    this.page = null;
    this.pages = {};
    this._initialPage = null;
    this.ready = false;
    this._startPromise = null;
  }
}

module.exports = { OxAlphaDriver, RESET_MARKER };
