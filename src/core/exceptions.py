"""SuperClaw 自定义异常"""


class SuperClawError(Exception):
    """基础异常"""
    def __init__(self, message="", code=""):
        self.message = message
        self.code = code
        super().__init__(message)


class AccountError(SuperClawError):
    pass

class TaskError(SuperClawError):
    pass

class RiskControlError(SuperClawError):
    pass

class PlatformError(SuperClawError):
    pass

class ConfigError(SuperClawError):
    pass

class StateTransitionError(TaskError):
    def __init__(self, current, target):
        super().__init__(f"非法状态转换: {current} -> {target}")
        self.current = current
        self.target = target

# Aliases for backward compatibility
TaskStateError = StateTransitionError
AccountNotAvailableError = AccountError
RateLimitExceededError = RiskControlError
SensitiveWordError = RiskControlError
