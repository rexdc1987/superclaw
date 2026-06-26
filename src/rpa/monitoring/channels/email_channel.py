"""
邮件告警通道

通过 SMTP 发送告警邮件，支持 TLS/SSL。
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


from . import AlertChannel, AlertMessage, AlertSeverity

logger = logging.getLogger(__name__)


class EmailChannel(AlertChannel):
    """
    邮件告警通道

    通过 SMTP 发送告警邮件，支持 STARTTLS 和 SSL。

    配置示例：
        channel = EmailChannel(
            name="ops-email",
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            username="alert@company.com",
            password="app-password",
            from_addr="alert@company.com",
            to_addrs=["ops@company.com", "dev@company.com"],
            use_tls=True,
        )
    """

    def __init__(
        self,
        name: str = "email",
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
        username: str = "",
        password: str = "",
        from_addr: str = "",
        to_addrs: list[str] = None,
        use_tls: bool = True,
        use_ssl: bool = False,
    ):
        super().__init__(name)
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._username = username
        self._password = password
        self._from_addr = from_addr
        self._to_addrs = to_addrs or []
        self._use_tls = use_tls
        self._use_ssl = use_ssl

    def _build_message(self, alert: AlertMessage) -> MIMEMultipart:
        """构建邮件消息"""
        msg = MIMEMultipart("alternative")

        severity_prefix = {
            AlertSeverity.INFO: "[INFO]",
            AlertSeverity.WARNING: "[WARNING]",
            AlertSeverity.CRITICAL: "[CRITICAL]",
        }
        prefix = severity_prefix.get(alert.severity, "[ALERT]")
        msg["Subject"] = f"{prefix} {alert.title}"
        msg["From"] = self._from_addr
        msg["To"] = ", ".join(self._to_addrs)

        # 纯文本内容
        text = alert.to_text()

        # HTML 内容
        severity_color = {
            AlertSeverity.INFO: "#3b82f6",
            AlertSeverity.WARNING: "#f59e0b",
            AlertSeverity.CRITICAL: "#ef4444",
        }
        color = severity_color.get(alert.severity, "#6b7280")
        html = f"""<html>
<body style="font-family: Arial, sans-serif; padding: 20px;">
  <div style="border-left: 4px solid {color}; padding: 10px; margin-bottom: 15px;">
    <h2 style="color: {color}; margin:0;">{prefix} {alert.title}</h2>
  </div>
  <table style="border-collapse: collapse; width: 100%;">
    <tr><td style="padding:8px; font-weight:bold;">Rule</td><td style="padding:8px;">{alert.rule_name}</td></tr>
    <tr><td style="padding:8px; font-weight:bold;">Description</td><td style="padding:8px;">{alert.description}</td></tr>
    <tr><td style="padding:8px; font-weight:bold;">Value</td><td style="padding:8px;">{alert.metric_value}</td></tr>
    <tr><td style="padding:8px; font-weight:bold;">Threshold</td><td style="padding:8px;">{alert.threshold}</td></tr>
    <tr><td style="padding:8px; font-weight:bold;">Time</td><td style="padding:8px;">{alert.timestamp.isoformat() if alert.timestamp else 'N/A'}</td></tr>
  </table>
  <hr style="margin-top:20px;">
  <p style="color:#888; font-size:12px;">SuperClaw RPA Monitoring System</p>
</body>
</html>"""

        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
        return msg

    async def send(self, message: AlertMessage) -> bool:
        """发送告警邮件（在线程池中执行 SMTP 操作）"""
        if not self._to_addrs:
            logger.error(f"[{self._name}] No recipients configured")
            return False

        msg = self._build_message(message)

        def _send_sync():
            try:
                if self._use_ssl:
                    server = smtplib.SMTP_SSL(self._smtp_host, self._smtp_port)
                else:
                    server = smtplib.SMTP(self._smtp_host, self._smtp_port)

                if self._use_tls and not self._use_ssl:
                    server.starttls()

                if self._username:
                    server.login(self._username, self._password)

                server.sendmail(self._from_addr, self._to_addrs, msg.as_string())
                server.quit()
                return True
            except Exception as e:
                logger.error(f"[{self._name}] SMTP error: {e}")
                return False

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _send_sync)

        if result:
            logger.info(f"[{self._name}] Email sent to {len(self._to_addrs)} recipients")
        return result
