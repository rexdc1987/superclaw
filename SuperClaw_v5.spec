# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\Chaos\\Documents\\SuperClaw\\src\\main.py'],
    pathex=['C:\\Users\\Chaos\\Documents\\SuperClaw\\src'],
    binaries=[],
    datas=[('C:\\Users\\Chaos\\Documents\\SuperClaw\\config', 'config'), ('C:\\Users\\Chaos\\Documents\\SuperClaw\\assets', 'assets')],
    hiddenimports=['models', 'models.account', 'models.task', 'models.comment', 'models.lead', 'models.action', 'models.risk', 'models.audit', 'models.keyword', 'models.template', 'models.database', 'models.user', 'services', 'services.account_service', 'services.task_service', 'services.collector_service', 'services.lead_service', 'services.action_service', 'services.risk_service', 'services.export_service', 'services.keyword_service', 'services.review_service', 'services.scheduler', 'services.user_service', 'services.task_executor', 'gui', 'gui.app', 'gui.main_window', 'gui.dashboard', 'gui.account_view', 'gui.task_view', 'gui.lead_view', 'gui.template_view', 'gui.log_view', 'gui.review_view', 'gui.risk_view', 'gui.login_dialog', 'gui.user_view', 'core', 'core.config', 'core.constants', 'core.exceptions', 'utils', 'utils.logger', 'utils.validators', 'utils.helpers', 'automation', 'automation.browser', 'automation.platform_base', 'automation.douyin_adapter', 'sqlalchemy.dialects.sqlite', 'PySide6.QtCore', 'PySide6.QtWidgets'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['playwright'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SuperClaw_v5',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SuperClaw_v5',
)
