# 当前进展

> 最后更新：2026-11-18。设计细节见 [proposal.md](proposal.md)，分步路线见 [docs/implementation-guide.md](docs/implementation-guide.md)，第一条任务的完整记录见 [docs/first-task.md](docs/first-task.md)。

## 一句话状态

数据链路已经打通，一条真实任务通过了“修复前失败、参考修复后通过”的本机验收，候选补丁的评分器也能独立判分。最小运行时（工作区、工具、权限、循环、轨迹）已用**预设动作**跑通，并产出补丁交给 grader 判定为通过。**还没有接模型**：没有真实轨迹、没有 token 费用、没有实验数字。

## 阶段进度

| 阶段 | 状态 | 说明 |
|---|---|---|
| M0 数据 | 基本完成 | 23 条 dev 已按 revision 固定下载，哈希校验通过；1 条任务达到 `oracle_validated` |
| M1 闭环 | 进行中 | scripted 运行时已跑通（工具、权限、轨迹、补丁）；模型适配器与泛化评测未实现 |
| M2 可靠性 | 未开始 | 权限、持久化、崩溃注入 |
| M3 实验 | 未开始 | 截断/摘要 A/B、重复运行、指标 |
| M4 展示 | 未开始 | MCP、PR 草稿 |

## 已经拿到的证据

### 数据

- 数据集：`SWE-bench/SWE-bench_Lite`，split `dev`，实际 revision `b0dde1093fe417d83b7184254edf8199c1f0dff5`。
- 23 条任务，来自 6 个仓库：marshmallow 2、pvlib 5、pydicom 5、astroid 5、pyvista 1、sqlfluff 5。
- 产物：`data/public/lite-dev/tasks.jsonl`（Agent 可见 4 个字段）、`data/private/lite-dev/oracle.jsonl`（完整记录）、`data/manifests/lite-dev.json`（revision、数量、SHA256）。
- 下载工具 `datasets 5.2.0`、`huggingface_hub 2.4.0`。

### 第一条任务（marshmallow-1359）

| 检查 | 结果 | 记录 |
|---|---|---|
| 最小复现 | `AttributeError: 'List' object has no attribute 'opts'` | 用户终端输出 |
| 修复前目标测试 | 1 条，按预期失败 | `artifacts/first-task/verify-0pcb_i9r/` |
| 修复前指定回归 | 76 条全部通过 | 同上 |
| 参考修复后 | 77 条全部通过 | 同上 |
| 总体状态 | `oracle_validated_local` | 同上 `result.json` |

环境：Python 3.7.16、pytest 7.4.4、Windows；Conda 环境 `task-marshmallow-1359`。

### 候选补丁评分器

| 输入 | 结果 | 记录 |
|---|---|---|
| 参考修复补丁当候选 | `passed`（77/77） | `artifacts/candidate-grading/grade-usl6kyc1/` |
| 空修改（反向对照） | `failed_tests`（1 失败，退出码 1） | `artifacts/candidate-grading/grade-jippbns1/` |
| 测试补丁当代码改动 | `invalid_patch`（白名单拒绝） | `artifacts/candidate-grading/grade-2a2ly8m1/` |

### 最小运行时（scripted，非模型）

`scripts/run_first_task.py` 用预设动作跑完“读 Issue → 搜索 → 读文件 → 跑测试 → 改代码 → 再跑测试 → 取 diff → 结束”，其中包括两个**故意违规**的动作。

| 事实 | 结果 | 记录 |
|---|---|---|
| 会话状态 | `finished`，10 步 | `artifacts/harness/first-task/run-43c90c62/` |
| 被权限拦截 | 2 次（路径逃逸读、改测试） | 同上 `trace.jsonl` |
| 工具错误 | 0 | 同上 |
| 候选补丁 | 489 字节，只改 `src/marshmallow/fields.py` 一行 | 同上 `candidate.diff` |
| 独立 grader | `passed`（77 个测试） | 同上 `result.json` |

这证明整条机械链路可用，**不证明模型会修 bug**：动作是写死的，补丁内容照着参考答案写。

设计原因记录在 [docs/harness-design.md](docs/harness-design.md)。

## 脚本

| 脚本 | 作用 | 状态 |
|---|---|---|
| [scripts/prepare_swebench.py](scripts/prepare_swebench.py) | 固定 revision 下载、字段校验、public/private 拆分、写 manifest | 可用 |
| [scripts/verify_first_task.py](scripts/verify_first_task.py) | 用参考答案验证任务：base 失败 → 参考修复通过 | 可用，仅本任务 |
| [scripts/grade_first_task.py](scripts/grade_first_task.py) | 给候选补丁打分，不回放参考代码补丁 | 可用，仅本任务 |
| [scripts/run_first_task.py](scripts/run_first_task.py) | scripted 运行时：建工作区、执行工具、权限拦截、产出补丁、调用 grader | 可用，仅本任务 |
| [src/agent_harness/](src/agent_harness/) | 最小运行时：schemas、workspace、policy、tools、runtime | 已实现 |

两个脚本都用 `git archive` 从 base 提交导出全新快照，不会改动 `data/workspaces/` 里的现有 checkout。

## 已知问题

1. **数据缺陷**：`PASS_TO_PASS` 中有 8 个参数化测试 ID 被截断（缺结尾的 `]` 和参数后半段）。脚本用“唯一前缀匹配”补全并记录映射；无法唯一匹配就报错。原始数据未修改，也不能声称完全原样使用官方数据。
2. **checkout 已“改脏”**：`data/workspaces/marshmallow-1359` 里残留人工验证时应用的 `test_patch` 和参考 `patch`，`git status` 显示两个文件被修改。它只作为 `git archive` 的来源，不能当“修复前代码”复用；恢复用 `git restore .`。
3. **脚本与运行时仍是单任务硬编码**：任务 ID、测试数量（1 + 76）、收集器路径、`src/marshmallow/*.py` 白名单都写死，不能直接用于其他任务。
4. **scripted 动作是写死的**：`run_first_task.py` 的动作序列和补丁内容照着参考答案写，只证明运行时可用，不代表 Agent 能力。
5. **没有隔离**：验证、评分和 Harness 都在本机直接执行历史代码与候选补丁，没有容器或进程隔离，只适合可信输入。
6. **没有版本控制之外的工程设施**：CI、lint 都还没有。

## 下一步

1. 接一个真实模型适配器（`models.py`），只给 Issue、base 和工具，跑出第一条真实轨迹和 token 费用。
2. 把任务加载与 grader 从单任务泛化到 23 条，并补环境隔离。
3. 补运行时不变量测试（权限、路径、预算）。
4. 之后才是崩溃恢复、上下文 A/B（M2/M3）。

## 快速复现

```powershell
conda activate agent-harness
python scripts\prepare_swebench.py --split dev

conda activate task-marshmallow-1359
python scripts\verify_first_task.py
python scripts\grade_first_task.py --patch data\private\first-task\patch.diff
python scripts\grade_first_task.py --empty
```

`--empty` 预期返回退出码 1（`failed_tests`），其余预期通过。

最小运行时（scripted）用 Harness 环境跑：

```powershell
conda activate agent-harness
python scripts\run_first_task.py
```

预期输出 `session : finished`、`grader : passed`。
