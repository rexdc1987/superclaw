import sys
sys.path.insert(0, ".")

modules = [
    "src.models.database",
    "src.models.account",
    "src.models.task",
    "src.models.keyword",
    "src.models.comment",
    "src.models.lead",
    "src.models.action",
    "src.models.audit",
    "src.models.risk",
    "src.models.template",
    "src.core.constants",
    "src.core.exceptions",
    "src.core.config",
    "src.utils.logger",
    "src.services.account_service",
    "src.services.keyword_service",
    "src.services.task_service",
    "src.services.lead_service",
    "src.services.export_service",
    "src.services.risk_service",
    "src.automation.browser",
    "src.automation.platform_base",
    "src.main",
]

for mod in modules:
    try:
        __import__(mod)
        print(f"  OK: {mod}")
    except Exception as e:
        print(f"  FAIL: {mod} -> {type(e).__name__}: {e}")

print("\nDone.")
