# 第一条开发任务：marshmallow-1359

## 已确认的数据

- 数据源：SWE-bench/SWE-bench_Lite，dev，23 条任务。
- 数据 revision：`b0dde1093fe417d83b7184254edf8199c1f0dff5`。
- 本地 public 与 private 文件 SHA256 均与 manifest 一致。
- instance_id：`marshmallow-code__marshmallow-1359`。
- 仓库：https://github.com/marshmallow-code/marshmallow
- Issue：https://github.com/marshmallow-code/marshmallow/issues/1357
- 已合并修复 PR：https://github.com/marshmallow-code/marshmallow/pull/1359
- 修复前 base：`b40a0f4e33823e6d0f341f7e8684e359a99060d1`。
- 数据中的 version：`3.0`；不等于要求从 PyPI 安装最新版 marshmallow。
- 目标测试：`tests/test_fields.py::TestParentAndName::test_datetime_list_inner_format`。
- 指定回归测试：76 个，完整列表在 private oracle 中。

PR 正文明确关联 Issue #1357。PR 编号和 Issue 编号不同。

## 要修复什么

将 DateTime 放入 List 或 Tuple 内部时，初始化 Schema 会报错；预期是容器中的日期时间字段能够正常初始化并使用配置的格式。

Issue 提供的最小复现：

```python
from marshmallow import fields, Schema

class MySchema(Schema):
    times = fields.List(fields.DateTime())

s = MySchema()
```

报告中的错误是 `AttributeError: 'List' object has no attribute 'opts'`。2026-11-14，用户在 `task-marshmallow-1359` 环境运行上述代码，提供的 traceback 与该错误一致，指向 `fields.py:1117`。最小复现、目标测试和回归测试均已验证，见下文“自动重复验证”。

已从本地 oracle 导出原始补丁（UTF-8、无 BOM）：

- `data/private/first-task/test_patch.diff`：测试改动。
- `data/private/first-task/patch.diff`：参考业务代码改动。

人工验证进展（用户报告）：

- Python 3.7.16，pytest 7.4.4，Windows；任务环境 `task-marshmallow-1359`。
- 仅应用 test_patch：目标测试执行 1 条并失败，报 `AttributeError: 'Tuple' object has no attribute 'opts'`，与容器嵌套字段的同一问题一致。
- 再应用参考 patch：用户确认目标测试通过。
- `python -m pytest -q tests/test_fields.py`：用户确认全部通过，具体通过数量未提供。

目标与回归清单的精确自动验证和原始日志由下述脚本补齐；用户的人工结果不冒充脚本实测结果。

## 自动重复验证

项目根目录、任务环境中执行：

```powershell
conda activate task-marshmallow-1359
python scripts/verify_first_task.py
```

脚本从 git 的 base 创建新快照，不修改现有 checkout；通过 PYTHONPATH 和导入路径校验确保测试使用新快照，而不是现有 editable 安装。先应用测试补丁，检查目标测试按预期失败、76 个指定回归测试通过，再应用参考代码补丁，检查 77 个指定测试全部通过。拒绝零测试、skip 和收集错误；失败必须包含预期 AttributeError。

每次产生独立 `artifacts/first-task/verify-*/`，保存工作区、补丁、依赖列表、3 份日志、JUnit XML 与 result.json。通过后状态为 `oracle_validated_local`，表示本机参考修复验收，不等于官方容器评测或 Agent 修复成功。当前脚本仅针对这条开发任务，不是通用 grader。

2026-11-14 自动实测通过，报告：`artifacts/first-task/verify-0pcb_i9r/result.json`。

| 检查 | 结果 |
|---|---|
| 修复前目标测试 | 1 条，按预期因 AttributeError 失败 |
| 修复前指定回归测试 | 76 条全部通过 |
| 参考修复后目标与回归 | 77 条全部通过 |

数据清单中有 8 个参数化测试 ID 在空格前被截断，最初直接调用 pytest 时无法定位。脚本现先收集完整 nodeid，仅对缺失右方括号的参数化 ID 进行唯一前缀匹配；缺失、歧义或重复映射均报错。完整映射保存在 result.json，不修改原始数据。最初失败记录保留在 `artifacts/first-task/verify-myj8za4j/`，不计为 bug 修复失败。

## 人工操作记录：准备修复前代码（已完成）

在项目根目录运行以下命令。若目标目录已经存在，先检查内容，不覆盖或删除。

```powershell
New-Item -ItemType Directory -Force data\workspaces
git clone https://github.com/marshmallow-code/marshmallow.git data/workspaces/marshmallow-1359
git -C data/workspaces/marshmallow-1359 checkout --detach b40a0f4e33823e6d0f341f7e8684e359a99060d1
git -C data/workspaces/marshmallow-1359 rev-parse HEAD
git -C data/workspaces/marshmallow-1359 status --short
```

验收：HEAD 为上述 base，status --short 无输出。这里只下载和定位源码，不安装依赖，不运行代码。

该完整 git clone 仅用于人工开发复现。之后 Agent 的正式运行工作区必须移除未来历史、remote 和答案访问能力，不能直接复用完整克隆。

注意：这份 checkout 在人工验证中被应用过 `test_patch.diff` 和 `patch.diff`，`git status` 会显示 `src/marshmallow/fields.py` 与 `tests/test_fields.py` 已修改，它已不是“修复前代码”。两个脚本都用 `git archive` 从 base 提交重新导出快照，因此不受影响；若要恢复干净状态，执行 `git -C data/workspaces/marshmallow-1359 restore .`。不要把这份工作区直接当作 Agent 的起点。

## 后续工作

本条任务已完成本机参考修复双向验证；下载 manifest 的 schema_validated 状态仍表示原始数据的结构校验，执行状态以独立 result.json 为准。该样本用于开发教学，不计入未见测试集，也不代表官方容器评测完成。

下一步实现公开任务加载、受控文件工具与 scripted 模型循环；随后让真实模型产生候选补丁，独立 grader 只使用候选补丁和隐藏测试，不能使用参考代码 patch。当前参考验证脚本会读取答案，不能直接当作 Agent 评测器。

## 候选补丁评测器

已增加 `scripts/grade_first_task.py`，仅评测本条任务。它接受指定候选补丁，在新的 base 快照上应用受保护的 test_patch 和候选代码修改，再执行 77 个指定测试；不会自动应用 oracle 中的参考代码 patch。候选修改目前只允许 `src/marshmallow/` 内的 Python 文件。

```powershell
conda activate task-marshmallow-1359
# 正向自检：显式将已知正确的参考修复作为候选输入。
python scripts/grade_first_task.py --patch data/private/first-task/patch.diff
# 反向自检：不修改业务代码，应该判失败、返回退出码 1。
python scripts/grade_first_task.py --empty
```

实测：参考补丁为 passed（77 个测试全部通过），空修改为 failed_tests。产物分别为 `artifacts/candidate-grading/grade-usl6kyc1/`、`artifacts/candidate-grading/grade-jippbns1/`。

结果区分 passed、failed_tests、invalid_patch、test_execution_error、grader_error，保存补丁来源/哈希、测试名称修正、日志和依赖。退出码 0 表示通过，1 表示候选失败或无效，2 表示评测执行异常。

这是可信本地代码的开发评测器，没有进程/网络隔离，不能用于运行不受信模型补丁的正式安全评测。读取完整 private 记录发生在 grader 端，未来 Agent 端仍必须隔离。下一步是实现产生候选补丁的最小工具与循环。
