# agent-harness-eval

面向代码仓库维护的 Agent Harness 与评测闭环：让 Agent 读 GitHub Issue、在修复前的代码快照上检索与修改、运行测试，最后由独立的 grader 判分。

当前状态：**数据链路与最小运行时已打通，单任务评分器可用，尚未接模型**。详见 [summary.md](summary.md)。

## 已完成

- 固定 revision 下载 SWE-bench Lite `dev`（23 条，6 个仓库），校验字段、拆分 public/private、记录 SHA256。
- 选 `marshmallow-code__marshmallow-1359` 完成本机双向验收：修复前目标测试失败、76 条回归通过、应用参考修复后 77 条全部通过。
- 实现候选补丁评分器：参考补丁通过、空修改判失败、测试补丁被白名单拒绝。
- 实现最小运行时并用预设动作跑通：全新工作区、7 个受限工具、参数级权限判定、JSONL 轨迹、补丁产出、交给 grader 判分。

没有任何模型运行结果，也没有实验结果。`scripts/run_first_task.py` 是 scripted 冒烟测试，不是模型能力证据。

## 目录

```text
proposal.md                     设计稿（研究问题、数据、Harness 设计、指标）
summary.md                      当前进展快照
docs/first-task.md              第一条任务的完整证据链
docs/harness-design.md          最小运行时的设计原因与踩坑记录
docs/implementation-guide.md    分步实施与验收
src/agent_harness/              最小运行时（schemas、workspace、policy、tools、runtime）
scripts/prepare_swebench.py     下载并拆分数据
scripts/verify_first_task.py    用参考答案验证任务
scripts/grade_first_task.py     给候选补丁打分
scripts/run_first_task.py       scripted 跑通运行时并调用 grader
data/                           数据与源码 checkout（不入库，可重新生成）
artifacts/                      每次运行的日志与结果（不入库）
```

## 环境

两个 Conda 环境，互不混装：

| 环境 | Python | 用途 |
|---|---|---|
| `agent-harness` | 3.11 | 数据脚本、未来的 Harness |
| `task-marshmallow-1359` | 3.7.16 | 运行历史版本的 marshmallow 与其测试 |

```powershell
conda env create --file environment.yml
conda activate agent-harness
```

## 快速开始

```powershell
# 1. 下载 dev 数据
conda activate agent-harness
python scripts\prepare_swebench.py --split dev

# 2. 取第一条任务的修复前代码（只做一次）
git clone https://github.com/marshmallow-code/marshmallow.git data\workspaces\marshmallow-1359
git -C data\workspaces\marshmallow-1359 checkout --detach b40a0f4e33823e6d0f341f7e8684e359a99060d1

# 3. 用参考答案验证任务
conda activate task-marshmallow-1359
python scripts\verify_first_task.py

# 4. 给候选补丁打分
python scripts\grade_first_task.py --patch data\private\first-task\patch.diff
python scripts\grade_first_task.py --empty   # 预期失败，退出码 1

# 5. scripted 跑通最小运行时并交给 grader
conda activate agent-harness
python scripts\run_first_task.py             # 预期 session: finished / grader: passed
```

`data/` 与 `artifacts/` 被 `.gitignore` 忽略：数据可由脚本按 revision 重新生成，运行产物保留在本地。

## 注意

- `data/private/` 含参考答案与隐藏测试清单，Agent 运行时必须不可见。
- 当前验证、评分与运行时都在本机直接执行历史代码，没有容器隔离，只适合可信输入。
- 脚本与运行时只支持这一条任务，任务 ID、测试数量和白名单都是硬编码的。
- 判分依据是测试的真实执行结果，不要求候选补丁与参考补丁一致。
- `run_first_task.py` 的动作与补丁是预设的，只验证运行时，不代表模型能力。

## 参考

- [SWE-bench](https://www.swebench.com/) / [SWE-bench_Lite](https://huggingface.co/datasets/SWE-bench/SWE-bench_Lite)
- [SWE-bench 评测指南](https://www.swebench.com/SWE-bench/guides/evaluation/)

仓库：<https://github.com/zhaozhengyi1026/agent-harness-eval>
