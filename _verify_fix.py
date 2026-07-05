"""马超修复验证 - 红果模块API端点 + 状态流转 + 日志写入"""
import requests, time

BASE = "http://localhost:8002/api/v1/hongguo"
results = []

def log(icon, name, code, detail=""):
    results.append((icon, name, code, detail))
    print(f"  {icon} {name:45s} {code:>3d}  {detail[:80]}")

def api(method, path, **kw):
    try:
        return getattr(requests, method)(f"{BASE}{path}", timeout=5, **kw)
    except Exception as e:
        return None

print("=" * 70)
print("  马超修复验证 - 红果模块全流程")
print("=" * 70)

# ── 1. API端点 ──
print("\n▸ 1. API端点测试")

r = api("get", "/tasks")
log("✅" if r and r.status_code==200 else "❌", "GET /tasks", r.status_code if r else 0)

# 关键：POST创建任务（用drama_name，不用task_name）
r = api("post", "/tasks", json={
    "drama_name": "修复验证剧",
    "comment_mode": "specified",
    "start_episode": 1,
    "episode_interval": 1,
    "comment_interval_sec": 30,
    "content_source": "ai",
    "templates": ["好看"]
})
ok = r and r.status_code == 200
log("✅" if ok else "❌", "POST /tasks (drama_name)", r.status_code if r else 0,
    "" if ok else f"ERR: {r.text[:120] if r else 'no response'}")
tid = r.json().get("id") if ok else None

if not tid:
    print("\n  ⛔ 创建任务失败，后续全部跳过")
else:
    r = api("get", f"/tasks/{tid}")
    log("✅" if r and r.status_code==200 else "❌", f"GET /tasks/{tid}", r.status_code if r else 0)

    r = api("put", f"/tasks/{tid}", json={"drama_name": "已更新剧名"})
    log("✅" if r and r.status_code==200 else "❌", f"PUT /tasks/{tid}", r.status_code if r else 0,
        "" if r and r.status_code==200 else f"ERR: {r.text[:120] if r else ''}")

    # ── 2. 状态流转 ──
    print("\n▸ 2. 状态流转 (start→pause→resume→stop)")

    def status():
        r = api("get", f"/tasks/{tid}")
        return r.json().get("status") if r and r.status_code == 200 else None

    r = api("post", f"/tasks/{tid}/start")
    s = status()
    log("✅" if r and r.status_code==200 else "❌", "start", r.status_code if r else 0, f"→ {s}")
    time.sleep(0.3)

    r = api("post", f"/tasks/{tid}/pause")
    s = status()
    log("✅" if r and r.status_code==200 and s=="paused" else "❌", "pause", r.status_code if r else 0, f"→ {s}")

    r = api("post", f"/tasks/{tid}/resume")
    s = status()
    log("✅" if r and r.status_code==200 and s=="running" else "❌", "resume", r.status_code if r else 0, f"→ {s}")
    time.sleep(0.3)

    r = api("post", f"/tasks/{tid}/stop")
    s = status()
    log("✅" if r and r.status_code==200 and s=="stopped" else "❌", "stop", r.status_code if r else 0, f"→ {s}")

    # ── 3. 日志写入 ──
    print("\n▸ 3. 日志写入验证")
    r = api("get", f"/tasks/{tid}/logs")
    if r and r.status_code == 200:
        logs = r.json()
        cnt = len(logs) if isinstance(logs, list) else 0
        log("✅" if cnt > 0 else "❌", "日志条数", r.status_code, f"{cnt}条")
        for lg in logs[:5]:
            print(f"       [{lg.get('level','?')}] {lg.get('message','')[:60]}")
    else:
        log("❌", "日志读取", r.status_code if r else 0, "")

    r = api("get", f"/tasks/{tid}/records")
    log("✅" if r and r.status_code==200 else "❌", "评论记录", r.status_code if r else 0)

    # ── 清理 ──
    r = api("delete", f"/tasks/{tid}")
    log("✅" if r and r.status_code==200 else "⚠️", "DELETE", r.status_code if r else 0,
        "" if r and r.status_code==200 else "FK约束(有日志时)")

# ── Summary ──
print("\n" + "=" * 70)
p = sum(1 for i,_,_,_ in results if i == "✅")
f = sum(1 for i,_,_,_ in results if i in ("❌","⚠️"))
print(f"  结果: {p}/{len(results)} passed, {f} failed")
print("=" * 70)
