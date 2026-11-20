const { test, describe } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const read = (p) => fs.readFileSync(path.join(root, p), 'utf8');

describe('Ox Alpha Proxy — tool calling contract (offline)', () => {
  test('toolInstruction shows a valid tool_calls JSON example', () => {
    const { TOOLS, toolInstruction } = require('../sandbox');
    const instr = toolInstruction(TOOLS);
    assert.ok(instr.includes('tool_calls'), 'instruction must mention tool_calls');
    for (const t of TOOLS) {
      assert.ok(instr.includes(t.function.name), `instruction must list tool ${t.function.name}`);
    }
    const m = instr.match(/```json\s*(\{[\s\S]*?\})\s*```/);
    assert.ok(m, 'instruction must contain a ```json example block');
    const example = JSON.parse(m[1]);
    assert.ok(Array.isArray(example.tool_calls) && example.tool_calls.length > 0);
    assert.equal(example.tool_calls[0].type, 'function');
    assert.ok(example.tool_calls[0].function.name);
    assert.ok(typeof example.tool_calls[0].function.arguments === 'string');
  });

  test('server wires tools end-to-end for IDEs/CLIs', () => {
    const src = read('server.js');
    assert.match(src, /const tools = Array\.isArray\(body\.tools\)/);
    assert.match(src, /toolInstruction\(tools\)/);
    assert.match(src, /parseToolCalls\(finalText\)/);
    assert.match(src, /runToolLoop\(/);
    assert.match(src, /finish_reason['"]?\s*:\s*['"]tool_calls['"]/);
    assert.match(src, /execTool\(clientId\|\|"legacy", name, args\)/);
  });
});

describe('Ox Alpha Proxy — images are small and visible (offline)', () => {
  test('chat downscales uploads before sending', () => {
    const js = read('public/chat-assets/chat.js');
    assert.match(js, /function downscaleImage/);
    assert.match(js, /1280/);
    assert.match(js, /image\/jpeg/);
    assert.match(js, /0\.82/);
    assert.match(js, /too large/);
  });

  test('chat CSS constrains every rendered image', () => {
    const css = read('public/chat-assets/chat.css');
    assert.match(css, /\.user-imgs img/);
    assert.match(css, /width:\s*120px/);
    assert.match(css, /\.prose img/);
    assert.match(css, /max-height:\s*320px/);
    assert.match(css, /max-width:\s*100%/);
  });

  test('server caps image count and bytes', () => {
    const src = read('server.js');
    assert.match(src, /MAX_IMAGES\s*=\s*4/);
    assert.match(src, /MAX_IMAGE_BYTES/);
  });

  test('driver never crashes on missing file input — tells the user instead', () => {
    const src = read('oxalpha.js');
    assert.doesNotMatch(src, /throw new Error\('file input not found'\)/);
    assert.match(src, /System note/);
    assert.match(src, /cannot see the attached image/);
  });

  test('auto-open uses localhost when LAN is off', () => {
    const src = read('server.js');
    assert.match(src, /openHost/);
    assert.match(src, /HOST === '0\.0\.0\.0' \? \(ips\[0\] \|\| 'localhost'\) : 'localhost'/);
  });
});

describe('Ox Alpha Proxy — dark-only UI (offline)', () => {
  test('no light theme anywhere in chat', () => {
    const css = read('public/chat-assets/chat.css');
    assert.doesNotMatch(css, /data-theme="light"|html\[data-theme=\\?"light/);
    assert.match(css, /color-scheme:\s*dark/);
    const html = read('public/chat/index.html');
    assert.match(html, /data-theme="dark"/);
    assert.doesNotMatch(html, /theme-pill/);
    const js = read('public/chat-assets/chat.js');
    assert.match(js, /setAttribute\("data-theme",\s*"dark"\)/);
    assert.doesNotMatch(js, /getItem\("ox_theme"\)/);
    assert.doesNotMatch(js, /setItem\("ox_theme"/);
  });

  test('settings modal is sectioned with switch, export and about', () => {
    const html = read('public/chat/index.html');
    assert.match(html, /settings-section-label/);
    assert.match(html, /General/);
    assert.match(html, /Assistant/);
    assert.match(html, /class="switch"/);
    assert.match(html, /id="voiceToggle"/);
    assert.match(html, /id="voiceSelect"/);
    assert.match(html, /id="langSelect"/);
    assert.match(html, /id="exportMd"/);
    assert.match(html, /id="exportJson"/);
    assert.match(html, /settings-about/);
    assert.match(html, /\/docs\/"/);
    assert.doesNotMatch(html, /theme-pill/);
    assert.doesNotMatch(html, /Appearance/);
    const js = read('public/chat-assets/chat.js');
    assert.match(js, /byId\("langSelect"\)/);
    assert.match(js, /exportChat/);
    assert.match(js, /\/api\/export\?chatId=/);
    const css = read('public/chat-assets/chat.css');
    assert.match(css, /\.switch input:checked\+span/);
    assert.match(css, /\.btn-primary/);
    assert.match(css, /\.btn-ghost/);
    assert.match(css, /popIn/);
  });

  test('driver never reads another chat page (no cross-chat history leak)', () => {
    const src = read('oxalpha.js');
    assert.doesNotMatch(src, /\|\| this\.page/);
  });

  test('server never 500s new-chat and auto-creates unknown chat ids', () => {
    const src = read('server.js');
    assert.match(src, /new-chat ensureChat deferred/);
    assert.match(src, /if \(chatId && !chat\) chatId = '';/);
  });

  test('client streams with throttled paints and recovers from 404', () => {
    const js = read('public/chat-assets/chat.js');
    assert.match(js, /lastPaint/);
    assert.match(js, /Date\.now\(\)-lastPaint>70/);
    assert.match(js, /res\.status===404/);
    assert.doesNotMatch(js, /randomUUID/);
    assert.match(js, /clearMessages\(\); showEmpty\(\);/);
  });

  test('settings modal nests all sections inside the body', () => {
    const html = read('public/chat/index.html');
    const b = html.indexOf('settings-modal-body');
    const f = html.indexOf('settings-modal-footer');
    for (const needle of ['settings-section-label">Language', 'settings-section-label">Data', 'settings-about', 'id="exportMd"']) {
      const i = html.indexOf(needle);
      assert.ok(i > b && i < f, `${needle} must be inside modal body`);
    }
  });

  test('flashlight hover follows the cursor', () => {
    const css = read('public/chat-assets/chat.css');
    assert.match(css, /\.spotlight::before/);
    assert.match(css, /--mx/);
    assert.match(css, /radial-gradient/);
    const js = read('public/chat-assets/chat.js');
    assert.match(js, /setProperty\("--mx"/);
    assert.match(js, /spotlight/);
  });
});
