export const TOOLSETS = {
  web: ['webfetch','websearch','web_extract'],
  terminal: ['bash','process'],
  file: ['read','write','edit','glob','grep','list'],
  browser: ['browser_navigate','browser_snapshot','browser_click','browser_type','browser_scroll','browser_vision','browser_back'],
  vision: ['vision_analyze','image_generate'],
  code: ['execute_code','delegate_task'],
  todo: ['todowrite','todoread'],
  memory: ['memory','session_search'],
  all: null
};

export const ALL_TOOLS = [
  { type:'function', function:{ name:'bash', description:'Execute shell (powershell/cmd/bash/python) in isolated workspace, memory-limited', parameters:{ type:'object', properties:{ command:{type:'string'}, workdir:{type:'string'} }, required:['command'] }}},
  { type:'function', function:{ name:'read', description:'Read file', parameters:{ type:'object', properties:{ filePath:{type:'string'} }, required:['filePath'] }}},
  { type:'function', function:{ name:'write', description:'Write file', parameters:{ type:'object', properties:{ filePath:{type:'string'}, content:{type:'string'} }, required:['filePath','content'] }}},
  { type:'function', function:{ name:'edit', description:'Edit file exact replace', parameters:{ type:'object', properties:{ filePath:{type:'string'}, oldString:{type:'string'}, newString:{type:'string'} }, required:['filePath','oldString','newString'] }}},
  { type:'function', function:{ name:'glob', description:'Find files by pattern', parameters:{ type:'object', properties:{ pattern:{type:'string'} }, required:['pattern'] }}},
  { type:'function', function:{ name:'grep', description:'Search content', parameters:{ type:'object', properties:{ pattern:{type:'string'} }, required:['pattern'] }}},
  { type:'function', function:{ name:'webfetch', description:'Fetch URL', parameters:{ type:'object', properties:{ url:{type:'string'} }, required:['url'] }}},
  { type:'function', function:{ name:'websearch', description:'Web search', parameters:{ type:'object', properties:{ query:{type:'string'} }, required:['query'] }}},
  { type:'function', function:{ name:'browser_navigate', description:'Navigate browser', parameters:{ type:'object', properties:{ url:{type:'string'} }, required:['url'] }}},
  { type:'function', function:{ name:'browser_snapshot', description:'Accessibility snapshot', parameters:{ type:'object', properties:{}, required:[] }}},
  { type:'function', function:{ name:'todowrite', description:'Manage todo list', parameters:{ type:'object', properties:{ todos:{type:'array', items:{type:'object', properties:{content:{type:'string'}, status:{type:'string'}}} } }, required:['todos'] }}},
  { type:'function', function:{ name:'delegate_task', description:'Delegate to subagent', parameters:{ type:'object', properties:{ prompt:{type:'string'}, subagent_type:{type:'string'} }, required:['prompt','subagent_type'] }}},
];

export function getToolsets(){ return Object.keys(TOOLSETS); }
export function getAllTools(){ return ALL_TOOLS; }
export function getToolsForLevel(levels){
  if(levels.includes('all')) return ALL_TOOLS;
  const out = new Set();
  for(const lvl of levels){
    const names = TOOLSETS[lvl];
    if(!names) continue;
    for(const t of ALL_TOOLS) if(names.includes(t.function.name)) out.add(t);
  }
  // If no match, return all (better than Hermes which returns none)
  return out.size ? Array.from(out) : ALL_TOOLS;
}
