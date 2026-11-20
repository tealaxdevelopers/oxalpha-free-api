import OpenAI from 'openai';
import { getToolsForLevel } from './tools.js';

export async function runAgentLoop(prompt, history, opts = {}) {
  const baseURL = opts.baseUrl || process.env.OX_PROXY_URL || 'http://localhost:3000/v1';
  const model = opts.model || 'ox-alpha';
  const openai = new OpenAI({ baseURL, apiKey: process.env.OX_API_KEY || 'sk-ox', dangerouslyAllowBrowser: true });

  const toolsets = (opts.toolsets || 'all').split(',').map(s=>s.trim());
  const tools = getToolsForLevel(toolsets);

  let messages = [...history, { role: 'user', content: prompt }];
  // Inject Ox Alpha identity if not present
  if (!messages.some(m=>m.role==='system')) {
    messages.unshift({ role: 'system', content: 'You are OX-AGENT — Ox Alpha stealth reasoning, 1M context, toolsets: '+toolsets.join(',')+'. Be concise, use tools when needed. You can do everything Hermes can: browser, bash, files, web, vision, delegation, workspaces.' });
  }

  const resp = await openai.chat.completions.create({
    model,
    messages,
    tools: tools.length ? tools : undefined,
    tool_choice: tools.length ? 'auto' : undefined,
    stream: false,
  });

  const msg = resp.choices[0]?.message;
  if (!msg) throw new Error('Empty response');

  // If tool_calls, execute locally (like Hermes terminal) and loop once
  if (msg.tool_calls && msg.tool_calls.length) {
    const results = [];
    for (const tc of msg.tool_calls) {
      const name = tc.function.name;
      let args = {};
      try { args = JSON.parse(tc.function.arguments||'{}'); } catch {}
      const out = await executeLocalTool(name, args, opts);
      results.push({ role: 'tool', tool_call_id: tc.id, content: JSON.stringify(out).slice(0,8000) });
    }
    // One more turn with tool results
    messages.push(msg, ...results);
    const resp2 = await openai.chat.completions.create({ model, messages, stream: false });
    return { text: resp2.choices[0]?.message?.content || '', toolCalls: msg.tool_calls };
  }

  return { text: msg.content || '', toolCalls: null };
}

async function executeLocalTool(name, args, opts) {
  const { execTool } = await import('../../sandbox.js');
  // ox-agent reuses the proxy sandbox per-workspace
  const workspace = opts.workspace || 'ox-agent';
  try {
    const r = await execTool(workspace, name, args);
    return r;
  } catch (e) {
    return { error: String(e.message||e) };
  }
}

export async function runOnce(prompt, opts) {
  const { text } = await runAgentLoop(prompt, [], opts);
  return text;
}
