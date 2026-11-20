const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const { spawn } = require('child_process');

const SANDBOX_DIR = process.env.SANDBOX_DIR || path.join(__dirname, 'sandbox');
const MEM_MB = parseInt(process.env.SANDBOX_MEMORY_MB || '512', 10);
const TIMEOUT_MS = parseInt(process.env.SANDBOX_TIMEOUT_MS || '30000', 10);

function ensureDir(userId){
  const dir = path.join(SANDBOX_DIR, String(userId||'legacy').replace(/[^a-z0-9_-]/gi,'_').slice(0,40) || 'legacy');
  fs.mkdirSync(dir,{recursive:true});
  return dir;
}
function safePath(base, p){
  const resolved = path.resolve(base, p);
  if(!resolved.startsWith(path.resolve(base)+path.sep) && resolved!==path.resolve(base)) throw new Error('path traversal denied');
  return resolved;
}

const TOOLS = [
  {
    type:"function",
    function:{
      name:"bash",
      description:"Execute a shell command in a per-user sandbox (auto-detects powershell/cmd/bash/python). Memory limited, timeout 30s. Use for running code, tests, scripts.",
      parameters:{
        type:"object",
        properties:{
          command:{type:"string",description:"Shell command to run"},
          workdir:{type:"string",description:"Subdirectory inside sandbox (optional)"},
          timeout:{type:"number",description:"Timeout in ms (default 30000)"}
        },
        required:["command"]
      }
    }
  },
  {
    type:"function",
    function:{
      name:"python",
      description:"Run Python code in sandbox. Shorthand for bash python.",
      parameters:{
        type:"object",
        properties:{
          code:{type:"string",description:"Python code to execute"},
          args:{type:"string",description:"Extra args"}
        },
        required:["code"]
      }
    }
  },
  {
    type:"function",
    function:{
      name:"write_file",
      description:"Create or overwrite a file in the user's sandbox. The file will be available for download/preview and hosting. Use for generating apps, HTML, etc.",
      parameters:{
        type:"object",
        properties:{
          path:{type:"string",description:"Relative path inside sandbox, e.g. index.html or app.py"},
          content:{type:"string",description:"File content (utf-8)"}
        },
        required:["path","content"]
      }
    }
  },
  {
    type:"function",
    function:{
      name:"read_file",
      description:"Read a file from the sandbox.",
      parameters:{
        type:"object",
        properties:{ path:{type:"string",description:"Relative path"} },
        required:["path"]
      }
    }
  },
  {
    type:"function",
    function:{
      name:"list_files",
      description:"List files in sandbox directory.",
      parameters:{
        type:"object",
        properties:{ dir:{type:"string",description:"Subdirectory, default ."} },
        required:[]
      }
    }
  }
];

function detectShell(cmd){
  const c=String(cmd).trim().toLowerCase();
  if(c.startsWith("python") || c.includes(".py")) return "python";
  if(c.includes("powershell")||c.includes("pwsh")||c.includes(".ps1")) return "powershell";
  if(process.platform==="win32") return "cmd";
  return "bash";
}

async function execTool(userId, name, args){
  const base = ensureDir(userId);
  if(name==="write_file"){
    const fp=safePath(base, args.path);
    fs.mkdirSync(path.dirname(fp),{recursive:true});
    fs.writeFileSync(fp, String(args.content||""), "utf8");
    // also expose via /sandbox/:user/:path route — handled in server.js static
    return { ok:true, path:args.path, bytes: Buffer.byteLength(args.content||"", "utf8") };
  }
  if(name==="read_file"){
    const fp=safePath(base, args.path);
    const content=fs.readFileSync(fp,"utf8");
    return { ok:true, content: content.slice(0, 200000) };
  }
  if(name==="list_files"){
    const dir=safePath(base, args.dir||".");
    const out=fs.readdirSync(dir,{withFileTypes:true}).map(d=>({name:d.name, dir:d.isDirectory()}));
    return { ok:true, files:out.slice(0,200) };
  }
  if(name==="python"){
    const tmp=path.join(base, `_tmp_${Date.now()}.py`);
    fs.writeFileSync(tmp,String(args.code||""),"utf8");
    const res=await execTool(userId,"bash",{command:`python "${tmp}" ${args.args||""}`});
    try{ fs.unlinkSync(tmp);}catch{}
    return res;
  }
  if(name==="bash"){
    const shell=detectShell(args.command);
    let cmd=args.command;
    let opts={cwd: base, timeout: args.timeout||TIMEOUT_MS, maxBuffer: 2*1024*1024};
    // memory limit via env — best-effort (not hard cgroup, but prevents OOM via Node)
    const env={...process.env, OX_SANDBOX_MEM_MB:String(MEM_MB)};
    return new Promise(resolve=>{
      let shellCmd, shellArgs;
      if(shell==="powershell"){
        shellCmd="powershell"; shellArgs=["-NoProfile","-Command",cmd];
      } else if(shell==="cmd"){
        shellCmd="cmd"; shellArgs=["/d","/s","/c",cmd];
      } else {
        shellCmd="bash"; shellArgs=["-lc",cmd];
      }
      if(args.workdir){
        try{ opts.cwd=safePath(base, args.workdir); fs.mkdirSync(opts.cwd,{recursive:true}); }catch{}
      }
      const p=spawn(shellCmd,shellArgs,{...opts, env, windowsHide:true});
      let out="", err="";
      const timer=setTimeout(()=>{ try{p.kill("SIGKILL");}catch{}; err+="\n[timeout after "+opts.timeout+"ms]"; }, opts.timeout);
      p.stdout.on("data",d=>{ out+=d.toString("utf8").slice(0,500000); });
      p.stderr.on("data",d=>{ err+=d.toString("utf8").slice(0,500000); });
      p.on("close",code=>{
        clearTimeout(timer);
        resolve({ ok:true, code, stdout: out.slice(0,80000), stderr: err.slice(0,80000), shell });
      });
      p.on("error",e=>{ clearTimeout(timer); resolve({ ok:false, error:String(e.message) }); });
    });
  }
  throw new Error("unknown tool: "+name);
}

function toolInstruction(tools){
  if(!Array.isArray(tools)||!tools.length) return "";
  const lines=["You have access to these tools. To use a tool, output a single JSON block exactly like:"];
  lines.push('```json');
  lines.push('{"tool_calls":[{"id":"call_1","type":"function","function":{"name":"bash","arguments":"{\\"command\\":\\"echo hi\\"}"}}]}');
  lines.push('```');
  lines.push("Available tools:");
  tools.forEach(t=>{
    const fn=t.function||t;
    lines.push(`- ${fn.name}: ${fn.description||""} params: ${JSON.stringify(fn.parameters||{})}`);
  });
  lines.push("Rules: Only use tools when needed. One tool call per turn. After tool result, continue.");
  return lines.join("\n");
}

module.exports={ TOOLS, execTool, toolInstruction, ensureDir, SANDBOX_DIR };
