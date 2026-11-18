# 逐步实施指南

当前状态（2026-11-18）：第 1–3 步已完成，第 5 步的单任务 grader 已实现并对照验证；第 4 步（工具与 scripted 循环）未开始。已完成条目保留原始命令，作为以后的环境与数据回归检查。

## 1. 创建 Conda 环境（已完成）

本机已有 Conda，默认环境是 aitown。使用项目独立环境：

```powershell
Set-Location D:\agent\agent-harness-eval
conda env create --file environment.yml
conda activate agent-harness
python --version
python -c "import sys; print(sys.executable)"
```

验收：Python 3.11，解释器属于 `agent-harness` 环境。激活不可用时，可用 `conda run -n agent-harness python ...`。这里不需要 GPU、模型密钥或 Docker。现有环境已创建时跳过创建命令。

安装后记录实际依赖版本，初始 YAML 不是严格锁文件：

```powershell
conda env export --name agent-harness --no-builds --file environment.resolved.yml
```

## 2. 下载并理解真实开发数据（已完成）

已提供的脚本获取 Hugging Face revision 后按 SHA 加载数据，校验字段，拆分公开信息和答案，不执行任何补丁或测试：

```powershell
python scripts\prepare_swebench.py --split dev
```

产物：

- `data/public/lite-dev/tasks.jsonl`：Agent 可见字段。
- `data/private/lite-dev/oracle.jsonl`：完整原始记录，含代码与测试补丁。
- `data/manifests/lite-dev.json`：revision、行数、哈希、仓库统计。

这只是数据拆分，正式执行还要隔离文件系统；不能把整个项目目录提供给 Agent。

先读 3 条公开任务和统计：

```powershell
Get-Content -Encoding UTF8 data\public\lite-dev\tasks.jsonl -TotalCount 3
Get-Content -Encoding UTF8 data\manifests\lite-dev.json
```

逐条回答：用户要修什么？仓库和 base 是什么？对应哪个 PR？目标测试与历史依赖是什么？哪些数据应隐藏？不要将 PR 编号当 Issue 编号。人工看过答案的样本归为开发用途。

下载成功只代表数据取得成功。网络无法连接时保留报错，不自动换成不明来源镜像。

## 3. 人工复现一条任务，先不调用模型（已完成）

从 dev 选依赖相对简单、测试明确的任务。已建立 `docs/first-task.md`，记录 instance_id、数据 revision、仓库/PR/核实后的 Issue URL、base、环境版本、命令和日志路径。

操作顺序：

1. 在临时执行工作区取得并固定到 base。
2. 根据历史任务配方构建独立环境，不用仓库最新版依赖代替。
3. 应用 test_patch，确认目标测试因功能问题失败，回归状态符合预期。
4. 重建干净工作区，应用 patch 和 test_patch，确认全部指定测试通过。
5. 保存用例数量、明确状态、退出码和完整日志。

复用官方镜像时先准备 WSL2/Linux + Docker，并核实数据 revision 与评测器兼容。Conda 继续管理 Harness，与容器并不冲突。不要在日常业务环境中直接运行不受信的历史代码。

验收：同一任务有可重复的失败和通过证据。依赖失败、零测试和只查看 GitHub CI 不算完成。若失败，先修环境或换样本，不急着实现复杂 Agent。

本条任务的完成证据：`scripts/verify_first_task.py` 在 `artifacts/first-task/verify-0pcb_i9r/` 留下三组日志，结果为修复前目标测试 1 条按预期失败、回归 76 条通过、参考修复后 77 条通过。数据中 8 个参数化测试 ID 存在截断，脚本只在唯一前缀匹配时补全并记录映射。该结果是本机参考验证，不是官方容器评测。

## 4. 实现工具与 scripted 循环

以下均待实现：定义 Task/Action/ToolResult/SessionState；实现工作区内文件、搜索、patch、测试和 diff；用预设动作走通读取→修改→测试→结束；保存每步事件与最终补丁，限制步数和时间。

验收：scripted 运行可重放，越界被拒绝，错误能被结构化表达。它验证运行时，不计入模型解决率。

## 5. 接真实模型与独立 grader

此时才选模型接口和费用上限，先实现一个适配器。只给模型 Issue、base 和开发工具；完成后在全新 grader 工作区应用候选补丁和隐藏测试。

进度：单任务 grader 已实现（`scripts/grade_first_task.py`），用参考补丁、空修改和测试补丁三种输入验证过；模型适配器尚未实现，因此还没有真实轨迹与费用数据。

验收：得到真实轨迹、补丁、费用和独立判分。失败时区分定位、修改、工具、环境和预算问题，不只改 prompt 反复试。

## 6. 权限与恢复

先用确定性场景检查普通写入、危险操作审批、拒绝、patch 删除、路径逃逸和参数变化。再在执行前、执行后写 receipt 前、receipt 后注入退出。

验收：恢复时能核对真实状态，审批不被绕过，没有重复副作用；每个注入点都有记录。只从 SQLite 读取再重新运行不算完整恢复设计。

## 7. 冻结数据，做 A/B

筛选与开发数据去重的独立集合，全部做参考答案验收。用 3–5 条 pilot 测费用与压缩触发率，再固定模型、工具、预算比较截断与摘要。先单次，预算允许再每任务四次。

验收：每个分数可追溯到 manifest、配置和 trial；报告波动、摘要错误、环境错误和区间。差异不明确时如实写不确定性。

## 8. MCP 与演示

已验证的搜索增加 stdio MCP 适配器，最后做 GitHub mock PR 草稿及可选真实发布演示。演示用自己的 fork/测试仓库，不向上游重复提交已经修复的历史 bug。

最终验收：README、复现命令、真实实验报告和端到端演示。

**现在从第 1、2 步开始，之后根据实际样本选择第一条复现任务。**
