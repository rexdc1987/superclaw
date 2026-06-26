"""通用 HTTP Webhook 告警通道。

使用方式:
    channel = WebhookChannel(url="https://hooks.example.com/alert", method="POST")
    await channel.send(alert)
"""
import json
import logging

import httpx

logger = logging.getLogger(__name__)


class WebhookChannel:
    """通用 HTTP Webhook 告警通道。"""

    def __init__(
        self,
        url: str,
        method: str = "POST",
        headers: dict = None,
        timeout: float = 10.0,
    ):
        """初始化。

        Args:
            url: Webhook URL
            method: HTTP 方法
            headers: 自定义请求头
        """
        self.url = url
        self.method = method.upper()
        self.headers = headers or {"Content-Type": "application/json"}
        self._client = httpx.AsyncClient(timeout=timeout)

    async def send(self, alert) -> bool:
        """发送告警到 Webhook。

        Args:
            alert: Alert 实例

        Returns:
            是否发送成功
        """
        payload = {
            "alert_name": alert.rule_name,
            "severity": alert.severity.value,
            "message": alert.message,
            "current_value": alert.current_value,
            "threshold": alert.threshold,
            "timestamp": alert.timestamp,
        }

        try:
            if self.method == "POST":
                resp = await self._client.post(
                    self.url, json=payload, headers=self.headers
                )
            else:
                resp = await self._client.request(
                    self.method, self.url,
                    content=json.dumps(payload),
                    headers=self.headers,
                )

            if resp.status_code < 400:
                logger.info("Webhook 告警已发送: %s -> %s (HTTP %d)",
                           alert.rule_name, self.url, resp.status_code)
                return True
            else:
                logger.error("Webhook 告警失败: HTTP %d, %s",
                           resp.status_code, resp.text[:200])
                return False

        except Exception as e:
            logger.error("Webhook 告警异常: %s", e)
            return False

    async def close(self) -> None:
        await self._client.aclose()
