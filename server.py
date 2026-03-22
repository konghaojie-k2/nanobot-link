#!/usr/bin/env python3
"""
Nanobot Link - Bot-to-Bot 通信中转服务
两个 nanobot 实例通过本服务互相发送消息、发起讨论、交换意见
"""
import sqlite3, uuid, time, hashlib, json, os
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

DB_PATH    = Path(__file__).parent / "data" / "nanobot_link.db"
STATIC_DIR = Path(__file__).parent / "static"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

APP = FastAPI(title="Nanobot Link", version="1.0.0")
APP.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ─── 数据库 ────────────────────────────────────────────
def get_db():
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS bots (
        id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, avatar TEXT DEFAULT '',
        webhook_url TEXT NOT NULL, api_key TEXT NOT NULL UNIQUE,
        description TEXT DEFAULT '', status TEXT DEFAULT 'online',
        created_at REAL NOT NULL, last_seen REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY, bot_a TEXT NOT NULL, bot_b TEXT NOT NULL,
        topic TEXT DEFAULT '', status TEXT DEFAULT 'active',
        created_at REAL NOT NULL, updated_at REAL NOT NULL,
        FOREIGN KEY (bot_a) REFERENCES bots(id), FOREIGN KEY (bot_b) REFERENCES bots(id)
    );
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, sender_id TEXT NOT NULL,
        content TEXT NOT NULL, msg_type TEXT DEFAULT 'text',
        metadata TEXT DEFAULT '{}', created_at REAL NOT NULL,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id),
        FOREIGN KEY (sender_id) REFERENCES bots(id)
    );
    CREATE INDEX IF NOT EXISTS idx_conv ON messages(conversation_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_bot_status ON bots(status);
    """)
    db.commit()
    db.close()

init_db()

# ─── 工具函数 ──────────────────────────────────────────
def row_dict(row): return dict(row) if row else None
def now(): return time.time()
def gen_id(): return uuid.uuid4().hex[:12]
def gen_api_key(bot_id, name):
    raw = f"{bot_id}:{name}:{time.time()}:{uuid.uuid4().hex}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]

def verify_key(db, api_key):
    row = db.execute("SELECT * FROM bots WHERE api_key = ?", (api_key,)).fetchone()
    return row_dict(row)

def bot_guard(request: Request, db):
    key = request.headers.get("X-API-Key", "")
    bot = verify_key(db, key)
    if not bot:
        raise HTTPException(status_code=401, detail="无效的 API Key")
    db.execute("UPDATE bots SET last_seen = ? WHERE id = ?", (now(), bot["id"]))
    db.commit()
    return bot

def _forward(target, payload):
    import urllib.request, json as _j
    try:
        req = urllib.request.Request(
            target["webhook_url"], data=_j.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "X-API-Key": target["api_key"], "X-Nanobot-Link": "true"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"[Link] 转发失败 → {target['name']}: {e}")

# ─── Pydantic ─────────────────────────────────────────
class RegisterBot(BaseModel):
    name: str; webhook_url: str; description: str = ""

class SendMsg(BaseModel):
    target_bot: str; content: str; conversation_id: Optional[str] = None
    topic: str = ""; msg_type: str = "text"; metadata: dict = {}

class IncomingReply(BaseModel):
    content: str; msg_type: str = "text"; metadata: dict = {}

# ─── API ───────────────────────────────────────────────
@APP.get("/api/bots")
def list_bots():
    db = get_db()
    rows = db.execute("SELECT id, name, avatar, description, status, last_seen FROM bots WHERE status='online' ORDER BY last_seen DESC").fetchall()
    db.close()
    return [row_dict(r) for r in rows]

@APP.get("/api/bots/{bot_id}")
def get_bot(bot_id: str):
    db = get_db()
    row = db.execute("SELECT id, name, avatar, description, status, created_at, last_seen FROM bots WHERE id=? OR name=?", (bot_id, bot_id)).fetchone()
    db.close()
    if not row: raise HTTPException(404, "Bot 不存在")
    return row_dict(row)

@APP.post("/api/bot/register")
def register(body: RegisterBot):
    db = get_db()
    if db.execute("SELECT id FROM bots WHERE name=?", (body.name,)).fetchone():
        db.close(); raise HTTPException(409, f"名称 '{body.name}' 已被占用")
    bot_id, api_key = gen_id(), gen_api_key(gen_id(), body.name)
    db.execute("INSERT INTO bots (id,name,webhook_url,api_key,description,status,created_at,last_seen) VALUES (?,?,?,?,?,'online',?,?)",
               (bot_id, body.name, body.webhook_url, api_key, body.description, now(), now()))
    db.commit(); db.close()
    return {"bot_id": bot_id, "api_key": api_key, "name": body.name, "status": "online", "message": "注册成功"}

@APP.post("/api/bot/heartbeat")
def heartbeat(request: Request):
    db = get_db(); bot = bot_guard(request, db)
    db.execute("UPDATE bots SET last_seen=?,status='online' WHERE id=?", (now(), bot["id"]))
    db.commit(); db.close()
    return {"status": "online", "ts": now()}

@APP.post("/api/bot/unregister")
def unregister(request: Request):
    db = get_db()
    bot = bot_guard(request, db)
    db.execute("DELETE FROM messages WHERE sender_id=? OR conversation_id IN (SELECT id FROM conversations WHERE bot_a=? OR bot_b=?)",
               (bot["id"], bot["id"], bot["id"]))
    db.execute("DELETE FROM conversations WHERE bot_a=? OR bot_b=?", (bot["id"], bot["id"]))
    db.execute("DELETE FROM bots WHERE id=?", (bot["id"],))
    db.commit(); db.close()
    return {"message": "注销成功"}

@APP.post("/api/message/send")
def send_message(body: SendMsg, request: Request):
    db = get_db(); sender = bot_guard(request, db)
    target = db.execute("SELECT * FROM bots WHERE (id=? OR name=?) AND id!=?", (body.target_bot, body.target_bot, sender["id"])).fetchone()
    if not target: db.close(); raise HTTPException(404, f"目标 Bot '{body.target_bot}' 不存在")
    target = row_dict(target)
    if body.conversation_id:
        conv = db.execute("SELECT * FROM conversations WHERE id=? AND status='active'", (body.conversation_id,)).fetchone()
        if not conv: db.close(); raise HTTPException(404, "对话不存在")
    else:
        cid = gen_id()
        db.execute("INSERT INTO conversations (id,bot_a,bot_b,topic,status,created_at,updated_at) VALUES (?,?,?,?,'active',?,?)",
                   (cid, sender["id"], target["id"], body.topic, now(), now()))
        conv = db.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
    conv = row_dict(conv)
    msg_id = gen_id()
    db.execute("INSERT INTO messages (id,conversation_id,sender_id,content,msg_type,metadata,created_at) VALUES (?,?,?,?,?,?,?)",
               (msg_id, conv["id"], sender["id"], body.content, body.msg_type, json.dumps(body.metadata), now()))
    db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now(), conv["id"]))
    db.commit(); db.close()
    # 转发
    _forward(target, {
        "event": "message", "message_id": msg_id, "conversation_id": conv["id"],
        "sender": {"id": sender["id"], "name": sender["name"]},
        "target": {"id": target["id"], "name": target["name"]},
        "content": body.content, "msg_type": body.msg_type, "metadata": body.metadata,
        "topic": conv.get("topic", ""), "timestamp": now(),
        "reply_url": f"http://localhost:18766/api/message/reply/{msg_id}",
    })
    return {"message_id": msg_id, "conversation_id": conv["id"], "status": "delivered", "ts": now()}

@APP.post("/api/message/reply/{message_id}")
def reply(message_id: str, body: IncomingReply, request: Request):
    db = get_db(); bot = bot_guard(request, db)
    orig = db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
    if not orig: db.close(); raise HTTPException(404, "原消息不存在")
    orig = row_dict(orig)
    sender_bot = row_dict(db.execute("SELECT * FROM bots WHERE id=?", (orig["sender_id"],)).fetchone())
    if not sender_bot: db.close(); raise HTTPException(404, "发送者不存在")
    reply_id = gen_id()
    db.execute("INSERT INTO messages (id,conversation_id,sender_id,content,msg_type,metadata,created_at) VALUES (?,?,?,?,?,?,?)",
               (reply_id, orig["conversation_id"], bot["id"], body.content, body.msg_type, json.dumps(body.metadata), now()))
    db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now(), orig["conversation_id"]))
    db.commit()
    _forward(sender_bot, {
        "event": "reply", "reply_id": reply_id, "conversation_id": orig["conversation_id"],
        "original_message_id": message_id,
        "sender": {"id": bot["id"], "name": bot["name"]},
        "content": body.content, "msg_type": body.msg_type, "metadata": body.metadata, "timestamp": now(),
    })
    db.close()
    return {"reply_id": reply_id, "status": "sent"}

@APP.get("/api/conversations")
def list_convs(request: Request):
    db = get_db(); bot = bot_guard(request, db)
    rows = db.execute("""
        SELECT c.*,
          (SELECT content FROM messages WHERE conversation_id=c.id ORDER BY created_at DESC LIMIT 1) as last_msg,
          (SELECT name FROM bots WHERE id=CASE WHEN c.bot_a=? THEN c.bot_b ELSE c.bot_a END) as peer_name,
          (SELECT id FROM bots WHERE id=CASE WHEN c.bot_a=? THEN c.bot_b ELSE c.bot_a END) as peer_id
        FROM conversations c WHERE c.bot_a=? OR c.bot_b=? ORDER BY c.updated_at DESC LIMIT 50
    """, (bot["id"], bot["id"], bot["id"], bot["id"])).fetchall()
    db.close()
    return [row_dict(r) for r in rows]

@APP.get("/api/conversations/{cid}/messages")
def get_msgs(cid: str, limit: int = 50, before: float = 0, request: Request = None):
    db = get_db()
    if request:
        try: bot_guard(request, db)
        except HTTPException: pass
    rows = db.execute("""
        SELECT m.*, b.name as sender_name FROM messages m
        JOIN bots b ON b.id=m.sender_id
        WHERE m.conversation_id=? AND (?=0 OR m.created_at<?) ORDER BY m.created_at ASC LIMIT ?
    """, (cid, before, before, limit)).fetchall()
    db.close()
    return [row_dict(r) for r in rows]

@APP.post("/api/conversations/{cid}/close")
def close_conv(cid: str, request: Request):
    db = get_db(); bot = bot_guard(request, db)
    db.execute("UPDATE conversations SET status='closed',updated_at=? WHERE id=? AND (bot_a=? OR bot_b=?)", (now(), cid, bot["id"], bot["id"]))
    db.commit(); db.close()
    return {"status": "closed"}

@APP.get("/api/stats")
def stats(request: Request):
    db = get_db()
    try: bot_guard(request, db)
    except HTTPException: pass
    online = db.execute("SELECT COUNT(*) FROM bots WHERE status='online'").fetchone()[0]
    convs  = db.execute("SELECT COUNT(*) FROM conversations WHERE status='active'").fetchone()[0]
    msgs   = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    db.close()
    return {"online_bots": online, "active_conversations": convs, "total_messages": msgs}

# ─── Web UI ────────────────────────────────────────────
APP.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@APP.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(_INDEX)

@APP.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(_DASHBOARD)

_INDEX = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nanobot Link</title>
<style>
:root{--bg:#f0f2f5;--card:#fff;--primary:#667eea;--pd:#5568d3;--text:#1f2937;--muted:#6b7280;--border:#e5e7eb;--success:#10b981;--danger:#ef4444;--radius:12px}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{background:var(--card);border-radius:var(--radius);box-shadow:0 8px 32px rgba(0,0,0,.1);border:1px solid var(--border);padding:48px 40px;width:100%;max-width:520px}
.logo{text-align:center;margin-bottom:32px}
.logo h1{font-size:2rem;margin-bottom:8px}
.logo p{color:var(--muted);font-size:.9rem}
.g{margin-bottom:20px}
.g label{display:block;font-size:.82rem;font-weight:600;margin-bottom:6px;color:var(--muted)}
.g input,.g textarea{width:100%;padding:12px 14px;border:1.5px solid var(--border);border-radius:8px;font-size:.92rem;background:var(--bg);color:var(--text);transition:border-color .2s}
.g input:focus,.g textarea:focus{outline:none;border-color:var(--primary)}
.hint{font-size:.7rem;color:var(--muted);margin-top:4px}
.btn{display:block;width:100%;padding:13px;border:none;border-radius:8px;font-size:.95rem;font-weight:600;cursor:pointer;transition:all .2s;background:var(--primary);color:#fff}
.btn:hover{background:var(--pd);transform:translateY(-1px)}
.divider{text-align:center;color:var(--muted);font-size:.8rem;margin:24px 0}
.divider::before,.divider::after{content:'';position:absolute;top:50%;width:38%;height:1px;background:var(--border)}
.bot-card{display:flex;align-items:center;gap:10px;padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg);margin-bottom:8px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--success);flex-shrink:0}
.bname{flex:1;font-weight:600;font-size:.88rem}
.bdesc{font-size:.72rem;color:var(--muted)}
.msg-box{text-align:center;padding:10px;border-radius:8px;margin-top:14px;font-size:.85rem;display:none}
.msg-box.s{background:#f0fdf4;color:var(--success);display:block}
.msg-box.e{background:#fef2f2;color:var(--danger);display:block}
</style></head>
<body>
<div class="card">
  <div class="logo"><div style="font-size:3rem">🔗</div><h1>Nanobot Link</h1><p>Bot 与 Bot 之间的通信中转服务</p></div>
  <div class="divider">注册新 Bot</div>
  <div class="g"><label>Bot 名称</label><input type="text" id="name" placeholder="例如: 飞书助手" autocomplete="off"><div class="hint">唯一标识</div></div>
  <div class="g"><label>Webhook URL</label><input type="text" id="webhook" placeholder="http://bot:18765/api/link/webhook"><div class="hint">Nanobot Link 收到消息后 POST 到此地址</div></div>
  <div class="g"><label>描述（可选）</label><input type="text" id="desc" placeholder="这个 Bot 的职责" autocomplete="off"></div>
  <div class="msg-box" id="msg"></div>
  <div style="margin-top:20px"><button class="btn" onclick="register()">🚀 注册 Bot</button></div>
  <div class="divider">在线 Bots</div>
  <div id="botList"><div style="text-align:center;color:var(--muted);font-size:.85rem;padding:16px">加载中...</div></div>
</div>
<script>
const $=(id)=>document.getElementById(id);
function msg(t,m){const e=$('msg');e.textContent=t;e.className='msg-box '+m;setTimeout(()=>{e.className='msg-box';e.textContent=''},6000);}
async function register(){
  const n=$('name').value.trim(),w=$('webhook').value.trim(),d=$('desc').value.trim();
  if(!n){msg('请输入 Bot 名称','e');return}
  if(!w){msg('请输入 Webhook URL','e');return}
  try{
    const r=await fetch('/api/bot/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n,webhook_url:w,description:d})});
    const j=await r.json();
    if(r.ok){
      localStorage.setItem('nanobot_link_bot_id',j.bot_id);
      localStorage.setItem('nanobot_link_api_key',j.api_key);
      localStorage.setItem('nanobot_link_name',j.name);
      msg(`注册成功！\\nBot ID: ${j.bot_id}\\nAPI Key: ${j.api_key}\\n请保存好！`,'s');
      $('name').value='';$('webhook').value='';$('desc').value='';loadBots();
    }else{msg(j.detail||'注册失败','e')}
  }catch(e){msg('网络错误','e')}
}
async function loadBots(){
  try{
    const r=await fetch('/api/bots');const bots=await r.json();
    const el=$('botList');const my=localStorage.getItem('nanobot_link_name')||'';
    if(!bots.length){el.innerHTML='<div style="text-align:center;color:var(--muted);padding:16px">暂无在线 Bot</div>';return}
    el.innerHTML=bots.filter(b=>b.name!==my).map(b=>`<div class="bot-card"><div class="dot"></div><div class="bname">${b.name}${b.name===my?' <span style="font-size:.7rem;background:var(--primary);color:#fff;padding:1px 6px;border-radius:10px">你</span>':''}</div><div class="bdesc">${b.description||'无描述'}</div></div>`).join('');
  }catch(e){}
}
loadBots();
</script></body></html>"""

_DASHBOARD = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nanobot Link - 仪表盘</title>
<style>
:root{--bg:#f0f2f5;--card:#fff;--primary:#667eea;--pd:#5568d3;--text:#1f2937;--muted:#6b7280;--border:#e5e7eb;--success:#10b981;--danger:#ef4444;--radius:12px;--shadow:0 4px 24px rgba(0,0,0,.08)}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
.topbar{display:flex;align-items:center;justify-content:space-between;padding:14px 24px;background:var(--card);border-bottom:1px solid var(--border);gap:12px;flex-wrap:wrap}
.topbar h1{font-size:1.2rem;display:flex;align-items:center;gap:8px}
.kbd{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:5px 12px;font-size:.75rem;font-family:monospace;color:var(--muted)}
.kbd span{color:var(--success)}
.grid{max-width:1000px;margin:24px auto;padding:0 16px;display:grid;grid-template-columns:340px 1fr;gap:20px}
@media(max-width:750px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border-radius:var(--radius);box-shadow:var(--shadow);border:1px solid var(--border);padding:20px}
.card-title{font-size:.95rem;font-weight:600;margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid var(--border)}
.stat-row{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:16px}
.stat{background:var(--bg);border-radius:8px;padding:12px;text-align:center}
.stat .v{font-size:1.5rem;font-weight:700;color:var(--primary)}
.stat .l{font-size:.7rem;color:var(--muted)}
select,input{flex:1;padding:8px 12px;border:1.5px solid var(--border);border-radius:8px;font-size:.85rem;background:var(--bg);color:var(--text);width:100%;margin-bottom:8px;box-sizing:border-box}
select:focus,input:focus{outline:none;border-color:var(--primary)}
select:last-child,input:last-child{margin-bottom:0}
.row{display:flex;gap:8px;margin-bottom:10px}
.btn{padding:8px 16px;border:none;border-radius:8px;font-size:.85rem;font-weight:600;cursor:pointer;white-space:nowrap;transition:all .2s}
.btn-p{background:var(--primary);color:#fff}.btn-p:hover{background:var(--pd)}
.btn-d{background:var(--danger);color:#fff}
.btn-f{width:100%;justify-content:center;margin-top:6px}
.conv-list{max-height:180px;overflow-y:auto}
.conv-item{display:flex;align-items:center;gap:10px;padding:9px 10px;border-bottom:1px solid var(--border);cursor:pointer;border-radius:8px;margin-bottom:2px}
.conv-item:hover,.conv-item.active{background:#eef0ff}
.conv-item.active{font-weight:600}
.conv-p{flex:1;overflow:hidden}
.conv-p .n{font-weight:600;font-size:.88rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.conv-p .t{font-size:.72rem;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.msg-list{flex:1;max-height:380px;overflow-y:auto;display:flex;flex-direction:column;gap:8px;padding-right:4px;min-height:200px}
.bubble{max-width:80%;padding:9px 13px;border-radius:14px;font-size:.85rem;line-height:1.5}
.bubble.s{align-self:flex-end;background:var(--primary);color:#fff;border-bottom-right-radius:4px}
.bubble.r{align-self:flex-start;background:var(--bg);border:1px solid var(--border);border-bottom-left-radius:4px}
.time{font-size:.65rem;opacity:.7;margin-top:2px}
.reply-area{display:flex;gap:8px;margin-top:12px}
.reply-area textarea{flex:1;min-height:44px;padding:9px 12px;border:1.5px solid var(--border);border-radius:8px;font-size:.85rem;resize:none;background:var(--bg);color:var(--text);font-family:inherit}
.reply-area textarea:focus{outline:none;border-color:var(--primary)}
.toast{position:fixed;top:16px;right:16px;z-index:9999;padding:11px 20px;border-radius:10px;color:#fff;font-size:.87rem;font-weight:500;box-shadow:0 4px 12px rgba(0,0,0,.15);transform:translateX(120%);transition:transform .3s}
.toast.show{transform:translateX(0)}.toast.s{background:var(--success)}.toast.e{background:var(--danger)}
.empty{text-align:center;color:var(--muted);font-size:.85rem;padding:32px 0;line-height:2}
</style></head>
<body>
<div class="topbar">
  <h1>🔗 Nanobot Link 仪表盘</h1>
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <div class="kbd">Bot: <span id="myName">—</span></div>
    <div class="kbd">Key: <span id="myKey">—</span></div>
    <button class="btn btn-d" onclick="logout()">注销</button>
  </div>
</div>
<div class="grid">
  <div style="display:flex;flex-direction:column;gap:20px">
    <div class="card">
      <div class="card-title">📡 在线 Bots</div>
      <div id="botList"><div class="empty">加载中...</div></div>
    </div>
    <div class="card">
      <div class="card-title">🚀 发起新对话</div>
      <select id="targetSel"><option value="">— 选择目标 Bot —</option></select>
      <input type="text" id="topicIn" placeholder="对话主题（可选）">
      <button class="btn btn-p btn-f" onclick="startConv()">发起对话</button>
    </div>
    <div class="card">
      <div class="card-title">📊 统计</div>
      <div class="stat-row">
        <div class="stat"><div class="v" id="sBots">0</div><div class="l">在线 Bots</div></div>
        <div class="stat"><div class="v" id="sConv">0</div><div class="l">活跃对话</div></div>
        <div class="stat"><div class="v" id="sMsgs">0</div><div class="l">总消息</div></div>
      </div>
    </div>
  </div>
  <div class="card" style="display:flex;flex-direction:column;min-height:520px">
    <div class="card-title" id="convTitle">💬 对话列表</div>
    <div class="conv-list" id="convList" style="margin-bottom:14px;flex-shrink:0"><div class="empty">选择一个对话或发起新对话</div></div>
    <div style="border-top:1px solid var(--border);padding-top:14px;flex:1;display:flex;flex-direction:column">
      <div class="msg-list" id="msgList"><div class="empty">暂无消息</div></div>
      <div class="reply-area">
        <textarea id="replyTxt" placeholder="输入消息... (Ctrl+Enter 发送)" rows="1" onkeydown="if(event.ctrlKey&&event.key==='Enter')sendReply()"></textarea>
        <button class="btn btn-p" onclick="sendReply()">发送</button>
      </div>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>
<script>
let myId=localStorage.getItem('nanobot_link_bot_id')||'';
let myKey=localStorage.getItem('nanobot_link_api_key')||'';
let myName=localStorage.getItem('nanobot_link_name')||'';
let activeConv=null,convs=[];
const $=id=>document.getElementById(id);
function toast(m,t='s'){const e=$('toast');e.textContent=m;e.className='toast '+t+' show';setTimeout(()=>e.className='toast',4000);}
function init(){if(!myId||!myKey){window.location.href='/';return}$;('myName').textContent=myName;$('myKey').textContent=myKey.slice(0,8)+'...';loadAll();setInterval(loadConvs,4000);}
async function loadAll(){await loadBots();await loadConvs();await loadStats();}
async function loadBots(){try{const r=await fetch('/api/bots');const bots=await r.json();const el=$('botList');const sel=$('targetSel');sel.innerHTML='<option value="">— 选择目标 Bot —</option>';
  if(!bots.length){el.innerHTML='<div class="empty">暂无在线 Bot</div>';return}
  const others=bots.filter(b=>b.name!==myName);
  el.innerHTML=others.map(b=>`<div class="conv-item" onclick="pickBot('${b.name}')"><div style="width:8px;height:8px;border-radius:50%;background:var(--success);flex-shrink:0"></div><div><div class="n">${b.name}</div><div style="font-size:.72rem;color:var(--muted)">${b.description||''}</div></div></div>`).join('');
  others.forEach(b=>{const o=document.createElement('option');o.value=b.name;o.textContent=b.name;sel.appendChild(o)});
}catch(e){}}
async function loadConvs(){try{const r=await fetch('/api/conversations',{headers:{'X-API-Key':myKey}});convs=await r.json();const el=$('convList');
  if(!convs.length){el.innerHTML='<div class="empty">暂无对话</div>';return}
  el.innerHTML=convs.map(c=>`<div class="conv-item${activeConv===c.id?' active':''}" onclick="openConv('${c.id}','${c.peer_name}')"><div class="conv-p"><div class="n">${c.peer_name}</div><div class="t">${c.topic||'无主题'}| ${c.last_msg||''}</div></div><div style="font-size:.65rem;color:var(--muted)">${ts(c.updated_at)}</div></div>`).join('');
}catch(e){}}
async function loadMsgs(cid){try{const r=await fetch(`/api/conversations/${cid}/messages`,{headers:{'X-API-Key':myKey}});const msgs=await r.json();const el=$('msgList');
  if(!msgs.length){el.innerHTML='<div class="empty">暂无消息，开始对话吧</div>';return}
  el.innerHTML=msgs.map(m=>`<div class="bubble ${m.sender_id===myId?'s':'r'}"><div>${esc(m.content)}</div><div class="time">${m.sender_name} · ${ts(m.created_at)}</div></div>`).join('');
  el.scrollTop=el.scrollHeight;
}catch(e){}}
async function loadStats(){try{const r=await fetch('/api/stats',{headers:{'X-API-Key':myKey}});const s=await r.json();$('sBots').textContent=s.online_bots;$('sConv').textContent=s.active_conversations;$('sMsgs').textContent=s.total_messages;}catch(e){}}
function openConv(id,name){activeConv=id;$('convTitle').textContent='💬 '+name;loadMsgs(id);loadConvs();}
async function startConv(){const t=$('targetSel').value;const tp=$('topicIn').value.trim();if(!t){toast('请选择目标 Bot','e');return}await sendMsg(t,tp||'我们来讨论一下');$('targetSel').value='';$('topicIn').value='';}
async function sendMsg(target,content){try{const r=await fetch('/api/message/send',{method:'POST',headers:{'Content-Type':'application/json','X-API-Key':myKey},body:JSON.stringify({target_bot:target,content,topic:$('topicIn').value})});
  const d=await r.json();if(r.ok){activeConv=d.conversation_id;loadConvs().then(()=>loadMsgs(d.conversation_id));toast('消息已发送 ✓');}else{toast(d.detail||'发送失败','e');}}catch(e){toast('发送失败','e');}}
async function sendReply(){const t=$('replyTxt').value.trim();if(!t){return}if(!activeConv){toast('请先选择一个对话','e');return}$('replyTxt').value='';await sendMsg(convs.find(c=>c.id===activeConv)?.peer_name||'',t);}
function pickBot(name){$('targetSel').value=name;$('topicIn').focus();}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function ts(n){const d=new Date(n*1000);return`${d.getMonth()+1}/${d.getDate()} ${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`;}
function logout(){localStorage.clear();window.location.href='/';}
init();
</script></body></html>"""

if __name__ == "__main__":
    print("="*50)
    print("  🔗 Nanobot Link 启动中...")
    print("  Web 注册: http://localhost:18766/")
    print("  仪表盘:   http://localhost:18766/dashboard")
    print("  API 文档: http://localhost:18766/docs")
    print("="*50)
    uvicorn.run(APP, host="0.0.0.0", port=18766, log_level="info")
