#!/usr/bin/env python3
"""
Nanobot Link 简单示例
演示如何让两个 Bot 进行通信

运行方式:
    python demo_simple.py

这个示例模拟两个 Bot：
    - Bot A: "专家助手" (负责分析)
    - Bot B: "调度助手" (负责调度)
"""
import json
import time
import threading
import re
from pathlib import Path

# ─── 模拟 Bot ────────────────────────────────────────────

class MockBot:
    """
    模拟一个 Nanobot 实例
    - register(): 注册到 Link 服务
    - send(): 发送消息
    - process_incoming(): 处理收到的消息
    """

    def __init__(self, name: str, personality: str, link_url: str = "http://localhost:18766"):
        self.name       = name
        self.personality = personality
        self.link_url  = link_url
        self.bot_id     = None
        self.api_key    = None
        self.conversations: list[dict] = []
        self.inbox: list[dict] = []   # 收到的消息
        self.reply_callback = None   # 收到消息时的回调

    # ─── 工具函数 ────────────────────────────────────────
    def _req(self, method: str, path: str, json_data=None, headers=None):
        import urllib.request
        url  = f"{self.link_url}{path}"
        hdrs = {"Content-Type": "application/json"}
        if headers: hdrs.update(headers)
        body = json.dumps(json_data).encode() if json_data else None
        req  = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    # ─── 注册 ────────────────────────────────────────────
    def register(self) -> dict:
        print(f"[{self.name}] 正在注册...")
        r = self._req("POST", "/api/bot/register", {
            "name":        self.name,
            "webhook_url": f"http://localhost:0/mock",  # mock 模式不需要真实 webhook
            "description":  self.personality,
        })
        self.bot_id  = r["bot_id"]
        self.api_key = r["api_key"]
        print(f"[{self.name}] ✅ 注册成功! bot_id={self.bot_id}")
        return r

    # ─── 发送消息 ────────────────────────────────────────
    def send(self, target_bot: str, content: str, topic: str = "") -> dict:
        print(f"[{self.name}] ➡️  发送消息 → {target_bot}: {content[:50]}...")
        r = self._req("POST", "/api/message/send", {
            "target_bot": target_bot,
            "content":     content,
            "topic":      topic,
        }, headers={"X-API-Key": self.api_key})
        print(f"[{self.name}] ✅ 消息已发送! conv_id={r['conversation_id']}")
        return r

    # ─── 接收消息（轮询方式） ─────────────────────────────
    def poll_messages(self, conversation_id: str, timeout: int = 30) -> list[dict]:
        """轮询获取新消息"""
        start = time.time()
        last_count = 0
        while time.time() - start < timeout:
            r = self._req("GET", f"/api/conversations/{conversation_id}/messages")
            if len(r) > last_count:
                new_msgs = r[last_count:]
                for m in new_msgs:
                    if m["sender_id"] != self.bot_id:  # 排除自己发的
                        self.inbox.append(m)
                        print(f"[{self.name}] 📩 收到消息 from {m.get('sender_name','?')}: {m['content'][:60]}...")
                        if self.reply_callback:
                            self.reply_callback(self, m)
                last_count = len(r)
            time.sleep(1)
        return self.inbox

    # ─── 处理收到的消息 ─────────────────────────────────
    def think(self, incoming_msg: str, sender: str) -> str:
        """
        模拟 AI 思考过程
        实际使用时，这里会被 nanobot 的 AI 替换
        """
        prompt = f"你是'{self.name}'，性格是'{self.personality}'。\n收到了来自'{sender}'的消息：{incoming_msg}\n请用一句话回复："
        # 这里用简单的规则模拟，实际接 nanobot 时用真正的 AI
        if "分析" in incoming_msg or "需求" in incoming_msg:
            return "我认为可以从技术可行性、业务价值、风险三个维度来分析这个需求。"
        elif "讨论" in incoming_msg or "你觉得" in incoming_msg:
            return "我同意你的看法，我再补充一点..."
        elif "总结" in incoming_msg:
            return "好的，我来总结一下今天的讨论要点..."
        else:
            return "收到，我再想想..."

    def reply_to(self, conversation_id: str, original_msg_id: str, content: str):
        """回复消息"""
        print(f"[{self.name}] ⬅️  回复: {content[:50]}...")
        self._req("POST", f"/api/message/reply/{original_msg_id}", {
            "content": content,
        }, headers={"X-API-Key": self.api_key})


def reply_handler(bot: MockBot, msg: dict):
    """当收到消息时，自动思考并回复"""
    reply_text = bot.think(msg["content"], msg.get("sender_name", "?"))
    bot.reply_to(msg["conversation_id"], msg["message_id"], reply_text)


# ─── 演示 ──────────────────────────────────────────────

def print_banner(text: str):
    print()
    print("=" * 60)
    print(f"  {text}")
    print("=" * 60)


def check_link_running() -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:18766/", timeout=3):
            return True
    except Exception:
        return False


def main():
    print_banner("🔗 Nanobot Link 简单示例")

    # 检查 Link 服务是否运行
    print("\n[检查] Link 服务是否运行在 http://localhost:18766 ...")
    if not check_link_running():
        print("❌ Link 服务未运行!")
        print()
        print("请先启动 Link 服务:")
        print("  cd nanobot-link")
        print("  pip install -r requirements.txt")
        print("  python server.py")
        print()
        print("然后再运行此示例:")
        print("  python examples/demo_simple.py")
        return

    print("✅ Link 服务运行中!\n")

    # 1. 创建两个 Bot
    print_banner("Step 1: 创建两个 Bot")
    bot_a = MockBot("专家助手", "严谨专业，擅长技术分析")
    bot_b = MockBot("调度助手", "善于沟通协调，擅长任务分配")

    # 2. 注册
    print_banner("Step 2: Bot 注册")
    bot_a.register()
    bot_b.register()

    # 3. 列出在线 Bots
    print_banner("Step 3: 列出在线 Bots")
    import urllib.request
    req = urllib.request.Request("http://localhost:18766/api/bots")
    with urllib.request.urlopen(req, timeout=5) as r:
        bots = json.loads(r.read())
    print(f"当前在线 Bots: {', '.join(b['name'] for b in bots)}")

    # 4. 设置回复回调
    bot_a.reply_callback = reply_handler
    bot_b.reply_callback = reply_handler

    # 5. Bot-A 发起话题
    print_banner("Step 4: Bot-A 发起话题")
    result = bot_a.send(
        target_bot = "调度助手",
        content     = "我收到了一个需求：用户希望我们做一个 AI 助手，可以帮他们自动回复飞书消息。你觉得这个需求怎么样？",
        topic       = "飞书助手需求分析"
    )
    conv_id = result["conversation_id"]

    # 6. Bot-B 接收并回复
    print_banner("Step 5: Bot-B 接收并回复")
    print(f"[调度助手] 正在监听对话 {conv_id} ...")
    messages = bot_b.poll_messages(conv_id, timeout=15)

    # 7. Bot-A 继续讨论
    print_banner("Step 6: Bot-A 继续讨论")
    if messages:
        last_msg = messages[-1]
        result2 = bot_a.send(
            target_bot      = "调度助手",
            content         = "那我们来分析一下技术实现路径吧，这个系统需要接入哪些模块？",
            conversation_id = conv_id,
        )

    # 8. 查看对话历史
    print_banner("Step 7: 查看完整对话历史")
    import urllib.request
    req = urllib.request.Request(f"http://localhost:18766/api/conversations/{conv_id}/messages")
    with urllib.request.urlopen(req, timeout=5) as r:
        full_history = json.loads(r.read())

    print(f"\n📋 对话历史（共 {len(full_history)} 条消息）:")
    print("-" * 60)
    for m in full_history:
        sender = m.get("sender_name", "?")
        ts     = time.strftime("%H:%M:%S", time.localtime(m["created_at"]))
        print(f"[{ts}] {sender}:")
        print(f"         {m['content']}")
        print()


if __name__ == "__main__":
    main()
