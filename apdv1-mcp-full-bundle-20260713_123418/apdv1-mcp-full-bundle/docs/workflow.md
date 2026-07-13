# 工作逻辑

本文说明 APDv1 MCP 完整交付包从 MCP 调用到部署执行的完整链路。

## 总体链路

```text
MCP 客户端 / IDE / Agent
        |
        | stdio MCP
        v
scripts/start-mcp-stdio.sh
        |
        v
mcp_server_apdv1.server
        |
        | 调用本地 HTTP API
        v
apdv1/app_server/deploy_api.py
        |
        | 写入队列记录
        v
apdv1/.codex/state/app_server_queue/
        |
        | worker 取任务
        v
apdv1/app_server/runner.py serve
        |
        | 启动 codex app-server turn
        v
Codex 自动部署 agent
        |
        | 生成部署产物和日志
        v
apdv1/Deliverable/ 和 apdv1/DP_LOGS/
```

## 启动阶段

1. `scripts/install-local-deps.sh`
   - 安装 MCP SDK 到 `.deps/`。
   - 不改系统 Python 包。

2. `scripts/start-worker.sh`
   - 进入 `apdv1/`。
   - 启动 `python3 app_server/runner.py serve`。
   - worker 进入单任务队列循环。

3. `scripts/start-api.sh`
   - 进入 `apdv1/`。
   - 启动 `python3 app_server/deploy_api.py --host 127.0.0.1 --port 18084`。
   - 对外提供本地 HTTP API。

4. `scripts/start-mcp-stdio.sh`
   - 设置 `.deps` 和 `mcp_server_apdv1/src` 到 `PYTHONPATH`。
   - 启动 `python3 -m apdv1_mcp_server.server`。
   - MCP 客户端通过 stdio 与它通信。

## 提交部署任务

MCP 客户端调用：

```text
apdv1_deploy(url, extras?)
```

MCP Server 内部执行：

```text
POST http://127.0.0.1:18084/deploy
```

HTTP API 会把任务写入：

```text
apdv1/.codex/state/app_server_queue/pending/<request_id>.json
```

返回结果包含：

- `request_ids`
- `queue_counts`

## worker 处理任务

`runner.py serve` 发现 pending 任务后：

1. 把 queue record 从 `pending/` 移到 `active/`。
2. 写入 service state。
3. 创建 run 目录：

   ```text
   apdv1/app_server/runs/service-<request_id>/task-001/
   ```

4. 通过官方 `codex app-server` 启动一个 Codex turn。
5. 把目标 JSON 和 `AGENTS.md` 约束交给内层 Codex agent。

## 内层 Codex agent 做什么

内层 agent 按 `apdv1/AGENTS.md` 执行：

1. 解析 target，确定 `delivery_mode`。
2. 默认走 `portable-deliverable`，直接构建最终 portable bundle。
3. 使用官方安装/部署信息指导 final bundle。
4. 从 final bundle 自身脚本重新部署并验证真实 baseline 功能。
5. 写入 `verification_result.json`，成功时必须包含 `passed=true` 和 `basic_function_verified=true`。
6. 只运行 final portable audit gate。
7. 必要时写入经验库。
8. 写终态状态。

输出通常写入：

```text
apdv1/Deliverable/<project>-final/
apdv1/DP_LOGS/<project>-final/
```

说明：

- 默认 final 是目录型 portable bundle：`apdv1/Deliverable/<project>-final/` 和 `apdv1/DP_LOGS/<project>-final/`。
- 目标 JSON 明确传入 `image_bundle: true` 时，生成镜像型 final：`apdv1/Deliverable/<project>-image-final/` 和 `apdv1/DP_LOGS/<project>-image-final/`。
- 显式 `delivery_mode="local-run"` 用于本机可访问部署，不要求 portable final。
- 当前 portable workflow 不要求先完成独立 primary deployment；官方部署信息用于指导 final bundle 构建。

## 查询状态

MCP 客户端调用：

```text
apdv1_tasks(limit?, url?)
```

内部调用：

```text
GET http://127.0.0.1:18084/status
```

MCP 工具会把底层状态整理成更适合用户阅读的分组，返回：

- pending/active/completed/failed/canceled 计数
- 每个分组里的简化任务记录
- 查询下一步提示

## 查看结果和产物

部署完成后，用户不需要自己猜目录。推荐调用：

```text
apdv1_result
```

如果不传参数，它会返回当前可见的最新任务摘要。如果传 `request_id`，会返回精确任务结果。

成功任务通常会返回：

- `project_name`
- `artifacts.deliverables[].path`
- `artifacts.deliverables[].quickstart`
- `artifacts.logs[].path`
- `artifacts.logs[].summary`
- `last_message`

如果任务还没进入产生交付物的阶段，`apdv1_result` 会返回 `artifact_hint`，提示产物通常会在部署后期出现在 `apdv1/Deliverable/` 和 `apdv1/DP_LOGS/`。

## 读取日志

MCP 客户端调用：

```text
apdv1_tail(request_id?, file?, lines?)
```

可读取：

- 服务日志：不传 `request_id`
- 任务 trace：`file="trace"`
- Codex 原始通信日志：`file="log"`
- 事件 JSONL：`file="events"`
- 最后一条 agent 消息：`file="last-message"`
- 协议统计：`file="protocol"`
- 队列记录：`file="record"`

## 中断任务

MCP 客户端调用：

```text
apdv1_abort_current(confirm=true)
```

内部调用：

```text
POST http://127.0.0.1:18084/abort-current
```

worker 收到控制文件后：

1. 中断当前 Codex turn。
2. 把任务标记为 `ABORTED`。
3. 把 queue record 移入 `failed/`。
4. worker 回到 `IDLE`。

## 打包逻辑

`scripts/package.sh` 会生成最终 tar.gz。

它会排除运行时产物：

- `.deps/`
- `.venv/`
- `apdv1/.codex/state/`
- `apdv1/app_server/runs/`
- `apdv1/app_server/results/`
- `apdv1/Deliverable/`
- `apdv1/DP_LOGS/`

因此测试运行产生的日志和交付物不会进入最终分发包。
