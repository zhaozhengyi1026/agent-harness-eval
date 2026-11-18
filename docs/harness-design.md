# 最小 Harness 设计说明：为什么这样写

这份文档解释 `src/agent_harness/` 里每个决定背后的原因，配合 `scripts/run_first_task.py` 的实测结果看。它不是 API 文档，而是“为什么不是另一种写法”。

## 1. 先用 scripted 模型，再接真实模型

`models.py` 没有写在这里，`ScriptedModel` 直接在 `runtime.py` 里，只有十几行：按固定顺序吐出 `Action`。

原因：**运行时 bug 和模型能力问题是两种失败**。如果第一版就接模型，跑失败了无法判断是工具写错、权限误拦、上下文拼错，还是模型不会做。用预设动作先跑通，等于先把“机械部分”变成可信基座；之后接模型，失败才有解释力。

这也决定了 scripted 跑出的成绩**不能算解决率**，它只验证运行时，不验证智能。

## 2. 工作区：从提交历史导出，而不是复制现有目录

`workspace.create_snapshot()` 做三件事：

1. `git archive <base_commit>` 从仓库导出该提交的完整文件树——**不含 `.git`**；
2. 解压到全新目录，并逐个校验成员路径不越界（防 zip slip）；
3. 在新目录里 `git init` + 一次提交 `base snapshot`。

为什么不直接复制 `data/workspaces/marshmallow-1359`：

- 那份 checkout 被人工验证改过（见 `docs/first-task.md`），复制等于把答案带进去；
- 里面有完整 git 历史，Agent 可以 `git log` 看到未来提交，等于泄题；
- 有 remote，Agent 可以 `git fetch` 拿到官方修复。

为什么不干脆不要 git：Agent 和 grader 都需要 `git diff` 取补丁、`git apply` 应用补丁；而且“一个只有 base 提交的干净仓库”本身就是对 Agent 的最小化环境。**没有历史、没有 remote、只有一个起点**，这是设计出来的，不是顺手。

### 踩到的两个坑（都是真实教训）

- `tempfile.mkdtemp()` 在 Windows 上创建的目录，其 ACL 会让子进程 `git` 无法写入（`Permission denied`）。改用普通 `mkdir` + 随机后缀。教训是：**沙箱/权限环境下，目录的创建方式会影响子进程能否写**。
- 工作区如果嵌在**另一个 git 仓库**里（项目根现在就是仓库），`git apply` 会把补丁路径当成“当前目录前缀之外”而跳过，输出 `Skipped patch`，退出码却是 0。于是测试补丁没打上、测试清单对不上。解法是让快照自己成为一个仓库（第 3 步）。教训是：**`git` 会在父目录里找仓库，行为随所在目录变化，必须让工作区自包含**。

## 3. 工具：窄接口，不给 shell

`tools.py` 只有 7 个工具：`list_files / search_code / read_file / apply_patch / run_tests / get_diff / finish`。

- **不给任意 shell**：`run_tests` 只接受 `tests/...` 形式的测试 node id，不接受 `-k`、`--`、管道、多个命令。测试代码本身能执行任意逻辑，所以工具再宽就等于把执行权交出去。
- **`apply_patch` 只接受 diff 文本**：不提供“写整个文件”，因为整文件覆盖无法审计、也无法做路径前缀检查；diff 可以先 `--check` 再落地，失败能拿到结构化错误。
- **工具错误返回 `ToolResult(ok=False)`，不抛异常**：模型（或 scripted 策略）需要看到“补丁打不上”这类反馈才能纠正。把异常炸到循环外，等于放弃了重试的机会。
- **输出一律截断**：`read_file` 默认 200 行、搜索最多 40 条、命令输出只留尾部，避免单次工具调用把上下文撑爆。

## 4. 权限：在参数层面判定，不信任工具名

`policy.py` 返回 `ALLOW / ASK / DENY` 三元，判定依据是**工具 + 规范化后的参数**：

| 场景 | 判定 | 原因 |
|---|---|---|
| 工作区内读文件 | ALLOW | 只读、无副作用 |
| 读 `../data/private/...` | DENY | 路径解析后在工作区外 |
| patch 改 `src/*.py` | ALLOW | 允许修业务代码 |
| patch 改 `tests/` | DENY | 改测试就等于改评分标准 |
| patch 删文件 | ASK | 破坏性操作要审批 |
| `run_tests` 用 `-k`/`--`/任意命令 | DENY | 只放开注册过的测试选择器 |
| 未知工具 | DENY | 白名单，不是黑名单 |

几个容易忽略的点：

- 判定在**执行之前**，被拒绝的动作没有任何副作用，日志里记 `decision=deny, output="not executed"`。
- 拒绝**不终止循环**，会话继续。真实场景里模型可能换个方式重试，正好可以观察它是否试图绕过。
- `ASK` 在 scripted 里等于“没有审批人 → 不执行”，这是刻意的：脚本跑通阶段不该出现无人值守的审批等待。
- 权限判定器不读 prompt。**模型说“我不会删文件”和权限系统没有关系**，这是这个项目要证明的事情之一。

## 5. 循环：单步单工具、有预算、全量留痕

`runtime.py` 的循环刻意做得很笨：

```text
取下一个 Action → 权限判定 → 拒绝则记日志继续 / 允许则执行 → 记事件 → finish 则结束
```

- **每步只做一个工具调用**：为将来“崩溃恢复”铺路——一步一个意图，天然对应一条 intent/receipt。
- **`max_steps` 预算**：现在写死 20，超了记为 `budget_exceeded`，这是将来实验里“预算相同”的雏形。
- **`finish` 只代表“我交了补丁”**，不代表成功。成功与否只有 grader 说了算。
- **轨迹是 JSONL**：一行一个事件，追加写入，崩溃了也能看到断点。这是恢复功能的前置条件。

## 6. 评测：grader 独立、绝不放水

`scripts/grade_first_task.py` 和 harness 完全是两条路径：

- 它自己从 `base_commit` 重建工作区，**不信任 Agent 的工作区状态**；
- 它只应用两样东西：隐藏的 `test_patch` + Agent 的候选补丁；
- **它从不自动应用参考 `patch`**——参考补丁只在自检时作为“候选输入”喂进去；
- 候选补丁先过 `--numstat` 检查：必须只改 `src/marshmallow/*.py`，否则 `invalid_patch`；
- 结果分成 `passed / failed_tests / invalid_patch / test_execution_error / grader_error`，并区分退出码 0/1/2。

三组对照是这一层的“单元测试”：

| 输入 | 期望 | 为什么必须测 |
|---|---|---|
| 参考补丁 | passed | 证明正向链路没有系统性错误 |
| 空修改 | failed_tests | 证明判分不是恒真 |
| 测试补丁当候选 | invalid_patch | 证明改测试骗分这条路被堵死 |

## 7. 这次实测结果

`scripts/run_first_task.py`（scripted）在 `artifacts/harness/first-task/run-43c90c62/`：

| 事实 | 值 |
|---|---|
| 会话状态 | `finished`，10 步 |
| 被拒动作 | 2（路径逃逸读、改测试） |
| 工具错误 | 0 |
| 候选补丁 | 489 字节，只改 `src/marshmallow/fields.py` 一行 |
| 独立 grader | `passed`（77 个测试通过） |

这证明的是：**从建工作区到独立判分的整条机械链路通了**。它不证明模型会修 bug，因为动作用的是预设序列，补丁内容也是照参考答案写的。

## 8. 现在还没有的

- 没有容器/进程隔离：历史代码和候选补丁都在本机直接跑，只适合可信输入。
- 没有 SQLite 状态、没有 intent/receipt、没有检查点：崩溃恢复还无从谈起。
- 没有上下文管理与压缩：现在是一问一答式 scripted，没有长历史。
- 没有模型适配器：下一步才接。
- 单任务硬编码：任务 ID、测试数量、`src/marshmallow` 白名单都写死在脚本里。

## 9. 接下来按这个顺序

1. 接一个真实模型适配器（`models.py`），只给它 Issue、base 和工具，跑出第一份真实轨迹与费用。
2. 把任务加载和 grader 泛化到 23 条，并补环境隔离。
3. 再做 M2：intent/receipt、故障注入、恢复；最后才是 M3 的上下文 A/B。
