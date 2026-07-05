"""飞书 Webhook 告警通道。

使用方式:
    channel = FeishuChannel(webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/xxx")
    await channel.send(alert)
"""
import logging


import httpx

logger = logging.getLogger(__name__)


class FeishuChannel:
    """飞书机器人 Webhook 告警通道。"""

    SEVERITY_COLOR = {
        "info": "blue",
        "warning": "orange",
        "critical": "red",
    }

    def __init__(self, webhook_url: str, timeout: float = 10.0):
        """初始化。

        Args:
            webhook_url: 飞书机器人 Webhook URL
        """
        self.webhook_url = webhook_url
        self._client = httpx.AsyncClient(timeout=timeout)

    async def send(self, alert) -> bool:
        """发送告警到飞书。

        Args:
            alert: Alert 实例

        Returns:
            是否发送成功
        """
        color = self.SEVERITY_COLOR.get(alert.severity.value, "blue")

        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"[SuperClaw 告警] {alert.rule_name}",
                    },
                    "template": color,
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": alert.message,
                        },
                    },
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": f"告警时间: {alert.timestamp:.0f}",
                            }
                        ],
                    },
                ],
            },
        }

        try:
            resp = await self._client.post(self.webhook_url, json=card)
            result = resp.json()
            if result.get("code") == 0 or result.get("StatusCode") == 0:
                logger.info("飞书告警已发送: %s", alert.rule_name)
                return True
            else:
                logger.error("飞书告警发送失败: %s", result)
                return False
        except Exception as e:
            logger.error("飞书告警发送异常: %s", e)
            return False

    async def close(self) -> None:
        await self._client.aclose()
