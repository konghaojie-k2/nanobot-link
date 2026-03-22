"""
Nanobot Link Plugin - 让 nanobot 通过 Nanobot Link 服务进行 Bot 间通信
将本文件放入 nanobot/agent/tools/ 目录即可使用
"""
import os
import json
import time
import asyncio
import threading
import logging
from typing import Any, Optional
from pathlib import Path

try:
    import httpx
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx", "-q"])
    import httpx

from nanobot.agent.tools.base import BaseTool

logger = logging.getLogger("nanobot.link")

LINK_URL = os.getenv("NANOBOT_LINK_URL", "http://localhost:18766")
BOT_ID   = os.getenv("NANOBOT_LINK_BOT_ID", "")
BOT_KEY  = os.getenv("NANOBOT_LINK_API_KEY", "")
BOT_NAME = os.getenv("NANOBOT_LINK_NAME", "nanobot")


class NanobotLinkTool(BaseTool):
    """
    Nanobot Link 通信工具
    让 nanobot 可以向其他 Bot 发起话题、交换意见、进行多轮对话
    """

    name = "nanobot_link"
    description = "与其他 AI Bot 进行通信、发起话题、交换意见"

    def __init__(
        self,
        link_url: str = None,
        bot_id: str = None,
        api_key: str = None,
        bot_name: str = None,
        webhook_path: str = "/api/link/webhook",
    ):
        self.link_url = link_url or LINK_URL
        self.bot_id   = bot_id   or BOT_ID
        self.api_key  = api_key  or BOT_KEY
        self.bot_name = bot_name or BOT_NAME
        self.webhook_path = webhook_path
        self._conversations: dict[str, dict] = {}  # 本地缓存对话
        self._async_client: Optional[httpx.AsyncClient] = None

    # ─── HTTP 客户端 ───────────────────────────
    @property
    def client(self) -> httpx.AsyncClient:
        if self._async_client is None or self._async_client.is_closed:
            self._async_client = httpx.AsyncClient(timeout=30.0)
        return self._async_client

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    # ─── Bot 注册 ─────────────────────────────
    async def register(self) -> str:
        """注册到 Nanobot Link 服务（仅需一次）"""
        if self.bot_id and self.api_key:
            return f"已注册: bot_id={self.bot_id}"

        r = await self.client.post(
            f"{self.link_url}/api/bot/register",
            json={
                "name":         self.bot_name,
                "webhook_url":  f"{self.link_url}{self.webhook_path}",
                "description":  f"Nanobot 实例: {self.bot_name}",
            },
        )
        data = r.json()
        if r.status_code != 200:
            raise Exception(f"注册失败: {data.get('detail', data)}")

        self.bot_id  = data["bot_id"]
        self.api_key = data["api_key"]
        return (
            f"注册成功！\n"
            f"  Bot ID : {self.bot_id}\n"
            f"  API Key: {self.api_key}\n"
            f"  请保存以上凭证，并配置环境变量:\n"
            f"    NANOBOT_LINK_BOT_ID={self.bot_id}\n"
            f"    NANOBOT_LINK_API_KEY={self.api_key}"
        )

    # ─── 发送消息 ─────────────────────────────
    async def send_message(
        self,
        target_bot: str,
        content: str,
        conversation_id: str = None,
        topic: str = "",
    ) -> str:
        """向指定 Bot 发送消息（可指定已有对话）"""
        if not self.api_key:
            return "❌ 未注册 Nanobot Link，请先调用 register()"

        r = await self.client.post(
            f"{self.link_url}/api/message/send",
            json={
                "target_bot":      target_bot,
                "content":         content,
                "conversation_id": conversation_id or None,
                "topic":           topic or "",
            },
            headers=self._headers(),
        )
        data = r.json()
        if r.status_code != 200:
            return f"❌ 发送失败: {data.get('detail', data)}"

        conv_id = data.get("conversation_id", "")
        status  = data.get("status", "sent")
        return (
            f"✅ 消息已发送 → {target_bot}\n"
            f"   对话 ID: {conv_id}\n"
            f"   状态: {status}"
        )

    # ─── 读取对话历史 ─────────────────────────
    async def get_conversation(self, conversation_id: str, limit: int = 20) -> str:
        """获取某对话的消息历史"""
        if not self.api_key:
            return "❌ 未注册"

        r = await self.client.get(
            f"{self.link_url}/api/conversations/{conversation_id}/messages",
            params={"limit": limit},
            headers=self._headers(),
        )
        if r.status_code != 200:
            return f"❌ 获取失败: {r.json().get('detail', r.text)}"

        msgs = r.json()
        if not msgs:
            return "暂无消息历史"

        lines = [f"=== 对话 {conversation_id} ==="]
        for m in msgs:
            sender = m.get("sender_name", m.get("sender_id", "?"))
            ts     = time.strftime("%m-%d %H:%M", time.localtime(m["created_at"]))
            lines.append(f"[{ts}] {sender}: {m['content']}")
        return "\n".join(lines)

    # ─── 列出活跃对话 ─────────────────────────
    async def list_conversations(self) -> str:
        """列出所有活跃对话"""
        if not self.api_key:
            return "❌ 未注册"

        r = await self.client.get(
            f"{self.link_url}/api/conversations",
            headers=self._headers(),
        )
        if r.status_code != 200:
            return f"❌ 获取失败: {r.json().get('detail', r.text)}"

        convs = r.json()
        if not convs:
            return "暂无活跃对话"

        lines = ["=== 活跃对话 ==="]
        for c in convs:
            ts    = time.strftime("%m-%d %H:%M", time.localtime(c["updated_at"]))
            topic = c.get("topic") or "无主题"
            last  = c.get("last_msg", "")
            if len(last) > 40:
                last = last[:40] + "..."
            lines.append(f"[{c['id']}] {c['peer_name']} | {topic} | {last}")
        return "\n".join(lines)

    # ─── 列出在线 Bots ────────────────────────
    async def list_online_bots(self) -> str:
        """查看所有在线的 Bot"""
        r = await self.client.get(f"{self.link_url}/api/bots")
        bots = r.json()
        if not bots:
            return "暂无在线 Bot"
        lines = ["=== 在线 Bots ==="]
        for b in bots:
            lines.append(f"  • {b['name']} — {b.get('description', '无描述')}")
        return "\n".join(lines)

    # ─── 主执行入口 ───────────────────────────
    async def execute(self, tool_call: dict) -> str:
        action = tool_call.get("action", "")
        params = tool_call.get("params", {})

        try:
            if action == "register":
                return await self.register()

            elif action == "send_message":
                return await self.send_message(
                    target_bot     = params.get("target_bot", ""),
                    content        = params.get("content", ""),
                    conversation_id = params.get("conversation_id"),
                    topic          = params.get("topic", ""),
                )

            elif action == "list_conversations":
                return await self.list_conversations()

            elif action == "get_conversation":
                return await self.get_conversation(
                    params.get("conversation_id", ""),
                    params.get("limit", 20),
                )

            elif action == "list_online_bots":
                return await self.list_online_bots()

            else:
                return f"未知操作: {action}"
        except Exception as e:
            logger.error(f"NanobotLink 执行错误: {e}")
            return f"❌ 错误: {e}"

    def get_tool_definitions(self) -> list[dict]:
        return [
            {
                "name": "nanobot_link_register",
                "description": "注册本 Bot 到 Nanobot Link 中转服务（只需执行一次）",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "nanobot_link_send",
                "description": "向另一个 Bot 发送消息或发起新话题",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target_bot":      {"type": "string", "description": "目标 Bot 名称或 ID"},
                        "content":         {"type": "string", "description": "消息内容"},
                        "conversation_id":  {"type": "string", "description": "已有对话 ID（可选，不填则创建新对话）"},
                        "topic":           {"type": "string", "description": "对话主题（可选）"},
                    },
                    "required": ["target_bot", "content"],
                },
            },
            {
                "name": "nanobot_link_list_bots",
                "description": "查看所有在线的 Bot",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "nanobot_link_list_conversations",
                "description": "列出本 Bot 所有活跃对话",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "nanobot_link_get_conversation",
                "description": "读取某对话的消息历史",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "conversation_id": {"type": "string", "description": "对话 ID"},
                        "limit":          {"type": "integer", "description": "最多返回消息数，默认 20"},
                    },
                    "required": ["conversation_id"],
                },
            },
        ]
