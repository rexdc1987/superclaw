"""
简易告警通道

在已有 channels/ 包基础上补充 Console 和 File 通道。
"""

import json
import logging

from pathlib import Path


from rpa.monitoring.channels import AlertChannel, AlertMessage

logger = logging.getLogger(__name__)


class ConsoleChannel(AlertChannel):
    """控制台告警通道"""

    def __init__(self):
        super().__init__(name="console")

    async def send(self, message: AlertMessage) -> bool:
        print(message.to_text())
        return True


class FileChannel(AlertChannel):
    """文件告警通道"""

    def __init__(self, log_path: str = "data/alerts.log"):
        super().__init__(name="file")
        self._log_path = Path(log_path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    async def send(self, message: AlertMessage) -> bool:
        try:
            record = {
                "timestamp": message.timestamp.isoformat() if message.timestamp else None,
                "rule": message.rule_name,
                "severity": message.severity.value,
                "title": message.title,
                "description": message.description,
                "metric_value": message.metric_value,
                "threshold": message.threshold,
            }
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            return True
        except Exception as e:
            logger.error("文件告警推送失败: %s", e)
            return False
