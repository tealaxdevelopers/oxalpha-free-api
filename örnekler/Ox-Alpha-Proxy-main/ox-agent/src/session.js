import fs from 'fs';
import path from 'path';
import os from 'os';

const SESS_DIR = path.join(os.homedir(), '.ox-agent', 'sessions');
function ensure(){ fs.mkdirSync(SESS_DIR, { recursive: true }); }

export function createSession(){
  ensure();
  const id = Date.now().toString(36)+'_'+Math.random().toString(36).slice(2,6);
  const file = path.join(SESS_DIR, id+'.json');
  fs.writeFileSync(file, JSON.stringify({ id, created: Date.now(), turns: [] }));
  // prune old (>50)
  const files = fs.readdirSync(SESS_DIR).sort().reverse();
  for(const f of files.slice(50)) try{ fs.unlinkSync(path.join(SESS_DIR,f)); }catch{}
  return { id, file };
}
export function listSessions(){
  ensure();
  const files = fs.readdirSync(SESS_DIR).map(f=> ({ name:f, stat: fs.statSync(path.join(SESS_DIR,f)) })).sort((a,b)=> b.stat.mtimeMs - a.stat.mtimeMs);
  return files.slice(0,10).map(f=> `${f.name.replace('.json','')}  ${new Date(f.stat.mtime).toLocaleString()}`).join('\n') || '(no sessions)';
}
export function pruneSessions(){
  ensure();
  const now = Date.now();
  for(const f of fs.readdirSync(SESS_DIR)){
    const p = path.join(SESS_DIR,f);
    const s = fs.statSync(p);
    if(now - s.mtimeMs > 7*24*3600*1000) fs.unlinkSync(p);
  }
  console.log('Pruned sessions older than 7 days');
}
