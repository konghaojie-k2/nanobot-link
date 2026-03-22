# 示例

## 示例 1: demo_simple.py（模拟两个 Bot 对话）

最简单的演示，无需真实 nanobot，用模拟 Bot 展示完整通信流程。

```bash
# 1. 先启动 Link 服务
cd nanobot-link
pip install -r requirements.txt
python server.py

# 2. 另开终端运行示例
python examples/demo_simple.py
```

**运行效果：**

```
============================================================
  Step 1: 创建两个 Bot
============================================================

============================================================
  Step 2: Bot 注册
============================================================
[专家助手] 正在注册...
[专家助手] ✅ 注册成功! bot_id=abc123
[调度助手] 正在注册...
[调度助手] ✅ 注册成功! bot_id=def456

============================================================
  Step 4: Bot-A 发起话题
============================================================
[专家助手] ➡️  发送消息 → 调度助手: 我收到了一个需求...
✅ 消息已发送! conv_id=conv789

============================================================
  Step 5: Bot-B 接收并回复
============================================================
[调度助手] 正在监听对话 conv789 ...
[调度助手] 📩 收到消息 from 专家助手: 我收到了一个需求...
专家助手] ⬅️  回复: 我认为可以从技术可行性、业务价值...

📋 对话历史（共 2 条消息）:
------------------------------------------------------------
[11:30:01] 专家助手:
         我收到了一个需求：用户希望我们做一个 AI 助手...
[11:30:02] 调度助手:
         我认为可以从技术可行性、业务价值、风险三个维度...
```

---

## 示例 2: 真实 nanobot 接入

将 `bot_plugin/nanobot/link_tool/` 复制到你的 nanobot 安装目录：

```bash
cp -r bot_plugin/nanobot/ /your/nanobot/
```

配置环境变量：

```bash
export NANOBOT_LINK_URL="http://your-link-server:18766"
export NANOBOT_LINK_BOT_ID="your_bot_id"
export NANOBOT_LINK_API_KEY="your_api_key"
export NANOBOT_LINK_NAME="飞书助手"
```

然后在 nanobot 中使用工具：

```
用户：查看有哪些在线的 Bot
AI：
  → 调用 nanobot_link_list_bots
  → 返回：专家助手、调度助手

用户：让专家助手分析一下这个需求
AI：
  → 调用 nanobot_link_send(target="专家助手", content="分析一下这个需求...")
  → 专家助手收到后回复
  → AI 展示回复内容
```

---

## 示例 3：Webhook 模式（推荐生产使用）

Bot 需要暴露一个 HTTP 端点来**接收消息**（而不是轮询）。

在 Bot 中添加 Webhook 端点：

```python
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/api/link/webhook", methods=["POST"])
def handle_link_message():
    data = request.json
    event = data.get("event")

    if event == "message":
        sender    = data["sender"]["name"]
        content   = data["content"]
        reply_url = data["reply_url"]   # 回复用的回调 URL

        # 用 AI 处理消息（接入你的 nanobot）
        reply = ai_think(content)

        # 回复给对方
        import requests
        requests.post(reply_url, json={"content": reply},
                     headers={"X-API-Key": os.getenv("NANOBOT_LINK_API_KEY")})

    return jsonify({"status": "ok"})
```

Nanobot Link 会自动 POST 到你的 Webhook：

```json
{
  "event": "message",
  "message_id": "msg_abc123",
  "conversation_id": "conv_xyz789",
  "sender": { "id": "bot_a", "name": "专家助手" },
  "content": "我收到了一个需求...",
  "reply_url": "http://link:18766/api/message/reply/msg_abc123",
  "timestamp": 1742611200.0
}
```
