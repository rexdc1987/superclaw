# 红果开发流程

## 1. 启动前检查

先跑：

```powershell
cd E:\Projects\SuperClaw
.\venv\Scripts\python.exe scripts\hongguo_dev_smoke.py
```

要求：
- `8890` API 在线
- `3000` 前端在线
- `/health` 可访问
- `/api/v1/hongguo/tasks/10` 可返回

## 2. 如果前端没起来

直接重启：

```powershell
Start-Process -FilePath cmd.exe -ArgumentList @('/c','cd /d E:\Projects\SuperClaw\frontend && npm run dev') -WindowStyle Hidden
```

## 3. 修改顺序

1. 先改后端或引擎
2. 再跑 `py_compile`
3. 再跑 `pytest tests\test_rpa_engine.py -q`
4. 再刷新 `http://test.openclaw.com:3000/`

## 4. 红果任务修改时的固定检查点

- 任务状态字段是否回写 `created_at / updated_at / started_at / completed_at / duration_seconds`
- `records` 是否带截图 URL
- `logs` 是否按最新时间返回
- 播放逻辑是否仍然按“确认当前集 -> 等待自动跳集 -> 处理评论”执行
- 重新启动同一任务前，先确认已成功评论集数会被跳过，不会重复打到平台
- 任务需要改配置时，用编辑入口，不要新建同名任务替代

## 5. 不要直接做的事

- 不要先跑真实任务再看页面
- 不要只看前端，不查 8890 接口
- 不要改完不跑 smoke test
