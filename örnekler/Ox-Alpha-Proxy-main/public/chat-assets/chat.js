/* Ox Alpha Chat — clean dark, no thinking dropdown, cool shine thinking */
(() => {"use strict";
const $=(s,el=document)=>el.querySelector(s);
const $$=(s,el=document)=>Array.from(el.querySelectorAll(s));
const byId=id=>document.getElementById(id);
let activeChatId=null;
let sending=false;
let abortCtrl=null;
let pendingImages=[];
let pendingFiles=[];
const MAX_IMAGES=2, MAX_FILES=3, MAX_IMG_MB=5, MAX_FILE_KB=100;
const FILE_SVG='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>';
const COPY_SVG='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"></path></svg>';
const UP_SVG='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3H14z"></path><path d="M7 22H4a2 2 0 01-2-2v-7a2 2 0 01 2-2h3"></path></svg>';
const DOWN_SVG='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3H10z"></path><path d="M17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"></path></svg>';
const RETRY_SVG='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg>';
const SPEAK_SVG='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M15.54 8.46a5 5 0 0 1 0 7.08"></path></svg>';
const emptyState=$(".empty-state");
const messagesWrap=$(".messages-wrap");
const messagesCol=$(".messages-col");
const inputArea=$(".input-area");
const sidebarChats=$(".sidebar-chats");
const settingsModal=$("#settingsModal")||$(".settings-modal");
const systemPromptEl=byId("systemPrompt")||$("#systemPrompt");
const voiceToggle=byId("voiceToggle");
const voiceSelect=byId("voiceSelect");
function getVoice(){ return (voiceSelect?.value||localStorage.getItem("ox_voice")||"en-US-AriaNeural"); }
function appState(){ return emptyState && messagesCol && messagesWrap }
function renderMarkdown(text){
  try{
    const raw=window.marked ? window.marked.parse(text||"") : (text||"").replace(/\n/g,"<br>");
    const safe=window.DOMPurify ? window.DOMPurify.sanitize(raw,{USE_PROFILES:{html:true}, ADD_ATTR:["target"], FORBID_TAGS:["style","form","input","button","textarea","iframe"]}) : raw;
    return safe;
  }catch{ return (text||"").replace(/\n/g,"<br>"); }
}
function highlightAll(root){
  try{ root.querySelectorAll("pre code").forEach(b=>window.hljs && window.hljs.highlightElement(b)); }catch{}
}
async function fetchChats(){
  try{ const r=await fetch("/api/chats",{headers:clientHeaders()}); const j=await r.json(); return j; }catch{ return {chats:[],activeChatId:null}; }
}
async function fetchHistory(chatId){
  try{ const r=await fetch("/api/history?chatId="+encodeURIComponent(chatId),{headers:clientHeaders()}); const j=await r.json(); return j.messages||[]; }catch{ return []; }
}
function clientHeaders(){
  const cid=localStorage.getItem("ox_client_id")||"legacy";
  const tok=localStorage.getItem("ox_client_token")||"";
  const h={};
  if(cid!=="legacy") h["X-Client-Id"]=cid;
  if(tok) h["X-Client-Token"]=tok;
  return h;
}
function renderSidebar(chats){
  if(!sidebarChats) return;
  sidebarChats.innerHTML="";
  const groups={today:[],yesterday:[],older:[]};
  const now=Date.now();
  chats.forEach(c=>{
    const age=now-(c.updatedAt||0);
    if(age<86400000) groups.today.push(c);
    else if(age<172800000) groups.yesterday.push(c);
    else groups.older.push(c);
  });
  const order=[["Today",groups.today],["Yesterday",groups.yesterday],["Older",groups.older]];
  order.forEach(([label,arr])=>{
    if(!arr.length) return;
    const lab=document.createElement("div");
    lab.className="chat-group-label"; lab.textContent=label;
    sidebarChats.appendChild(lab);
    arr.forEach(ch=>{
      const el=document.createElement("div");
      el.className="chat-item"+(ch.id===activeChatId?" active":"");
      el.innerHTML=`<span class="chat-item-title">${escapeHtml(ch.title||"New chat")}</span><button class="chat-item-delete" title="Delete">×</button>`;
      el.addEventListener("click",e=>{
        if(e.target.closest(".chat-item-delete")) return;
        openChat(ch.id);
      });
      el.querySelector(".chat-item-delete").addEventListener("click",async e=>{
        e.stopPropagation();
        if(!confirm("Delete chat?")) return;
        await fetch("/api/chat-delete",{method:"POST",headers:{"Content-Type":"application/json",...clientHeaders()},body:JSON.stringify({chatId:ch.id})});
        if(activeChatId===ch.id){ activeChatId=null; clearMessages(); showEmpty(); }
        refreshChats();
      });
      sidebarChats.appendChild(el);
    });
  });
}
async function refreshChats(){
  const {chats,activeChatId:aid}=await fetchChats();
  if(!activeChatId && aid) activeChatId=aid;
  renderSidebar(chats);
}
function escapeHtml(s){ return String(s).replace(/[&<>"']/g,m=>({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[m])); }
function showEmpty(){ if(emptyState) emptyState.style.display=""; if(messagesWrap) messagesWrap.style.display="none"; if(inputArea) inputArea.style.display="none"; }
function showMessages(){ if(emptyState) emptyState.style.display="none"; if(messagesWrap) messagesWrap.style.display=""; if(inputArea) inputArea.style.display=""; }
function clearMessages(){ if(messagesCol) messagesCol.innerHTML=""; }
function scrollToBottom(){ const w=$(".messages-wrap"); if(w) w.scrollTop=w.scrollHeight; }
function addUserBubble(text, imgs, files){
  const wrap=document.createElement("div");
  wrap.className="msg msg-user";
  let media="";
  if(imgs && imgs.length) media+=`<div class="user-imgs">${imgs.map(im=>`<img src="${im.url}" alt="">`).join("")}</div>`;
  if(files && files.length) media+=`<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px">${files.map(f=>`<span style="background:var(--surface2);border:1px solid var(--border);padding:4px 8px;border-radius:999px;font-size:12px;display:inline-flex;align-items:center;gap:6px">${FILE_SVG} ${escapeHtml(f.name)}</span>`).join("")}</div>`;
  wrap.innerHTML=`<div class="msg-bubble">${media}${escapeHtml(text)}</div><button class="ox-edit-btn" title="Edit" aria-label="Edit"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4Z"/></svg></button>`;
  wrap.querySelector(".ox-edit-btn").addEventListener("click",()=>{
    const ta=document.createElement("textarea");
    ta.value=text; ta.style.width="100%"; ta.style.minHeight="60px"; ta.style.background="var(--surface)"; ta.style.color="var(--text)"; ta.style.border="1px solid var(--border2)"; ta.style.borderRadius="8px"; ta.style.padding="8px";
    const save=document.createElement("button"); save.textContent="Save & send"; save.style.background="#6e56cf"; save.style.color="#fff"; save.style.border="0"; save.style.padding="6px 10px"; save.style.borderRadius="999px"; save.style.cursor="pointer";
    const cancel=document.createElement("button"); cancel.textContent="Cancel"; cancel.style.background="transparent"; cancel.style.border="1px solid var(--border)"; cancel.style.padding="6px 10px"; cancel.style.borderRadius="999px"; cancel.style.cursor="pointer";
    const row=document.createElement("div"); row.style.display="flex"; row.style.gap="8px"; row.style.justifyContent="flex-end"; row.appendChild(cancel); row.appendChild(save);
    const box=document.createElement("div"); box.style.flex="1"; box.appendChild(ta); box.appendChild(row);
    wrap.innerHTML=""; wrap.appendChild(box); ta.focus();
    cancel.onclick=()=>{ wrap.innerHTML=`<div class="msg-bubble">${escapeHtml(text)}</div>`; };
    save.onclick=()=>{ const nv=ta.value.trim(); if(nv) { wrap.innerHTML=`<div class="msg-bubble">${escapeHtml(nv)}</div>`; sendMessage(nv,[],[]); }};
  });
  messagesCol.appendChild(wrap); scrollToBottom();
}
function addAssistantBubble(){
  const wrap=document.createElement("div");
  wrap.className="msg msg-assistant";
  wrap.innerHTML=`<div class="msg-bubble"><div class="prose"><span class="ox-thinking"><span class="ox-thinking-dot"></span><span class="ox-thinking-dot"></span><span class="ox-thinking-dot"></span><i class="ox-status">Thinking…</i></span></div><div class="msg-actions" style="display:none"><button class="msg-action-btn" data-act="copy">${COPY_SVG} Copy</button><span class="ox-sep"></span><button class="msg-action-btn" data-act="up" title="Good response">${UP_SVG}</button><button class="msg-action-btn" data-act="down" title="Bad response">${DOWN_SVG}</button><button class="msg-action-btn" data-act="retry" title="Regenerate">${RETRY_SVG}</button><button class="msg-action-btn" data-act="speak" title="Speak">${SPEAK_SVG}</button></div></div>`;
  messagesCol.appendChild(wrap);
  const prose=wrap.querySelector(".prose");
  const actions=wrap.querySelector(".msg-actions");
  let startAt=Date.now();
  let thinkingTimer=setInterval(()=>{
    const sec=Math.floor((Date.now()-startAt)/1000);
    const el=wrap.querySelector(".ox-status");
    if(el) el.textContent = sec>2 ? `Thinking… ${sec}s` : `Thinking…`;
  }, 400);
  function autoFormatFrontend(t){
    if(!t) return t;
    const lines=t.split("\n");
    let inF=false, out=[];
    const re=/^\s*(const |let |var |import |export |function |class |if\s*\(|for\s*\(|while\s*\(|return |def |from |print\(|console\.|.*=>|.*\b\w+\s*=\s*.+[;{]?\s*$|.*[;{}()]\s*$)/;
    for(let i=0;i<lines.length;i++){
      const raw=lines[i], tt=raw.trim();
      if(tt.startsWith("```")){ inF=!inF; out.push(raw); continue; }
      if(inF){ out.push(raw); continue; }
      if(tt && re.test(tt) && tt.length>4 && tt.length<300 && !/^[A-Z][a-z]+ [a-z]+/.test(tt)){
        let lang="js"; if(/^\s*(def |import |from |print\()/.test(tt)) lang="py";
        out.push("```"+lang); out.push(raw); out.push("```");
      } else out.push(raw);
    }
    return out.join("\n");
  }
  function setContent(text, isThinking){
    if(isThinking){
      prose.innerHTML=`<span class="ox-thinking"><span class="ox-thinking-dot"></span><span class="ox-thinking-dot"></span><span class="ox-thinking-dot"></span><i class="ox-status">${escapeHtml(text||"Thinking…")}</i></span>`;
      return;
    }
    clearInterval(thinkingTimer);
    text = autoFormatFrontend(text);
    let html=renderMarkdown(text||"");
    const tmp=document.createElement("div"); tmp.innerHTML=html;
    tmp.querySelectorAll("pre").forEach(pre=>{
      const code=pre.querySelector("code");
      const lang=(code && code.className.match(/language-([\w-]+)/)?.[1])||"code";
      const header=document.createElement("div"); header.className="code-block-header";
      header.innerHTML=`<span>${escapeHtml(lang)}</span><span style="display:flex;gap:6px"><button class="code-copy-btn" style="font-size:11px;padding:2px 6px;border-radius:999px;border:1px solid var(--border);background:var(--surface)">Copy</button><button class="code-dl-btn" style="font-size:11px;padding:2px 6px;border-radius:999px;border:1px solid var(--border);background:var(--surface)">Download</button></span>`;
      const block=document.createElement("div"); block.className="code-block"; block.appendChild(header); block.appendChild(pre.cloneNode(true));
      pre.replaceWith(block);
    });
    prose.innerHTML=tmp.innerHTML;
    if(sending) prose.innerHTML += '<span class="stream-cursor"></span>';
    highlightAll(prose);
    prose.querySelectorAll(".code-copy-btn").forEach(btn=>{
      btn.addEventListener("click",()=>{
        const pre=btn.closest(".code-block")?.querySelector("pre code");
        if(pre) navigator.clipboard.writeText(pre.textContent||"");
        btn.textContent="Copied!"; setTimeout(()=>btn.textContent="Copy",1200);
      });
    });
    prose.querySelectorAll(".code-dl-btn").forEach(btn=>{
      btn.addEventListener("click",()=>{
        const pre=btn.closest(".code-block")?.querySelector("pre code");
        const header=btn.closest(".code-block")?.querySelector(".code-block-header span")?.textContent||"code";
        const ext={js:"js",javascript:"js",py:"py",python:"py",html:"html",css:"css",json:"json"}[header]||"txt";
        const blob=new Blob([pre?.textContent||""],{type:"text/plain"}); const url=URL.createObjectURL(blob);
        const a=document.createElement("a"); a.href=url; a.download=`code-${Date.now()}.${ext}`; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
      });
    });
    actions.style.display="flex";
  }
  const FEED_KEY='ox_feedback';
  let fb={}; try{ fb=JSON.parse(localStorage.getItem(FEED_KEY)||'{}')||{}; }catch{}
  function hash(s){ let h=0; for(let i=0;i<s.length;i++) h=(h*31 + s.charCodeAt(i))|0; return 'm'+(h>>>0).toString(36); }
  function voteId(){ const prose=wrap.querySelector('.prose'); const h=hash((prose?prose.innerText:'').trim()); const idx=Array.from(document.querySelectorAll('.msg-assistant')).indexOf(wrap); return (activeChatId||'c')+':'+idx+':'+h; }
  function paintVotes(){ const id=voteId(); wrap.querySelector('[data-act="up"]')?.classList.toggle('active', fb[id]==='up'); wrap.querySelector('[data-act="down"]')?.classList.toggle('active', fb[id]==='down'); }
  function toggleVote(v){ const id=voteId(); if(fb[id]===v) delete fb[id]; else fb[id]=v; try{ localStorage.setItem(FEED_KEY, JSON.stringify(fb)); }catch{} paintVotes(); }
  wrap.querySelector('[data-act="copy"]')?.addEventListener("click",()=>{
    const txt=wrap.querySelector(".prose")?.innerText||"";
    navigator.clipboard.writeText(txt).then(()=>{ const b=wrap.querySelector('[data-act="copy"]'); const old=b.innerHTML; b.innerHTML=COPY_SVG+' Copied!'; b.classList.add('active'); setTimeout(()=>{ b.innerHTML=old; b.classList.remove('active'); },1200); });
  });
  wrap.querySelector('[data-act="up"]')?.addEventListener("click",()=>toggleVote('up'));
  wrap.querySelector('[data-act="down"]')?.addEventListener("click",()=>toggleVote('down'));
  wrap.querySelector('[data-act="retry"]')?.addEventListener("click",()=>{
    const lastUser=[...messagesCol.querySelectorAll(".msg-user")].pop();
    const txt=lastUser?.querySelector(".msg-bubble")?.innerText||"";
    if(txt) sendMessage(txt,[],[]);
  });
  wrap.querySelector('[data-act="speak"]')?.addEventListener("click",async()=>{
    const btn=wrap.querySelector('[data-act="speak"]');
    const txt=wrap.querySelector(".prose")?.innerText||"";
    if(!txt) return;
    if(btn.classList.contains('active')){ try{ speechSynthesis.cancel(); }catch{} btn.classList.remove('active'); return; }
    btn.classList.add('active');
    try{
      const r=await fetch("/api/tts?text="+encodeURIComponent(txt.slice(0,20000))+"&voice="+encodeURIComponent(getVoice()));
      if(!r.ok) throw new Error("tts "+r.status);
      const blob=await r.blob(); const url=URL.createObjectURL(blob);
      const a=new Audio(url); a.onended=()=>{ URL.revokeObjectURL(url); btn.classList.remove('active'); }; a.onerror=()=>btn.classList.remove('active'); await a.play();
    }catch{
      try{
        const u=new SpeechSynthesisUtterance(txt.slice(0,4000));
        u.onend=()=>btn.classList.remove('active'); u.onerror=()=>btn.classList.remove('active');
        speechSynthesis.speak(u);
      }catch{ btn.classList.remove('active'); }
    }
  });
  const _origSet=setContent;
  const wrappedSet=(text,isThinking)=>{ _origSet(text,isThinking); if(!isThinking) paintVotes(); };
  setContent=wrappedSet;
  return {wrap, setContent};
}
function updateSendState(){
  const boxes=$$(".empty-input-box, .input-box");
  let hasText=false;
  for(const box of boxes){
    if(box.offsetParent===null) continue;
    const ta=box.querySelector("textarea");
    if(ta && ta.value.trim().length>0) hasText=true;
  }
  const hasPending=pendingImages.length>0||pendingFiles.length>0;
  const btns=$$(".empty-input-box .send-btn, .input-box .send-btn");
  for(const b of btns){
    const box=b.closest(".empty-input-box, .input-box");
    const visible = box && box.offsetParent!==null;
    if(!visible) continue;
    b.disabled=!(hasText||hasPending)||sending;
  }
  // also handle empty case where no box visible yet (initial)
  if(!boxes.some(b=>b.offsetParent!==null)){
    const btn=document.querySelector(".send-btn");
    if(btn) btn.disabled=!(hasText||hasPending)||sending;
  }
}
function wireComposer(){
  const tas=$$(".empty-input-box textarea, .input-box textarea");
  tas.forEach(ta=>{
    if(ta.dataset.wired) return; ta.dataset.wired="1";
    ta.addEventListener("input",()=>{
      ta.style.height="auto"; ta.style.height=Math.min(ta.scrollHeight,160)+"px";
      updateSendState();
    });
    ta.addEventListener("keydown",e=>{
      if(e.key==="Enter"&&!e.shiftKey){ e.preventDefault(); const btn=ta.closest(".empty-input-box, .input-box")?.querySelector(".send-btn"); btn?.click(); }
    });
  });
  const btns=$$(".empty-input-box .send-btn, .input-box .send-btn");
  btns.forEach(btn=>{
    if(btn.dataset.wired) return; btn.dataset.wired="1";
    btn.addEventListener("click",()=>{
      const box=btn.closest(".empty-input-box, .input-box");
      const ta=box?.querySelector("textarea");
      const txt=ta?.value.trim()||"";
      if(!txt && pendingImages.length===0 && pendingFiles.length===0) return;
      const imgs=pendingImages.slice(); const files=pendingFiles.slice();
      pendingImages=[]; pendingFiles=[]; renderStrips();
      if(ta) { ta.value=""; ta.style.height="auto"; }
      updateSendState();
      sendMessage(txt,imgs,files);
    });
  });
  const stop=$(".stop-btn");
  if(stop && !stop.dataset.wired){ stop.dataset.wired="1"; stop.addEventListener("click",()=>{ abortCtrl?.abort(); stop.style.display="none"; }); }
  function downscaleImage(file, maxDim, quality){
    return new Promise((resolve)=>{
      const url=URL.createObjectURL(file);
      const img=new Image();
      img.onload=()=>{
        try{
          const w=img.naturalWidth||0, h=img.naturalHeight||0;
          URL.revokeObjectURL(url);
          if(!w || !h){ resolve(null); return; }
          const scale=Math.min(1, maxDim/Math.max(w,h));
          const cw=Math.max(1,Math.round(w*scale)), ch=Math.max(1,Math.round(h*scale));
          const cv=document.createElement("canvas"); cv.width=cw; cv.height=ch;
          const cx=cv.getContext("2d");
          cx.fillStyle="#0a0a0f"; cx.fillRect(0,0,cw,ch);
          cx.drawImage(img,0,0,cw,ch);
          const small = scale>=1 && file.size<=400*1024;
          if(small){
            const r=new FileReader();
            r.onload=()=>resolve(String(r.result||""));
            r.onerror=()=>resolve(null);
            r.readAsDataURL(file);
            return;
          }
          let out="";
          try{ out=cv.toDataURL("image/jpeg",quality); }catch{ out=""; }
          if(!out || out.length<100){
            const r2=new FileReader();
            r2.onload=()=>resolve(String(r2.result||""));
            r2.onerror=()=>resolve(null);
            r2.readAsDataURL(file);
            return;
          }
          resolve(out);
        }catch{ resolve(null); }
      };
      img.onerror=()=>{ URL.revokeObjectURL(url); resolve(null); };
      img.src=url;
    });
  }
  $$(".ox-attach input[type='file']").forEach(inp=>{
    if(inp.dataset.wired) return; inp.dataset.wired="1";
    inp.addEventListener("change",async e=>{
      const files=Array.from(e.target.files||[]);
      for(const f of files){
        if(/^image\//.test(f.type)){
          if(pendingImages.length>=MAX_IMAGES) continue;
          if(f.size>MAX_IMG_MB*1024*1024){ toast(`"${f.name}" too large (max ${MAX_IMG_MB}MB)`); continue; }
          const dataUrl=await downscaleImage(f,1280,0.82);
          if(!dataUrl){ toast(`Could not read "${f.name}"`); continue; }
          const base=f.name.replace(/\.[a-z0-9]+$/i,"")||"image";
          pendingImages.push({url:dataUrl,name:base+".jpg"});
        } else {
          if(pendingFiles.length>=MAX_FILES) continue;
          const text=await f.text().catch(()=>"");
          if(text.length>MAX_FILE_KB*1024) { toast(`"${f.name}" too large (max ${MAX_FILE_KB}KB)`); continue; }
          pendingFiles.push({name:f.name,size:f.size,text});
        }
      }
      renderStrips(); updateSendState(); e.target.value="";
    });
  });
  $$(".empty-chip").forEach(ch=>{
    if(ch.dataset.wired) return; ch.dataset.wired="1";
    ch.addEventListener("click",()=>{
      const ta=$(".empty-input-box textarea")||$(".input-box textarea");
      if(ta){ ta.value=ch.textContent.trim(); ta.dispatchEvent(new Event("input")); ta.focus(); }
    });
  });
  renderStrips();
}
function renderStrips(){
  $$(".empty-input-box, .input-box").forEach(box=>{
    let strip=box.querySelector(".ox-attach-strip");
    if(!pendingImages.length && !pendingFiles.length){ if(strip) strip.remove(); box.classList.remove("ox-has-strip"); return; }
    box.classList.add("ox-has-strip");
    if(!strip){ strip=document.createElement("div"); strip.className="ox-attach-strip"; box.insertBefore(strip, box.firstChild); }
    strip.innerHTML="";
    pendingImages.forEach((im,i)=>{
      const chip=document.createElement("div"); chip.className="ox-chip";
      chip.innerHTML=`<img src="${im.url}" alt=""><button>×</button>`;
      chip.querySelector("button").onclick=()=>{ pendingImages.splice(i,1); renderStrips(); updateSendState(); };
      strip.appendChild(chip);
    });
    pendingFiles.forEach((f,i)=>{
      const chip=document.createElement("div"); chip.className="ox-fchip";
      chip.innerHTML=`<span>${FILE_SVG}</span><span><b>${escapeHtml(f.name)}</b> <i>${Math.round(f.size/1024)}KB</i></span><button>×</button>`;
      chip.querySelector("button").onclick=()=>{ pendingFiles.splice(i,1); renderStrips(); updateSendState(); };
      strip.appendChild(chip);
    });
  });
}
function toast(msg){
  const t=byId("toast")||$(".ox-toast");
  if(!t) return;
  t.textContent=msg; t.classList.add("show");
  setTimeout(()=>t.classList.remove("show"),2200);
}
async function sendMessage(text, imgs, files){
  if(sending) return;
  showMessages();
  let prompt=text||"";
  if(!prompt && imgs.length) prompt="What do you see in this image?";
  if(!prompt && files.length) prompt="Review the attached file.";
  files.forEach(f=>{
    const ext=f.name.split(".").pop().toLowerCase();
    prompt+=`\n\n[Attached file: ${f.name}]\n\`\`\`${ext}\n${f.text}\n\`\`\``;
  });
  addUserBubble(prompt,imgs,files);
  sending=true; updateSendState();
  const stop=$(".stop-btn"); if(stop) stop.style.display="grid";
  const sendBtns=$$(".send-btn"); sendBtns.forEach(b=>b.disabled=true);
  if(!activeChatId){
    try{
      const r=await fetch("/api/new-chat",{method:"POST",headers:{"Content-Type":"application/json",...clientHeaders()}});
      const j=await r.json(); activeChatId=j.id||j.chatId||null;
    }catch{ activeChatId=null; }
    refreshChats();
  }
  const bubble=addAssistantBubble();
  let full="";
  let lastPaint=0;
  const paint=()=>{ lastPaint=Date.now(); bubble.setContent(full,false); scrollToBottom(); };
  abortCtrl=new AbortController();
  try{
    const body={message:prompt, chatId:activeChatId};
    if(imgs.length) body.images=imgs.map(im=>({name:im.name,dataUrl:im.url}));
    let res=await fetch("/api/chat",{method:"POST",headers:{"Content-Type":"application/json",...clientHeaders()},body:JSON.stringify(body),signal:abortCtrl.signal});
    if(res.status===404){
      activeChatId=null; refreshChats();
      const r2=await fetch("/api/new-chat",{method:"POST",headers:{"Content-Type":"application/json",...clientHeaders()}});
      try{ const j2=await r2.json(); activeChatId=j2.id||j2.chatId||null; }catch{}
      body.chatId=activeChatId;
      res=await fetch("/api/chat",{method:"POST",headers:{"Content-Type":"application/json",...clientHeaders()},body:JSON.stringify(body),signal:abortCtrl.signal});
    }
    if(!res.ok || !res.body){ const t=await res.text().catch(()=>res.statusText); throw new Error(t||"request failed"); }
    const reader=res.body.getReader(); const dec=new TextDecoder(); let buf="";
    while(true){
      const {value,done}=await reader.read(); if(done) break;
      buf+=dec.decode(value,{stream:true});
      let idx;
      while((idx=buf.indexOf("\n\n"))!==-1){
        const chunk=buf.slice(0,idx); buf=buf.slice(idx+2);
        if(!chunk.startsWith("data:")) continue;
        const data=chunk.slice(5).trim();
        if(!data) continue;
        try{
          const j=JSON.parse(data);
          if(j.type==="delta" && j.text){ full+=j.text; if(Date.now()-lastPaint>70) paint(); }
          else if(j.type==="reset"){ full=""; paint(); }
          else if(j.type==="done" && j.text){ full=j.text; paint(); }
          else if(j.type==="error"){ full="Error: "+(j.message||j.text||j.code); paint(); }
          else if(j.type==="status"){ bubble.setContent(j.text||"Waiting…",true); }
        }catch{}
      }
    }
    paint();
    if(!full) bubble.setContent("(no response)",false);
  }catch(e){
    if(e.name==="AbortError") bubble.setContent(full?full+"\\n\\n[stopped]":"[stopped]",false);
    else bubble.setContent("Error: "+(e.message||String(e)),false);
  }finally{
    sending=false; abortCtrl=null; if(stop) stop.style.display="none"; updateSendState(); refreshChats();
    if(voiceToggle?.checked || localStorage.getItem("ox_speak")==="1"){
      const txt=bubble.wrap.querySelector(".prose")?.innerText||full;
      if(txt) fetch("/api/tts?text="+encodeURIComponent(txt.slice(0,20000))+"&voice="+encodeURIComponent(getVoice())).then(r=>r.ok&&r.blob()).then(b=>{ if(!b) return; const url=URL.createObjectURL(b); const a=new Audio(url); a.play(); a.onended=()=>URL.revokeObjectURL(url); }).catch(()=>{});
    }
  }
}
async function openChat(chatId){
  activeChatId=chatId;
  clearMessages(); showMessages();
  const msgs=await fetchHistory(chatId);
  if(!msgs.length){ showEmpty(); return; }
  msgs.forEach(m=>{
    if(m.role==="user") addUserBubble(m.text,[],[]);
    else {
      const b=addAssistantBubble(); b.setContent(m.text,false);
    }
  });
  refreshChats();
}
function wireChrome(){
  document.addEventListener('click', async (e)=>{
    const nb = e.target.closest('.new-chat-btn');
    if(nb){
      e.preventDefault();
      activeChatId=null; clearMessages(); showEmpty();
      try{ const r=await fetch("/api/new-chat",{method:"POST",headers:{"Content-Type":"application/json",...clientHeaders()}}); const j=await r.json(); if(j && j.id) activeChatId=j.id; }catch{}
      refreshChats();
      setTimeout(()=>{ const ta=document.querySelector('.empty-input-box textarea, .input-box textarea'); if(ta) ta.focus(); },100);
    }
  });
  $(".mobile-burger")?.addEventListener("click",()=>{ $(".sidebar")?.classList.add("open"); $(".sidebar-overlay")?.classList.add("open"); });
  $(".sidebar-overlay")?.addEventListener("click",()=>{ $(".sidebar")?.classList.remove("open"); $(".sidebar-overlay")?.classList.remove("open"); });
  $(".ox-drawer-close")?.addEventListener("click",()=>{ $(".sidebar")?.classList.remove("open"); $(".sidebar-overlay")?.classList.remove("open"); });
  $(".settings-trigger")?.addEventListener("click",()=>{ if(settingsModal) settingsModal.style.display="grid"; loadSettings(); });
  $(".settings-modal-close")?.addEventListener("click",()=>{ if(settingsModal) settingsModal.style.display="none"; });
  settingsModal?.addEventListener("click",e=>{ if(e.target===settingsModal) settingsModal.style.display="none"; });
  $(".clear-btn")?.addEventListener("click",async()=>{
    if(!confirm("Clear all chats?")) return;
    const {chats}=await fetchChats();
    for(const ch of chats) await fetch("/api/chat-delete",{method:"POST",headers:{"Content-Type":"application/json",...clientHeaders()},body:JSON.stringify({chatId:ch.id})});
    activeChatId=null; clearMessages(); showEmpty(); refreshChats(); toast("Cleared");
  });
  document.documentElement.setAttribute("data-theme","dark");
  try{ localStorage.removeItem("ox_theme"); }catch{}
  document.addEventListener("pointermove",(e)=>{
    const t=e.target && e.target.closest ? e.target.closest(".empty-input-box,.input-box,.msg-bubble,.new-chat-btn,.chat-item,.code-block,.empty-chip") : null;
    if(!t) return;
    t.classList.add("spotlight");
    const r=t.getBoundingClientRect();
    t.style.setProperty("--mx",((e.clientX-r.left)/Math.max(1,r.width)*100)+"%");
    t.style.setProperty("--my",((e.clientY-r.top)/Math.max(1,r.height)*100)+"%");
  },{passive:true});
  byId("langSelect")?.addEventListener("change",e=>{ try{ localStorage.setItem("chattest_lang",e.target.value);}catch{} });
  if(voiceToggle){
    try{ voiceToggle.checked=localStorage.getItem("ox_speak")==="1"; }catch{}
    voiceToggle.addEventListener("change",()=>{ try{ localStorage.setItem("ox_speak",voiceToggle.checked?"1":"0"); }catch{} });
  }
  if(voiceSelect){
    try{ const v=localStorage.getItem("ox_voice"); if(v) voiceSelect.value=v; }catch{}
    voiceSelect.addEventListener("change",()=>{ try{ localStorage.setItem("ox_voice",voiceSelect.value); }catch{} });
  }
  byId("savePrompt")?.addEventListener("click",async()=>{
    const v=systemPromptEl?.value||"";
    await fetch("/api/settings",{method:"POST",headers:{"Content-Type":"application/json",...clientHeaders()},body:JSON.stringify({systemPrompt:v})});
    toast("Saved");
    if(settingsModal) settingsModal.style.display="none";
  });
  async function exportChat(fmt){
    if(!activeChatId){ toast("No chat to export"); return; }
    try{
      const r=await fetch(`/api/export?chatId=${encodeURIComponent(activeChatId)}&format=${fmt}`,{headers:{...clientHeaders()}});
      if(!r.ok) throw new Error("export failed");
      const blob=await r.blob();
      const url=URL.createObjectURL(blob);
      const a=document.createElement("a"); a.href=url; a.download=`chat-${activeChatId.slice(0,8)}.${fmt==="json"?"json":"md"}`; a.click();
      setTimeout(()=>URL.revokeObjectURL(url),2000);
      toast("Exported");
    }catch{ toast("Export failed"); }
  }
  byId("exportMd")?.addEventListener("click",()=>exportChat("md"));
  byId("exportJson")?.addEventListener("click",()=>exportChat("json"));
}
async function loadSettings(){
  try{
    const r=await fetch("/api/settings",{headers:clientHeaders()}); const j=await r.json();
    if(systemPromptEl){
      systemPromptEl.value = j.customPrompt || "";
      if(j.builtin) systemPromptEl.placeholder = j.builtin.slice(0,140) + "...  (add your custom instructions above — built-in Ox Alpha identity is always included)";
    }
  }catch{}
}
async function init(){
  if(!appState()) return;
  wireComposer(); wireChrome(); await refreshChats();
  const q=new URLSearchParams(location.search).get("q");
  if(q){ const ta=$(".empty-input-box textarea")||$(".input-box textarea"); if(ta){ ta.value=q; ta.dispatchEvent(new Event("input")); } }
  if(activeChatId) openChat(activeChatId);
  startPlaceholderTyping();
}
function startPlaceholderTyping(){
  const prompts=[
    "Refactor this 2,000-line module without changing its behavior…",
    "Why does this async function sometimes race…",
    "Summarize a 500-page spec and list the edge cases…",
    "Explain this traceback and propose a fix…",
    "Design a multi-step agent workflow with tool calls…",
    "Review my pull request like a senior engineer…",
    "Debug this production traceback…",
    "Optimize this SQL query for 10M rows…",
    "Convert this REST API to GraphQL…",
    "Write a comprehensive test suite for this class…",
    "Explain why this React component re-renders…",
    "Create a CI/CD pipeline for this repo…",
    "Migrate this codebase from JavaScript to TypeScript…",
    "Find the memory leak in this Node.js service…",
    "Design a rate limiter that handles 100k RPS…",
    "Explain this regex and simplify it…",
    "Generate OpenAPI spec from these endpoints…",
    "Fix this CSS Grid layout on Safari…",
    "Implement JWT auth with refresh tokens…",
    "Parse this 2GB CSV without loading it all…",
    "Make this Python function 10x faster…",
    "Explain the difference between process and thread…",
    "Design a chat app that scales to 1M users…",
    "Write a migration for this database schema…",
    "Debug why this Docker build is slow…",
    "Create a custom React hook for websockets…",
    "Explain how this blockchain consensus works…",
    "Optimize this image processing pipeline…",
    "Write a parser for this custom language…",
    "Fix this race condition in Go…",
    "Design a recommendation engine…",
    "Explain this Kubernetes deployment YAML…",
    "Convert this class component to hooks…",
    "Make this API idempotent…",
    "Write a load test for this endpoint…",
    "Explain why this query is slow…",
    "Create a design system from these mocks…",
    "Implement undo/redo for this editor…",
    "Fix this hydration mismatch in Next.js…",
    "Write a GitHub Action that deploys to S3…",
    "Explain this WebAssembly module…",
    "Design a file upload that resumes…",
    "Make this code handle 1M concurrent connections…",
    "Explain this machine learning model…",
    "Create a real-time collaboration feature…",
    "Fix this timezone bug…",
    "Write a cron job that never misses…",
    "Explain how this cache invalidation works…",
    "Design a search that handles typos…",
    "Make this mobile app offline-first…",
    "Explain this cryptography code…",
    "Create a dashboard with live charts…",
    "Fix this accessibility issue…",
    "Write a script that scrapes this site…",
    "Explain why this sort is unstable…",
    "Design a notification system…",
    "Make this function pure…",
    "Explain this event loop behavior…",
    "Create a plugin system…",
    "Fix this CORS error…",
    "Write a regex that validates emails…",
    "Explain this recursion…",
    "Design a queue that never loses messages…",
    "Make this UI 60fps…",
    "Explain this compiler error…",
    "Create a markdown editor…",
    "Fix this SQL injection…",
    "Write a rate limiter in Redis…",
    "Explain this distributed lock…",
    "Design a chat that supports threads…",
    "Make this test flaky test stable…",
    "Explain this Promise chain…",
    "Create a video streaming service…",
    "Fix this layout shift…",
    "Write a linter rule…",
    "Explain this garbage collection log…",
    "Design a payment flow…",
    "Make this code work in IE11…",
    "Explain this AST transformation…",
    "Create a code formatter…",
    "Fix this double-submit bug…",
    "Write a tokenizer…",
    "Explain this mutex deadlocks…",
    "Design a leaderboard…",
    "Make this API GraphQL…",
    "Explain this WebSocket reconnection…",
    "Create a file watcher…",
    "Fix this prototype pollution…",
    "Write a diff algorithm…",
    "Explain this JIT compilation…",
    "Design a dark mode…",
    "Make this app accessible…",
    "Explain this service worker…",
    "Create a drag-and-drop…",
    "Fix this flicker…",
    "Write a template engine…",
    "Explain this virtual DOM…",
    "Design a permissions system…",
    "Make this bundle smaller…",
    "Explain this HMR…",
    "Create a terminal emulator…",
    "Fix this z-index hell…",
    "Write a scheduler…",
    "Explain this CRDT…",
    "Design a real-time game…",
    "Make this function tail-recursive…",
    "Explain this borrow checker error…",
    "Create a syntax highlighter…",
    "Fix this FOUC…",
    "Write a build tool…",
    "Explain this tree shaking…",
    "Design a multi-tenant DB…",
    "Make this app work offline…",
    "Explain this hydration…",
    "Create a virtual scroller…",
    "Fix this content shift…",
    "Write a package manager…",
    "Explain this monad…",
    "Design a feature flag system…",
    "Make this code functional…",
    "Explain this effect system…",
    "Create a state machine…",
    "Fix this infinite loop…",
    "Write a type checker…",
    "Explain this variance…",
    "Design a CDN…",
    "Make this test faster…",
    "Explain this mocking…",
    "Create a test runner…",
    "Fix this brittle test…",
    "Write a fuzzer…",
    "Explain this property testing…",
    "Design a chaos test…",
    "Make this app resilient…",
    "Explain this circuit breaker…",
    "Create a retry logic…",
    "Fix this timeout…",
    "Write a debouncer…",
    "Explain this throttle…",
    "Design a cache…",
    "Make this memoization correct…",
    "Explain this weak ref…",
    "Create a pool…",
    "Fix this leak…",
    "Write a serializer…",
    "Explain this deserialization…",
    "Design a protocol…",
    "Make this RPC fast…",
    "Explain this gRPC…",
    "Create a streaming API…",
    "Fix this backpressure…",
    "Write a batcher…",
    "Explain this pagination…",
    "Design a cursor…",
    "Make this infinite scroll smooth…",
    "Explain this virtual list…",
    "Create a timeline…",
    "Fix this jank…",
    "Write a spring animation…",
    "Explain this easing…",
    "Design a gesture…",
    "Make this swipe work…",
    "Explain this intersection observer…",
    "Create a lazy loader…",
    "Fix this image flash…",
    "Write a placeholder…",
    "Explain this skeleton…",
    "Design a shimmer…",
    "Make this loading feel fast…",
    "Explain this suspense…",
    "Create a concurrent feature…",
    "Fix this waterfall…",
    "Write a data loader…",
    "Explain this N+1…",
    "Design a batch…",
    "Make this query fast…",
    "Explain this index…",
    "Create a full-text search…",
    "Fix this ranking…",
    "Write a stemmer…",
    "Explain this TF-IDF…",
    "Design a vector search…",
    "Make this RAG correct…",
    "Explain this embedding…",
    "Create a chatbot…",
    "Fix this hallucination…",
    "Write a guardrail…",
    "Explain this prompt injection…",
    "Design a safe system prompt…",
    "Make this alignment work…",
    "Explain this RLHF…",
    "Create a reward model…",
    "Fix this bias…",
    "Write a red team…",
    "Explain this jailbreak…",
    "Design a filter…",
    "Make this moderation fast…",
    "Explain this classifier…",
    "Create a detector…",
    "Fix this false positive…",
    "Write a feedback loop…",
    "Explain this A/B test…",
    "Design a metric…",
    "Make this dashboard real-time…",
    "Explain this anomaly detection…",
    "Create an alert…",
    "Fix this alert fatigue…",
    "Write an on-call playbook…",
    "Explain this incident…",
    "Design a postmortem…",
    "Make this blameless…",
    "Explain this SRE…",
    "Create a runbook…",
    "Fix this flaky deploy…"
  ];
  // shuffle for random each reload
  for(let i=prompts.length-1;i>0;i--){ const j=Math.floor(Math.random()*(i+1)); [prompts[i],prompts[j]]=[prompts[j],prompts[i]]; }
  let idx=0, pos=0, dir=1, timer=null;
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if(reduce) return;
  function tick(){
    const el=document.querySelector('.empty-input-box textarea');
    if(!el){ timer=setTimeout(tick,600); return; }
    if(el.value){ timer=setTimeout(tick,400); return; }
    const p=prompts[idx];
    if(dir>0){
      pos++;
      if(pos>=p.length){ el.placeholder=p; dir=-1; timer=setTimeout(tick,2000); return; }
      el.placeholder=p.slice(0,pos)+'\u258C';
      timer=setTimeout(tick, 26 + Math.random()*38);
    } else {
      pos-=2;
      if(pos<=0){ pos=0; dir=1; idx=(idx+1)%prompts.length; el.placeholder=''; timer=setTimeout(tick,380); return; }
      el.placeholder=p.slice(0,pos)+'\u258C';
      timer=setTimeout(tick,12);
    }
  }
  timer=setTimeout(tick,900);
}
document.addEventListener("DOMContentLoaded",init);
if(document.readyState!=="loading") init();
})();
