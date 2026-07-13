# `run_codex_batch.sh` 使用教程与流程说明

本文档说明当前批处理脚本：

- 脚本：`batch/run_codex_batch.sh`
- 目标：按 `target.txt` 逐行调度 Codex，串行执行任务，记录状态、会话轨迹与可读 trace，支持超时终止与会话复用。

## 1. 快速开始

1. 准备目标文件（JSONL，一行一个 JSON）。
2. 执行批处理。
3. 查看 `batch/runs/<batch_id>/summary.json` 与 `.codex/state/task_state.json`。

示例：

```bash
cd /absolute/path/to/apdv1-mcp-full-bundle/apdv1
bash batch/run_codex_batch.sh
```

指定目标文件：

```bash
bash batch/run_codex_batch.sh /path/to/targets.jsonl
```

指定超时时间（每个任务）：

```bash
TIMEOUT_MINUTES=50 bash batch/run_codex_batch.sh
# 或
TIMEOUT_SECONDS=3000 bash batch/run_codex_batch.sh
```

关闭终端也可持续运行（后台执行并输出日志）：

```bash
cd /absolute/path/to/apdv1-mcp-full-bundle/apdv1
nohup bash batch/run_codex_batch.sh >batch/nohup_batch.log 2>&1 &
echo $! >batch/nohup_batch.pid
```

实时查看后台日志：

```bash
tail -f batch/nohup_batch.log
```

## 2. 输入格式

默认输入文件：`batch/target.txt`

规则：

- 每行一个 JSON 对象。
- 必须包含 `url` 且非空。
- 可包含任意额外字段（如 `license_key`、`addition` 等）。
- 批处理会自动补充并强制 `delivery_mode="portable-deliverable"`，因此每个目标都会直接构建 final portable bundle，并只执行最终 portable audit。
- 空行和以 `#` 开头的行会被跳过。

示例：

```json
{"url":"https://docs.octobercms.com/4.x/setup/installation.html#minimum-system-requirements","license_key":"SHAGU-ZCN4U-PTDVZ-5PAOO"}
{"url":"https://example.com/another-target","addition":"info","delivery_mode":"portable-deliverable"}
```

## 3. 运行产物与目录

每次运行会创建：

- `batch/runs/<batch_id>/`
  - `task-001/`
    - `prompt.txt`：发送给 Codex 的任务提示词
    - `codex.log`：Codex 标准输出日志
    - `last_message.txt`：最后回复
    - `session`：提取出的 `session_id`
    - `session_path`：绑定到的本地 rollout JSONL 源文件
    - `trajectory.jsonl`：镜像到任务目录的完整 rollout 轨迹
    - `trace.txt`：从 rollout 增量渲染的可读流程
    - `trace.offset`：trace 渲染进度
    - `trace.pid`：后台观测进程 PID
    - `agents/`：已拉起子 agent 的独立 rollout 镜像
      - `<role-or-nickname>/trajectory.jsonl`
      - `<role-or-nickname>/trace.offset`
      - `<role-or-nickname>/session_path`
  - `summary.json`：本批次统计
  - `batch/results/<batch_id>/`
    - `success.txt`
    - `conditional_success.txt`
    - `failure.txt`

结果文件每条任务会记录：

- `status/result/rc/url`
- `target_json=<原始目标JSON>`（包含 `license_key` 等 extras，便于追溯输入与结果对应关系）
- 如有风险会追加 `warning=...` 行

状态文件：

- 当前状态：`.codex/state/task_state.json`
- 当前历史：`.codex/state/task_history.jsonl`
- 可读状态总览：`.codex/state/STATUS.md`
- 历史归档/清理备份：`.codex-backups/`

## 4. 批次开始前的状态归档与重置

每次批处理开始前，脚本会自动：

1. 将旧状态文件归档到 `.codex/state/archive/`：
   - `task_state.<batch_id>.json`
   - `task_history.<batch_id>.jsonl`
2. 清空旧状态上下文并开始新批次状态写入。

长期历史和清理前备份会定期移到 `.codex-backups/`，live `.codex/state` 只保留当前运行所需状态。

## 5. 状态机与写入职责

状态写入采用混合所有权：

- Agent 写：`RUNNING`、`COMPLETED_SUCCESS`、`COMPLETED_CONDITIONAL_SUCCESS`、`COMPLETED_FAILED`
- Runner 写：`INITIALIZING`、`STARTING`、`TIMED_OUT`、`ABORTED`、`IDLE`

典型状态序列：

- `INITIALIZING -> STARTING -> RUNNING -> COMPLETED_SUCCESS -> IDLE`
- `INITIALIZING -> STARTING -> RUNNING -> COMPLETED_CONDITIONAL_SUCCESS -> IDLE`
- 或 `INITIALIZING -> STARTING -> TIMED_OUT -> IDLE`

Runner 判定原则：

- Agent 终态是业务结果唯一来源；runner 不覆盖 agent 的业务终态。
- 若 agent 没有写终态且发生超时（`rc=124/137`），runner 写 `TIMED_OUT`。
- 若 agent 没有写终态且非超时异常退出，runner 写 `ABORTED`。
- 若出现一致性风险（例如 agent 写成功但进程返回非零，或 conditional success 缺少原因字段），runner 仅记录 warning，不改写业务终态。
- 若 agent 写成功/条件成功但 final 输出或 audit 结构化校验失败，runner 会降级为 `COMPLETED_FAILED` 并写入 `final_output_validation.json`。
- 任务最终失败、超时或中止时，runner 会删除当前项目在 `Deliverable/` 下的交付产物目录，避免污染后续批次；`DP_LOGS/` 会保留用于排错。

主流程与 final portable bundle 委派要求：

- 批处理任务已显式授权使用 `spawn_agent`。
- 批处理任务固定为 `delivery_mode=portable-deliverable`。
- 主 agent 使用官方流程信息作为辅助输入，快速构建 final bundle 所需的 `Dockerfile`、`docker-compose.yml`、`docker/entrypoint.sh`、脚本、source/DB 快照和验证逻辑。
- portable 模式不再要求单独完成 local-run deployment audit。
- final bundle 构建/验证成功后，只委派 `portable_bundle_auditor` 做最终审计门。
- 默认由主 agent 构建 final bundle；必须委派 `portable_bundle_auditor` 做最终审计门。
- 显式请求镜像交付时，使用 `post-deploy-image-bundle` 生成 `Deliverable/<project>-image-final/`。

三分类结果映射：

- `success`：`COMPLETED_SUCCESS`
- `conditional_success`：`COMPLETED_CONDITIONAL_SUCCESS`
- `failed`：`COMPLETED_FAILED` / `TIMED_OUT` / `ABORTED`

结果 warning（写入结果文件与 `summary.json`）：

- `runner_rc_nonzero_after_agent_terminal`：agent 已写成功/条件成功，但进程退出码非 0。
- `missing_conditional_metadata`：`COMPLETED_CONDITIONAL_SUCCESS` 缺少 `conditional_reason` 或 `blocking_requirement`。

## 6. 超时与进程终止

单任务命令由以下结构执行：

```bash
timeout -k 10s "${TIMEOUT_SECONDS}s" codex exec --dangerously-bypass-approvals-and-sandbox ...
```

含义：

- 主超时：`TIMEOUT_SECONDS`（默认 50 分钟 / 3000 秒）。
- 到时先发 `TERM`。
- 10 秒未退出再发 `KILL`。
- Codex 调用附带 `--dangerously-bypass-approvals-and-sandbox`，用于批处理全自动执行。

重试边界：

- runner 默认不自动重跑整个 target，避免重复消耗和覆盖已生成证据。
- 部署/修复重试由主 agent 在单个任务内完成，默认预算见 `.codex/workflow.toml` 的 `max_deploy_attempts`。
- 审计失败重试由主 agent 修复后重跑 auditor，默认 `max_audit_attempts=3`。
- app-server 启动失败有轻量启动重试；这不是业务 target 重试。

任务后置补杀：

- 脚本会按当前任务唯一标记（`task-xxx.last_message.txt`）扫描并补杀残留相关进程树。

## 7. Docker 项目范围资源清理

每个 URL 任务结束后（无论成功/失败/超时/中止），runner 只清理当前任务登记的项目范围 Docker 资源。

- agent 在确定项目名后应写入 state：
  - `project_name=<resolved_project_name>`
  - `cleanup_project_names=<comma-separated compose project names>`
- runner 只删除匹配 `com.docker.compose.project=<name>` 或 `codex.apdv1.cleanup_project=<name>` 标签的容器、网络、卷和任务构建镜像。
- 非 compose 的 Docker 资源需要在创建时显式加 `codex.apdv1.cleanup_project=<project_name>` 标签，否则 runner 不会猜测性删除。
- 不执行 `docker system prune`、全局 `docker stop/rm`、全局网络/卷/镜像 prune 或 builder cache prune。
- 如果没有登记 cleanup project，runner 会跳过 Docker 清理并在 `docker_cleanup` 中记录缺少项目范围，不会退回全局清理。
- 失败产物清理只删除 `Deliverable/<project>`、`Deliverable/<project>-final`、`Deliverable/<project>-image-final` 这类当前项目直接子目录，不会清空整个 `Deliverable/`。

## 8. 会话复用（resume）

每任务日志会提取 `session id`，保存到：

- `batch/runs/<batch_id>/task-xxx/session`

继续执行示例：

```bash
codex exec resume "$(cat batch/runs/<batch_id>/task-001/session)" "continue fixing"
```

## 9. 并发控制

脚本使用文件锁：

- `.codex/state/batch.lock`

同一时刻只允许一个批次运行。若有正在运行的批次，会直接报错退出。

## 10. 常用检查命令

查看当前状态：

```bash
jq '{status,batch_id,task_id,result,exit_code,message,docker_cleanup}' .codex/state/task_state.json
```

查看最近批次目录：

```bash
ls -1dt batch/runs/* | head
```

实时看某任务日志：

```bash
tail -f batch/runs/<batch_id>/task-001/codex.log
```

实时看某任务可读流程：

```bash
tail -f batch/runs/<batch_id>/task-001/trace.txt
```

## 11. 注意事项

- 批处理每个任务结束只清理已登记的项目范围 Docker 资源；任务脚本必须使用稳定的 compose project 名并写入 `cleanup_project_names`，否则 runner 会跳过 Docker 清理。
- 若目标任务自身流程会多次部署 final bundle 进行修复和复验，这是预期行为，不是重复调度。
- 当前 portable 设计已融合官方流程部署与 portable bundle 阶段：官方信息用于指导 final bundle 构建，交付和审计只针对 final bundle。
- 默认 50 分钟预算需要覆盖 final bundle 构建、便携包迁移验证和最终审计；慢启动阶段优先安静等待，不要过早把“慢”当成“卡死”。
- 观测数据完全由 runner 和辅助脚本负责读写，agent 不参与 `trajectory.jsonl` / `trace.txt` 的生成。
- `trace.txt` 会聚合 parent 和已发现 child agent 的流程，并在每行标注来源 agent。
- 成功项目应在 `summary.md` 里包含 `Quick Restart Verification`（2-3 条可复制命令）。
