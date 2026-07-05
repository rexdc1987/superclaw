"""SuperClaw RPA 管道模块。

提供表单自动提交、压力测试等管道能力。
"""

from rpa.pipelines.social_media_collector import SocialMediaCollector
from rpa.pipelines.form_submitter import FormSubmitter, SubmitResult, SubmitStatus
from rpa.pipelines.stress_test import StressTester, StressTestResult

__all__ = [
    "FormSubmitter",
    "SubmitResult",
    "SubmitStatus",
    "StressTester",
    "StressTestResult",
    "SocialMediaCollector",
]
