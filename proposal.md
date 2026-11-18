# 面向代码仓库维护的 Agent Harness 与评测闭环

> 状态：M0 数据阶段基本完成，M1 闭环进行中。默认使用 Conda。原稿保存在 proposal.original.md。
> 最近更新：2026-11-18。进展细节见 [summary.md](summary.md)，路线图见 [docs/implementation-guide.md](docs/implementation-guide.md)。

## 0. 当前进展

| 阶段 | 状态 | 证据 |
|---|---|---|
| M0 数据 | 基本完成 | 23 条 Lite dev 已按 revision 固定下载，SHA256 通过；1 条任务完成本机参考答案双向验收 |
| M1 闭环 | 进行中 | 单任务候选补丁 grader 已实现并对照验证；模型循环与工具尚未实现 |
| M2 可靠性 | 未开始 | — |
| M3 实验 | 未开始 | — |
| M4 展示 | 未开始 | — |

已完成的可复现产物：`scripts/prepare_swebench.py`、`scripts/verify_first_task.py`、`scripts/grade_first_task.py`，运行记录在 `artifacts/`。尚无任何 Agent 或模型运行结果，也没有可报告的实验数字。

## 1. 项目目标

构建一个处理 GitHub Issue 的代码维护 Agent：读取问题、检索修复前代码、生成修改、运行开发测试、输出补丁和 PR 草稿。手写模型—工具循环，明确控制执行预算、权限、上下文和恢复行为。

核心研究问题：

1. 同一模型、任务和预算下，结构化摘要相比历史截断，是否提高多次运行的成功率？额外成本是多少？
2. 工具执行途中崩溃后，是否能恢复并避免重复副作用？
3. 权限是否由运行时强制执行，模型换工具或修改参数能否绕过限制？

主要成果是可复现的任务、可检查的轨迹和有对照的实验。手写循环用于展示运行时设计，不要求自行实现模型 SDK、MCP 协议栈或容器运行时。

## 2. 数据来源：首先复用真实 Issue–PR 数据

### 2.1 可直接使用的开源资源

| 来源 | 已核实内容 | 本项目用途 |
|---|---|---|
| [SWE-bench Lite 介绍](https://www.swebench.com/lite) / [下载](https://huggingface.co/datasets/SWE-bench/SWE-bench_Lite) | 300 条 test、23 条 dev，来自真实 Python 仓库问题与修复 | 首选，从 dev 开始建立流程 |
| [SWE-bench Verified](https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified) / [官方说明](https://www.swebench.com/SWE-bench/faq/) | 500 条人工筛选的测试任务 | 后续扩展；Verified 不意味着容易 |
| [SWE-bench-Live](https://github.com/microsoft/SWE-bench-Live) | 持续更新的数据、采集与评测代码 | 补充较新任务，参考自建采集流程 |

来源核实于 2026-11-13。正式实验固定数据 revision，不持续读取 main。旧资料常使用 `princeton-nlp` 命名空间，本项目统一使用上述 `SWE-bench` 来源，并记录实际版本。

我们需要的是“问题 + 修复前快照 + 验证依据”，并非单独的 Issue 文本。因此无需先写爬虫，就能开始项目。

### 2.2 一条数据包含什么

字段含义参考 [官方数据说明](https://github.com/SWE-bench/SWE-bench/blob/main/docs/guides/datasets.md)：

| 字段 | 用途 | Agent 能否看到 |
|---|---|---|
| `instance_id`、`repo` | 任务标识和仓库来源 | 能 |
| `problem_statement` | Issue 描述 | 能 |
| `base_commit` | 修复前代码快照 | 能 |
| `patch` | 原 PR 的参考代码补丁 | 不能，仅数据质检端使用 |
| `test_patch` | 原 PR 的测试补丁 | 不能，由最终 grader 应用 |
| `FAIL_TO_PASS` | 修复前失败、修复后应通过的测试 | 隐藏 |
| `PASS_TO_PASS` | 修复前后应保持通过的回归测试 | 隐藏 |
| `version`、`environment_setup_commit` | 历史环境复现信息 | 环境构建端使用 |

真实示例：`astropy__astropy-12907`，对应 [已合并 PR #12907](https://github.com/astropy/astropy/pull/12907)，修复嵌套复合模型的 separability 计算。它适合帮助理解字段关系；已经人工查看参考补丁的样本归入开发用途。

注意 `instance_id` 的数字通常是 PR 编号，不是 Issue 编号。数据未提供 Issue URL 时，通过原 PR 核实关联，不能按数字编造链接。不同 revision 的测试清单可能是 JSON 字符串或列表，适配器必须校验。

### 2.3 推荐的采样与扩展路线

1. 下载 Lite dev，先人工检查 3 条，再统计全部开发任务，筛选 5–10 条用于开发。
2. 开发流程稳定后，从未使用的 Lite test 或 Verified 中筛选 20 条，再根据可复现率扩展到 40–60 条。
3. 最后增加 Live 的冻结版本或自建的新任务。

这些数量是规划，不预先保证全部任务都可运行。Lite 和 Verified 存在重叠的可能，按 instance_id、关联 Issue/PR 和近似补丁去重，不能直接视为独立集合。报告各仓库数量、筛选规则、淘汰原因；不只保留 Agent 容易成功的任务。

公开历史数据可能已进入模型训练，本项目主要测量同一模型下 Harness 的相对影响，不声称得到无污染的模型能力评估。较新的数据也不能自动保证无污染。

### 2.4 数据质量：先证明参考修复成立

每条正式任务都必须完成：

- **修复前快照 + 测试补丁**：目标测试因业务行为失败，回归测试符合预期。
- **修复前快照 + 参考代码补丁 + 测试补丁**：目标与指定回归测试全部通过。

记录测试实际收集和执行数量、明确的用例状态、退出码、日志及环境版本。依赖安装失败、补丁冲突、测试无法收集和网络错误不算预期失败；零测试不能算通过。

任务状态：`downloaded → schema_validated → environment_ready → oracle_validated → eligible`。数据下载脚本仅完成前两项；目前只有 `marshmallow-code__marshmallow-1359` 在本机（Windows + Conda）达到 `oracle_validated`，其余任务仍停留在 `schema_validated`。下载成功不等于可复现。

### 2.5 后续如何从 GitHub 自建数据

“关闭的 Issue + 合并的 PR”只是候选，不一定构成可判分任务。建议参考 [SWE-bench-Live 采集实现](https://github.com/microsoft/SWE-bench-Live/tree/main/curation)与 [GitHub GraphQL 文档](https://docs.github.com/en/graphql/reference)：

1. 选择 1–2 个依赖和测试较易复现的 Python 仓库，人工检查少量历史修复。
2. 枚举已合并 PR，保存正文、提交、变更文件和时间，用 closing references 与 Issue 时间线确认关联，不只正则匹配 `#123`。
3. 保存来源和原始响应，冻结问题可用时间点，排除修复后评论与答案信息。
4. 确定实际修复前快照、PR head 和对应差异，保存采集时 base SHA、merge-base、head SHA、merge SHA 并区分其含义；不能把合并后的主分支当作修复前状态。
5. 拆分代码和测试补丁；squash、rebase、多 PR 修复、混合重构先人工处理或剔除。
6. 做参考答案验收，去重、冻结版本并划分开发/测试集，保留许可证和归属信息。

第一版不建设大规模爬虫。能稳定复现 10 条，比收集数千条不可执行的 Issue 更有价值。

## 3. 范围与交付阶段

| 阶段 | 产物 | 验收 |
|---|---|---|
| M0 数据 | Conda 配置、下载脚本、任务统计、人工复现记录 | 至少 1 条通过参考答案验收 |
| M1 闭环 | 模型循环、真实工具、补丁、轨迹、独立 grader | 至少 1 条真实任务由模型完成并判分 |
| M2 可靠性 | 权限、预算、持久化、故障注入、恢复 | 确定性关键场景通过 |
| M3 实验 | 截断/摘要对比、重复运行、报告、CI 门禁 | 冻结集合与配置，失败可追溯 |
| M4 展示 | MCP 搜索、PR 草稿演示、可选采集器 | 有端到端示例与复现文档 |

MVP 专注 Python bugfix。大型 feature/refactor、多 Agent、自动合并、Web 控制台和模型训练暂不做。GitHub 发布后置；离线评测用 mock。

## 4. 技术方案与 Conda 环境

### 4.1 依赖与隔离分层

- **Harness 环境**：独立 Conda，建议 Python 3.11，管理数据、模型适配、状态和报告。
- **任务环境**：每个历史仓库按指定版本构建独立依赖，可能使用不同 Python；不和 Harness 混装。
- **执行隔离**：Conda 负责依赖，不能隔离不受信代码。正式执行使用隔离 worker，例如 WSL2/Linux + 容器；参考 [SWE-bench 容器化评测指南](https://www.swebench.com/SWE-bench/guides/evaluation/)。

本机已检测到 `D:\anaconda3`，默认 Python 来自 `aitown`。使用项目独立环境，不向现有业务环境安装依赖。先在 Windows 完成数据流程，再准备正式执行环境。

### 4.2 模块结构

```text
公开任务 → 调度器 → 隔离工作区
                     ↓
CLI → Agent Runtime → ModelAdapter
           ↓
         Policy → ToolExecutor → 文件/搜索/开发测试/GitHub mock
           ↓           ↓
         EventLog + SQLite + Checkpoint + 原始输出
                     ↓
候选补丁 → 独立 Grader → results.jsonl → report.md → CI Gate
```

目标目录（`scripts/` 下的数据、验证和评分脚本已交付；`src/agent_harness/` 运行时待实现）：

```text
src/agent_harness/
  schemas.py       # Task、Action、ToolResult、SessionState
  runtime.py       # 状态机、循环、预算
  models.py        # scripted 与真实模型适配器
  tools/           # 搜索、文件、测试、GitHub mock
  policy.py        # 统一权限判定
  persistence.py   # intent、receipt、事件、checkpoint
  context.py       # 截断、摘要与预算
  evals/           # 调度、grader、指标与门禁
scripts/
configs/
data/public/       # Agent 可见
data/private/      # 原始数据和答案，Agent 不可见
data/manifests/    # revision、文件哈希与任务清单
artifacts/         # 轨迹、补丁和报告
tests/             # 关键运行时不变量
```

## 5. Harness 核心设计

### 5.1 手写循环与最小工具集

模型输出结构化工具调用或完成信号，不要求暴露隐藏思维链；允许记录简短行动说明。第一版每步一个工具，方便追踪恢复。

```text
加载或恢复状态 → 检查时间/步数/token/费用预算 → 构造上下文
→ 调用模型 → 校验 Action → 持久化工具意图 → 权限判断
→ 执行/等待审批/拒绝 → 保存结果与 checkpoint → 必要时压缩 → 继续
```

`finish` 只表示产生候选补丁，是否成功由 grader 决定。状态包含 `running / waiting_approval / completed / failed / budget_exceeded`。

最小工具为 `list_files / search_code / read_file / apply_patch / run_tests / get_diff`，后加 `draft_pr` mock。限制路径、输出、执行时间；patch 检查预期旧内容或哈希。测试工具接受注册目标，不直接开放任意 shell 字符串。测试代码本身也有执行能力，因此仍要隔离，且不传入模型密钥。

先用 scripted adapter 验证循环和工具，再接真实模型，避免将运行时 bug 误判为模型能力问题。

### 5.2 权限：检查实际操作，不能只检查工具名

运行时返回 `ALLOW / ASK / DENY`，结合工具、规范化路径、参数及已有授权：

- 工作区内普通读取与允许的代码修改自动执行并审计。
- 删除、CI 配置变更和外部发布按策略审批。
- 工作区外、隐藏评测资源和密钥目录拒绝访问。

经 patch 删除文件、修改测试配置或符号链接逃逸同样进入策略检查。审批绑定 session、call ID、参数哈希、资源范围和有效期；参数变化后重新判断。拒绝后不可执行，恢复后不可绕过。

评测使用固定 approval fixture 模拟批准和拒绝，不无限等待人工。分别记录请求、审批决定和实际执行；模型提出违规请求不等于违规副作用已经发生。

### 5.3 恢复：处理“已执行但未写 receipt”的窗口

仅在执行后写 receipt 不足以保证不重复。项目不承诺本地数据库与外部系统之间通用的 exactly-once：

1. 执行前持久化 intent：call ID、参数哈希、预期前置状态、状态。
2. 可幂等工具使用稳定幂等键；patch 记录修改前后哈希。
3. 执行后保存 receipt，在 SQLite 事务内推进本地状态。
4. 恢复遇到 pending/unknown 调用，核对真实资源：达到目标则补记，仍处于原状态则重试，状态冲突则停止报告。
5. 外部 PR 若无服务端幂等支持，利用稳定标记查询已有结果；无法确认时转人工核对，不盲目重复创建。

checkpoint 关联任务、配置、工作区身份和补丁状态。工作区丢失要么从 base + 补丁重建，要么明确不支持。故障注入覆盖执行前、执行后写 receipt 前、receipt 后 checkpoint 前。

测试失败后继续修改称“修复重试”，进程退出后续跑称“崩溃恢复”，分别验证与统计。

### 5.4 上下文策略

两组共同保留 system、原始任务、权限约束和相同的持久状态视图。淘汰时保留完整工具交互，不能拆出无对应调用的响应。

- **A 截断**：按时间淘汰旧交互，大输出只保留受限预览。
- **B 摘要**：用结构化摘要替换旧交互，保留目标、证据、已修改文件、失败尝试、未解决问题和原始日志索引。

原始输出存盘，可通过受控工具重读。摘要可能有错，不作为权限和工具执行状态的真相来源。文件状态直接核对，receipt 从数据库恢复。

使用模型 tokenizer 或标明的估算，预留输出预算；字符数只作早期近似。摘要失败回退到截断，摘要费用和延迟计入总成本。

先报告压缩触发率；任务过短就无法验证压缩效果。需要时增加单独标识的长上下文 stress 集，不混入真实任务主分数。摘要可能更慢、更贵或更差，应允许实验得到这些结论。

### 5.5 MCP 后置

本地搜索稳定后增加 stdio MCP 适配器，使用 SDK 并锁定版本，检查两种接入结果与错误处理。MCP 负责工具发现与调用，权限仍由 Harness 执行，参考 [MCP Tools 规范](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)。

## 6. 评测闭环

### 6.1 业务任务和运行时测试分开

真实任务按单文件/跨文件、仓库、类型打标签，不按预计失败模式硬凑互斥 L1–L4。

另外维护确定性的运行时测试：崩溃、超时、模型格式错误、状态重建，以及批准、拒绝、无须审批、参数变化、工具绕过。可以使用合成小仓库和 scripted adapter，其成绩不能冒充真实 Issue 修复率。

### 6.2 独立 grader 与防泄漏

Agent 只访问 base 快照和公开任务，不访问原始数据、参考补丁、隐藏测试、未来 git 历史和网上答案。private 放在另一个目录不等于隔离，执行工作区必须不挂载这些资源，工具也不能越界。

候选补丁在全新的 grader 工作区应用，再应用受保护的隐藏测试。检查目标与回归测试的实际状态及执行数量，参考 [SWE-bench 判分实现](https://github.com/SWE-bench/SWE-bench/blob/main/swebench/harness/grading.py)。

不要求候选补丁与参考补丁一致，也不把“改了指定文件”当正确性条件。模型可以写开发测试，但不能改变最终 grader 的断言。

结果分类为 `resolved / unresolved / agent_error / infra_error / invalid_task / policy_violation`。冻结集合中的计划 trial 不静默删除；基础设施错误单列，并保留重跑前后记录与分母口径。功能与合规分别报告，另给两者都满足的成功率。

### 6.3 指标

设 N 个任务，每个 k 次独立 trial，y(i,j) 为是否成功：

- `pass@1 = sum(y(i,j)) / (N*k)`：以重复 trial 均值估计单次成功率，报告明确口径。
- `all_pass_4 = sum_i product_j y(i,j) / N`，k=4：实测四次全部成功的任务比例，描述 pass^4 可靠性；不是把总体 pass@1 直接四次方。
- 成本：输入、输出、摘要 token，费用、耗时、工具调用数；分别报告全部与成功 trial。
- 恢复：恢复执行率、恢复后完成率、重复副作用数，与未注入情况配对比较。
- 权限：应审批却绕过、不应审批却误触发、拒绝后仍执行，分别使用对应机会数作分母。
- 上下文：压缩触发率、次数、耗时、摘要错误和超预算率。

pass@k 指至少一次成功，pass^k 指全部成功，概念参考 [Agent 评测实践](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)。本项目主要关注单次成功与一致性。

每个 trial 独立工作区、session 和模型历史。固定模型版本、prompt、预算、工具与任务 revision，记录随机参数和供应商支持情况。按任务配对比较，给任务级 bootstrap 区间；仓库内相关性另做分组敏感性分析。小样本只作探索，不凭单个任务宣称显著提升。

### 6.4 费用与 CI

先用 3–5 条单次 pilot 测量成本：

`计划费用 ≈ 任务数 × 重复数 × 策略数 × 平均单次费用`。

例如 40 × 4 × 2 = 320 次运行，仅为工作量示例，费用还包含数据复现和重试。设置单次与整批费用上限，超限保留失败记录。

每次提交运行不付费的工具、权限、恢复、指标和 scripted 检查；真实模型评测定时或手动运行。权限违规执行为硬门禁；质量指标使用冻结基线与预声明容忍范围，不能用有波动的单次分数机械比较。模型、数据、预算变化后建立新基线。

LLM Judge 不进入 MVP，后续仅用于可读性等辅助指标并人工校准，不替代可执行测试。

## 7. 实施顺序与最终交付

详见 [逐步实施指南](docs/implementation-guide.md)：

1. ✅ Conda 和数据下载，理解字段并隔离答案。
2. ✅ 人工复现一条真实任务，验证 base 失败、参考修复通过；已脚本化。
3. 🚧 工具和 scripted 循环，再接真实模型与独立 grader（单任务 grader 已完成，循环未开始）。
4. 权限、持久化、崩溃注入及恢复。
5. 冻结任务集，pilot 后做上下文 A/B 与重复评测。
6. MCP、PR 草稿演示和复现文档。

最终提交任务清单与来源、revision 和哈希、环境配方、运行命令、原始轨迹、候选补丁、统计报告、失败分析和端到端演示。

报告写成：“在 [任务 revision]、[模型]、[预算] 下，A 为 [实测]，B 为 [实测]，差异区间为 [实测]，主要失败类型为 [证据]。”数字实验前留空，不将原稿示例成绩当作结果。
