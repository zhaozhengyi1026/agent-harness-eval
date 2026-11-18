# 当前进展

> 最后更新：2026-11-18。设计细节见 [proposal.md](proposal.md)，分步路线见 [docs/implementation-guide.md](docs/implementation-guide.md)，第一条任务的完整记录见 [docs/first-task.md](docs/first-task.md)。

## 一句话状态

数据链路已经打通，并有一条真实任务通过了“修复前失败、参考修复后通过”的本机验收；候选补丁的评分器也已经能独立判分。**Agent 本身还没写**：没有模型调用、没有工具循环、没有实验数字。

## 阶段进度

| 阶段 | 状态 | 说明 |
|---|---|---|
| M0 数据 | 基本完成 | 23 条 dev 已按 revision 固定下载，哈希校验通过；1 条任务达到 `oracle_validated` |
| M1 闭环 | 进行中 | 单任务 grader 可用；模型适配器、工具、轨迹、循环均未实现 |
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

## 脚本

| 脚本 | 作用 | 状态 |
|---|---|---|
| [scripts/prepare_swebench.py](scripts/prepare_swebench.py) | 固定 revision 下载、字段校验、public/private 拆分、写 manifest | 可用 |
| [scripts/verify_first_task.py](scripts/verify_first_task.py) | 用参考答案验证任务：base 失败 → 参考修复通过 | 可用，仅本任务 |
| [scripts/grade_first_task.py](scripts/grade_first_task.py) | 给候选补丁打分，不回放参考代码补丁 | 可用，仅本任务 |

两个脚本都用 `git archive` 从 base 提交导出全新快照，不会改动 `data/workspaces/` 里的现有 checkout。

## 已知问题

1. **数据缺陷**：`PASS_TO_PASS` 中有 8 个参数化测试 ID 被截断（缺结尾的 `]` 和参数后半段）。脚本用“唯一前缀匹配”补全并记录映射；无法唯一匹配就报错。原始数据未修改，也不能声称完全原样使用官方数据。
2. **checkout 已“改脏”**：`data/workspaces/marshmallow-1359` 里残留人工验证时应用的 `test_patch` 和参考 `patch`，`git status` 显示两个文件被修改。它只作为 `git archive` 的来源，不能当“修复前代码”复用；恢复用 `git restore .`。
3. **脚本是单任务硬编码**：任务 ID、测试数量（1 + 76）、收集器路径、`src/marshmallow/*.py` 白名单都写死，不能直接用于其他任务。
4. **没有隔离**：验证和评分都在本机直接执行历史代码与候选补丁，没有容器或进程隔离，只适合可信输入。
5. **没有版本控制**（本次已初始化）和 CI；根目录此前也没有 README。

## 下一步

1. 实现最小 Harness：读 public 任务 → 建修复前工作区 → 文件/搜索/改代码/跑测试工具 → scripted 动作走通 → 输出候选补丁 → 交给 grader。
2. 接一个真实模型适配器，产生第一条真实轨迹和费用数据。
3. 把 grader 从单任务泛化到 23 条，并补环境隔离。
4. 之后才是权限、崩溃恢复、上下文 A/B（M2/M3）。

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
