"""
账号健康度评分器

多维度评估账号健康状态：登录成功率、操作成功率、被标记率、封禁状态、活跃度
"""

import time
import logging
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass
class HealthMetrics:
    """健康度指标"""
    login_success: int = 0       # 登录成功次数
    login_failure: int = 0       # 登录失败次数
    action_success: int = 0      # 操作成功次数
    action_failure: int = 0      # 操作失败次数
    captcha_triggered: int = 0   # 触发验证码次数
    flagged_count: int = 0       # 被标记/警告次数
    ban_count: int = 0           # 被封禁次数
    last_check: float = 0.0      # 上次检查时间
    total_sessions: int = 0      # 总会话数
    avg_session_duration: float = 0.0  # 平均会话时长(秒)

    @property
    def login_rate(self) -> float:
        total = self.login_success + self.login_failure
        return self.login_success / total if total > 0 else 1.0

    @property
    def action_rate(self) -> float:
        total = self.action_success + self.action_failure
        return self.action_success / total if total > 0 else 1.0

    @property
    def captcha_rate(self) -> float:
        """触发验证码的频率（越低越好）"""
        total = self.action_success + self.action_failure
        return self.captcha_triggered / total if total > 0 else 0.0


class HealthScorer:
    """
    健康度评分器

    评分维度和权重：
    - 登录成功率 (30%)
    - 操作成功率 (30%)
    - 验证码触发率 (15%, 越低越好)
    - 封禁记录 (15%, 越低越好)
    - 活跃度 (10%)

    最终分数 0-100：
    - 80-100: 健康
    - 60-80: 亚健康（需关注）
    - 40-60: 高风险（建议冷却）
    - 0-40: 危险（建议禁用）
    """

    WEIGHTS = {
        "login": 0.30,
        "action": 0.30,
        "captcha": 0.15,
        "ban": 0.15,
        "activity": 0.10,
    }

    THRESHOLDS = {
        "healthy": 80,
        "warning": 60,
        "danger": 40,
    }

    def calculate(self, metrics: HealthMetrics) -> float:
        """
        计算健康度评分

        Args:
            metrics: 健康度指标

        Returns:
            0-100 分数
        """
        scores = {}

        # 登录成功率得分
        scores["login"] = metrics.login_rate * 100

        # 操作成功率得分
        scores["action"] = metrics.action_rate * 100

        # 验证码触发率得分（反向，触发越多分越低）
        scores["captcha"] = max(0, (1 - metrics.captcha_rate * 5)) * 100

        # 封禁记录得分（有封禁记录扣分）
        if metrics.ban_count > 0:
            scores["ban"] = max(0, 100 - metrics.ban_count * 30)
        else:
            scores["ban"] = 100.0

        # 活跃度得分（近期活跃加分）
        hours_since_check = (time.time() - metrics.last_check) / 3600 if metrics.last_check > 0 else 999
        if hours_since_check < 24:
            scores["activity"] = 100.0
        elif hours_since_check < 72:
            scores["activity"] = 70.0
        elif hours_since_check < 168:
            scores["activity"] = 40.0
        else:
            scores["activity"] = 10.0

        # 加权求和
        total = sum(scores[k] * self.WEIGHTS[k] for k in self.WEIGHTS)

        # 封禁扣分（直接扣）
        if metrics.flagged_count > 0:
            total -= min(20, metrics.flagged_count * 5)

        return max(0.0, min(100.0, round(total, 1)))

    def classify(self, score: float) -> str:
        """
        根据分数分类

        Returns:
            "healthy" / "warning" / "danger" / "critical"
        """
        if score >= self.THRESHOLDS["healthy"]:
            return "healthy"
        elif score >= self.THRESHOLDS["warning"]:
            return "warning"
        elif score >= self.THRESHOLDS["danger"]:
            return "danger"
        return "critical"

    def recommend_action(self, score: float) -> str:
        """根据分数推荐操作"""
        cls = self.classify(score)
        actions = {
            "healthy": "正常运行",
            "warning": "降低操作频率，增加间隔",
            "danger": "暂停使用，进入冷却期（建议24小时）",
            "critical": "立即禁用，人工检查",
        }
        return actions.get(cls, "未知")

    def evaluate(self, metrics: HealthMetrics) -> dict:
        """
        完整评估

        Returns:
            {score, classification, recommendation, detail_scores}
        """
        score = self.calculate(metrics)
        return {
            "score": score,
            "classification": self.classify(score),
            "recommendation": self.recommend_action(score),
            "metrics": {
                "login_rate": round(metrics.login_rate, 3),
                "action_rate": round(metrics.action_rate, 3),
                "captcha_rate": round(metrics.captcha_rate, 3),
                "ban_count": metrics.ban_count,
                "flagged_count": metrics.flagged_count,
            },
        }
