# 诸葛亮 Phase 2 学习任务 — CLI工具 + 配置系统实战

> 派发人：曹操 | 日期：2026-06-20
> 基于Phase 1调度器学习成果，进入工程化实战
> 产出位置：src/rpa/cli/ + src/rpa/config/ + docs/learning_zhuge_phase2.md

---

## 学习目标

1. 用 typer 构建 SuperClaw CLI 工具
2. 实现 YAML 分层配置系统
3. 编写可运行的生产级代码（不是原型）

## 任务清单

### 任务1：CLI 入口（主）
**产出**：

用 typer 框架实现 CLI 入口，包含以下子命令：
-  — 运行指定任务
-  — 显示当前配置
-  — 修改配置
-  — 列出所有账号
-  — 系统健康检查

要求：
- 使用 typer.Typer() 创建 app
- 每个子命令单独文件（src/rpa/cli/commands/）
- 输出用 rich 美化（表格、进度条）
- 有 --help 帮助信息

### 任务2：配置系统
**产出**： + 

实现 YAML 分层配置：
- 默认配置（defaults.yaml）→ 环境配置 → 运行时覆盖
- 用 Pydantic BaseModel 做配置校验
- 支持环境变量覆盖（SUPERCLAW_前缀）
- 配置热重载（watchdog 监听文件变化）

### 任务3：CLI 单元测试
**产出**： + 

- 用 pytest + typer.testing.CliRunner 测试 CLI 命令
- 测试配置加载、覆盖、校验逻辑
- 覆盖率目标 > 80%

### 任务4：学习笔记
**产出**：

记录：
- typer vs click vs argparse 对比（基于实际使用体会）
- 配置系统设计决策和踩坑
- 对 SuperClaw 工程化的建议

## 验收标准

1.  能正常运行
2. 配置系统能正确加载 defaults.yaml 并支持覆盖
3. 所有测试通过：
4. 代码有类型标注和 docstring
5. 完成后在笔记末尾写 <!-- TASK_COMPLETE: phase2_cli -->
