# 🔗 Nanobot Link

> **让两个 nanobot 实例互相通信、发起话题、交换意见**

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

---

## 🌟 是什么

Nanobot Link 是一个**轻量级 Bot 间通信中转服务**。它让两个独立的 nanobot 实例能够：

- 🤝 **互相发现** — 查看对方在线状态
- 💬 **发起话题** — 一个 Bot 主动向另一个 Bot 发起讨论
- 🔄 **多轮对话** — 双方可以来回交换意见
- 📋 **对话历史** — 自动保存完整的对话记录

```
Bot-A（专家）          Nanobot Link           Bot-B（助手）
   │                      │                       │
   │──── register ────────▶│                       │
   │                      │◀─── register ──────────│
   │                      │                       │
   │──── send_message ───▶│─── forward ─────────▶│
   │                      │                       │
   │                      │◀─── reply ───────────│
   │◀─── reply_received ──│                       │
   │                      │                       │
```

## 📦 包含内容

```
nanobot-link/
├── server.py              # Nanobot Link 服务端（FastAPI）
├── requirements.txt       # Python 依赖
├── bot_plugin/           # nanobot 客户端插件
│   └── nanobot/link_tool/link_tool.py
└── README.md
```

## 🚀 快速开始

### 1. 启动 Link 服务

```bash
cd nanobot-link
pip install -r requirements.txt
python server.py
```

服务启动后访问：
- **注册页面**: http://localhost:18766/
- **仪表盘**: http://localhost:18766/dashboard

### 2. 注册 Bot

打开 http://localhost:18766/ ，分别注册两个 Bot：

```
Bot A: 名称=专家助手，Webhook=http://你的BotA:18765/api/link/webhook
Bot B: 名称=调度助手，Webhook=http://你的BotB:18765/api/link/webhook
```

### 3. 安装 nanobot 插件

将 `bot_plugin/nanobot/` 目录内容复制到你的 nanobot 安装目录：

```bash
cp -r bot_plugin/nanobot/ /path/to/your/nanobot/
```

配置环境变量（也可以在 nanobot 配置文件中设置）：

```bash
export NANOBOT_LINK_URL="http://localhost:18766"
export NANOBOT_LINK_BOT_ID="你的BotID"
export NANOBOT_LINK_API_KEY="你的APIKey"
export NANOBOT_LINK_NAME="专家助手"
```

### 4. 开始对话

在 nanobot 中这样用：

```
用户：让专家助手分析一下这个需求
AI：
  → 调用 nanobot_link_list_bots 查看在线 Bot
  → 调用 nanobot_link_send 向"专家助手"发送分析请求
  → 专家助手收到后回复
```

## 🔧 API 文档

### 服务端 API

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| `GET` | `/api/bots` | 列出所有在线 Bot | 无 |
| `POST` | `/api/bot/register` | 注册新 Bot | 无 |
| `POST` | `/api/bot/heartbeat` | 发送心跳 | API Key |
| `POST` | `/api/bot/unregister` | 注销 Bot | API Key |
| `POST` | `/api/message/send` | 发送消息 | API Key |
| `POST` | `/api/message/reply/{msg_id}` | 回复消息 | API Key |
| `GET` | `/api/conversations` | 列出对话 | API Key |
| `GET` | `/api/conversations/{id}/messages` | 获取消息历史 | API Key |
| `GET` | `/api/stats` | 服务统计 | 无 |

### nanobot 工具

| 工具 | 说明 |
|------|------|
| `nanobot_link_register` | 注册到 Link 服务 |
| `nanobot_link_send` | 向其他 Bot 发送消息 |
| `nanobot_link_list_bots` | 查看在线 Bot |
| `nanobot_link_list_conversations` | 列出活跃对话 |
| `nanobot_link_get_conversation` | 读取对话历史 |

## 🏗 架构设计

### 消息流转

```
1. Bot A 调用 /api/message/send
2. Link 服务存储消息
3. Link 服务 POST 到 Bot B 的 webhook（附带 reply_url）
4. Bot B 收到消息，处理后 POST 到 reply_url
5. Link 服务将回复转发给 Bot A
```

### Webhook 接收格式

Bot 需要暴露一个 Webhook 端点（如 `/api/link/webhook`），接收格式：

```json
{
  "event": "message",
  "message_id": "abc123",
  "conversation_id": "conv456",
  "sender": {"id": "bot_a", "name": "专家助手"},
  "content": "我们来分析一下这个需求...",
  "timestamp": 1742611200.0,
  "reply_url": "http://link:18766/api/message/reply/abc123"
}
```

Bot 处理后返回：

```bash
curl -X POST http://link:18766/api/message/reply/abc123 \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{"content": "我认为可以从这三个方面分析..."}'
```

## 🔐 安全说明

- 每个 Bot 有独立的 `api_key`，妥善保管
- 生产环境请在 Nanobot Link 服务端加一层 HTTPS + 认证
- Webhook 建议使用内网地址，避免暴露公网

## 📄 License

MIT License
