const { test, describe } = require('node:test');
const assert = require('node:assert');

describe('Ox Alpha Proxy — API contracts (offline)', () => {
  test('package.json is Ox Alpha branded', () => {
    const pkg = require('../package.json');
    assert.match(pkg.name, /ox-alpha/);
    assert.match(pkg.description, /Ox Alpha/);
    assert.equal(pkg.license, 'MIT');
  });

  test('oxalpha driver exports OxAlphaDriver and RESET_MARKER', () => {
    const fs=require('fs');
    const src=fs.readFileSync(require('path').join(__dirname,'../oxalpha.js'),'utf8');
    assert.match(src, /class OxAlphaDriver/);
    assert.match(src, /RESET_MARKER/);
    assert.match(src, /module\.exports.*OxAlphaDriver/);
  });

  test('sandbox tools list is valid OpenAI shape', () => {
    const { TOOLS } = require('../sandbox');
    assert.ok(Array.isArray(TOOLS) && TOOLS.length >= 4);
    for(const t of TOOLS){
      assert.equal(t.type, 'function');
      assert.ok(t.function.name);
      assert.ok(t.function.description);
    }
  });

  test('root redirects to chat (no landing page)', async () => {
    const fs = require('fs');
    const server = fs.readFileSync(require('path').join(__dirname,'../server.js'),'utf8');
    assert.match(server, /app\.get\('\/', \(req, res\) => res\.redirect\(302, '\/chat'\)\)/);
    const html = fs.readFileSync(require('path').join(__dirname,'../public/index.html'),'utf8');
    assert.match(html, /url=\/chat/);
    assert.match(html, /location\.replace\("\/chat"\)/);
  });

  test('public chat exists with Ox Alpha shell (no Turnstile key)', async () => {
    const fs = require('fs');
    const html = fs.readFileSync(require('path').join(__dirname,'../public/chat/index.html'),'utf8');
    assert.match(html, /Chat with Ox Alpha/);
    assert.match(html, /class="sidebar"/);
    assert.match(html, /class="chat-area"/);
    assert.match(html, /empty-state/);
    // ensure Turnstile key removed
    assert.match(html, /__TURNSTILE_SITE_KEY__.*\"\"/);
    assert.doesNotMatch(html, /0x4AAAAAABp_UYRVl7snkQ51/);
  });

  test('sandbox exec: write_file + read_file + bash', async () => {
    const { execTool } = require('../sandbox');
    const user = 'test_'+Date.now();
    const w = await execTool(user, 'write_file', { path: 'hello.txt', content: 'hello ox alpha' });
    assert.ok(w.ok);
    const r = await execTool(user, 'read_file', { path: 'hello.txt' });
    assert.equal(r.content, 'hello ox alpha');
    const b = await execTool(user, 'bash', { command: 'echo hi' });
    assert.ok(b.ok);
    assert.match(b.stdout, /hi/);
  });

  test('chat assets exist', () => {
    const fs=require('fs'), path=require('path');
    assert.ok(fs.existsSync(path.join(__dirname,'../public/chat-assets/chat.css')));
    assert.ok(fs.existsSync(path.join(__dirname,'../public/chat-assets/chat.js')));
    assert.ok(fs.existsSync(path.join(__dirname,'../public/vendor/js/marked.min.js')));
  });
});
