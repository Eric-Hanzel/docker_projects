# APDv1 App Server 部署服务

这是交付给外部调用方使用的 **App Server 化自动项目部署服务**。

调用方通常只需要知道两件事：

```bash
cd /absolute/path/to/apdv1-mcp-full-bundle/apdv1

# 1. 启动长期运行的部署 worker，真正执行部署任务
python3 app_server/runner.py serve

# 2. 启动长期运行的 HTTP API，给外部系统提交任务、查状态、看日志
python3 app_server/deploy_api.py --port 18084
```

之后调用方通过 HTTP 提交部署任务：

```bash
curl --noproxy '*' -sS -X POST http://127.0.0.1:18084/deploy \
  -H 'Content-Type: application/json' \
  --data '{"url":"https://github.com/org/project"}'
```

返回的 `request_ids[0]` 就是后续查询、看日志、取消任务用的 ID。

## 服务组成

正式服务由两个长期进程组成：

- `python3 app_server/runner.py serve`
  - 单 worker 部署队列服务
  - 串行处理任务，一次只跑一个项目
  - 任务执行内部使用 `codex app-server`
- `python3 app_server/deploy_api.py --port 18084`
  - HTTP API
  - 给外部调用方提交任务、查询状态、查看日志、取消任务

这两个进程合起来才是完整的“自动项目部署 App Server 化服务”。

## HTTP API

### 启动

```bash
cd /absolute/path/to/apdv1-mcp-full-bundle/apdv1
python3 app_server/deploy_api.py --port 18084
```

### 接口

- `GET /healthz`: API 健康检查
- `GET /status`: 查看服务和队列状态
- `POST /deploy`: 提交部署任务
- `GET /requests/<request_id>`: 查看单个请求记录
- `GET /requests/<request_id>/tail?file=trace&lines=40`: 查看请求日志
- `POST /requests/<request_id>/cancel`: 取消 pending 请求或中断 active 请求
- `POST /abort-current`: 中断当前 active 请求
- `POST /stop`: 停止 `runner.py serve` 服务

### 示例

健康检查：

```bash
curl --noproxy '*' -sS http://127.0.0.1:18084/healthz
```

提交一个部署任务：

```bash
curl --noproxy '*' -sS -X POST http://127.0.0.1:18084/deploy \
  -H 'Content-Type: application/json' \
  --data '{"url":"https://github.com/org/project"}'
```

提交完整 target 对象：

```bash
curl --noproxy '*' -sS -X POST http://127.0.0.1:18084/deploy \
  -H 'Content-Type: application/json' \
  --data '{"target":{"url":"https://github.com/org/project","license_key":"optional"}}'
```

查看队列和服务状态：

```bash
curl --noproxy '*' -sS http://127.0.0.1:18084/status
```

查看单个请求：

```bash
curl --noproxy '*' -sS http://127.0.0.1:18084/requests/<request_id>
```

查看日志：

```bash
curl --noproxy '*' -sS \
  'http://127.0.0.1:18084/requests/<request_id>/tail?file=trace&lines=80'
```

取消任务：

```bash
curl --noproxy '*' -sS -X POST http://127.0.0.1:18084/requests/<request_id>/cancel \
  -H 'Content-Type: application/json' \
  --data '{}'
```

## 调用方只需关注的规则

- 服务是单 worker：一次只执行一个部署任务。
- 新任务会进入 `pending` 队列，不会打断正在执行的任务。
- `pending` 任务：停服务后保留，恢复服务后继续执行。
- `active` 任务如果被正常 `stop` / `abort-current` 中断：落为失败，不自动重试。
- `active` 任务如果是服务异常崩掉留下的脏状态：下次启动会被回收到 `pending` 再跑。
- `cancel` pending 请求会把它移动到 `canceled/`，状态为 `CANCELLED`。
- `cancel` active 请求会请求中断当前任务，任务通常落为 `ABORTED`。

## 手动 CLI

HTTP API 是对外推荐入口。人工维护时也可以直接使用 CLI。

启动服务：

```bash
python3 app_server/runner.py serve
```

提交单个任务：

```bash
python3 app_server/runner.py submit --target-json '{"url":"https://example.com"}'
```

提交 JSONL 文件里的多个任务：

```bash
python3 app_server/runner.py submit --target-file /path/to/targets.jsonl
```

查看状态：

```bash
python3 app_server/runner.py status
python3 app_server/runner.py status --json
```

查看日志：

```bash
python3 app_server/runner.py tail
python3 app_server/runner.py tail --request-id <request_id> --file trace
python3 app_server/runner.py tail --request-id <request_id> --file log
python3 app_server/runner.py tail --request-id <request_id> --file protocol
```

取消和停止：

```bash
python3 app_server/runner.py cancel --request-id <request_id>
python3 app_server/runner.py abort-current
python3 app_server/runner.py stop
```

## 与旧链路的关系

这是一套与现有 `batch/run_codex_batch.sh` 平行存在的链路，不会改动旧 batch runner。

它的目标不是替换 `.codex/skills`、`AGENTS.md` 或状态协议，而是只替换内层执行方式：

- 旧链路：`codex exec` + rollout/log 解析
- 新链路：`codex app-server` + JSON-RPC 事件流

当前默认会在一次 `app_server` run 内复用同一个 `codex app-server` 进程，也就是“per-run 常驻、per-task 顺序复用”：

- 原始链路 `batch/run_codex_batch.sh` 完全不受影响
- 并行链路 `app_server/runner.py` / `batch/run_codex_batch_appserver.sh` 默认使用长生命周期 app-server
- 如果需要回退到每个 task 单独启动一个 app-server 进程，可以显式传 `--server-lifecycle per-task`

并行 batch 入口：

```bash
bash batch/run_codex_batch_appserver.sh
bash batch/run_codex_batch_appserver.sh /path/to/targets.jsonl
```

## 可观测性

查看服务和队列状态：

```bash
python3 app_server/runner.py status
python3 app_server/runner.py status --json
```

查看服务日志：

```bash
python3 app_server/runner.py tail
```

查看某个请求的落盘记录或任务日志：

```bash
python3 app_server/runner.py tail --request-id <request_id> --file record
python3 app_server/runner.py tail --request-id <request_id> --file trace
python3 app_server/runner.py tail --request-id <request_id> --file log
python3 app_server/runner.py tail --request-id <request_id> --file protocol
```

协议 smoke 检查，不启动模型 turn，只验证 `codex app-server` 的 schema 生成、初始化、线程创建和退订：

```bash
python3 app_server/runner.py doctor
python3 app_server/runner.py doctor --json
```

## 取消与停止

取消一个还没开始的 pending 请求：

```bash
python3 app_server/runner.py cancel --request-id <request_id>
```

如果该请求已经在 active 运行，`cancel` 会转成“请求中断当前任务”。

只中断当前正在运行的任务，但保持服务继续可用：

```bash
python3 app_server/runner.py abort-current
```

停止服务：

```bash
python3 app_server/runner.py stop
```

当前行为：

- `cancel` 针对 `pending` 请求会把它移动到 `canceled/`，状态为 `CANCELLED`
- `cancel` 针对 `active` 请求会请求中断当前任务，任务状态通常落为 `ABORTED`
- `abort-current` 会中断当前任务，但服务会继续运行并继续处理后续队列
- `stop` 会停止服务；如果当前有任务在跑，会先请求中断当前任务，再把服务状态写成 `STOPPED`
- 如果 app-server 发起官方 approval server-request，runner 会自动响应，避免无人值守任务挂死；默认决策是 `cancel`
- 如确实需要允许 approval 自动通过，可在启动前设置 `APP_SERVER_APPROVAL_DECISION=accept` 或 `APP_SERVER_APPROVAL_DECISION=acceptForSession`

恢复规则：

- `pending` 任务：停服务后保留，恢复服务后继续执行
- `active` 任务如果是被正常 `stop` / `abort-current` 中断：落为失败，不自动重试
- `active` 任务如果是服务异常崩掉留下的脏状态：下次启动会被回收到 `pending` 再跑

## 输入格式

和现有 batch runner 保持一致：

- 每行一个 JSON 对象
- 必须包含 `url`
- 其他字段原样保留并传给内层 agent

## 输出目录

新链路只写自己的目录，不复用旧 batch 输出：

- `app_server/runs/<run_id>/task-001/`
  - `prompt.txt`
  - `codex.log`
  - `events.jsonl`
  - `trace.txt`
  - `last_message.txt`
  - `session.json`
  - `thread_id`
  - `protocol.json`
- `app_server/runs/<run_id>/summary.json`
- `app_server/results/<run_id>/results.jsonl`

每个 task 仍然保留独立日志/事件文件；常驻 app-server 的复用只影响进程生命周期，不改变按任务落盘的方式。

## 状态文件

为了不影响现有 runner，状态单独写到：

- `.codex/state/app_server_task_state.json`
- `.codex/state/app_server_task_history.jsonl`
- `.codex/state/app_server_batch.lock`
- `.codex/state/app_server_service_state.json`
- `.codex/state/app_server_service_history.jsonl`
- `.codex/state/app_server_service.log`
- `.codex/state/app_server_service_control.json`
- `.codex/state/app_server_queue/pending/`
- `.codex/state/app_server_queue/active/`
- `.codex/state/app_server_queue/completed/`
- `.codex/state/app_server_queue/failed/`
- `.codex/state/app_server_queue/canceled/`

## 官方协议覆盖范围

当前覆盖的官方 App Server 核心协议：

- `stdio://` JSONL transport
- 每连接一次 `initialize` + `initialized`
- `thread/start`
- `turn/start`
- 持续消费 `turn/*`、`item/*`、`error` 等通知
- `turn/interrupt`
- `thread/loaded/list`、`thread/unsubscribe` 的 doctor 检查
- command/file approval server-request 的自动兜底响应

当前不实现完整交互式客户端能力：

- 不提供 WebSocket/Unix socket 长连接入口和 HTTP health endpoint
- 不提供人工 approval UI
- 不主动处理 dynamic tool call、MCP connector 用户输入、外部 ChatGPT token refresh 等高级 server-request；遇到这些请求会写入 `protocol.json` 并返回 unsupported，避免静默挂死
- 不替代官方 `codex app-server`，这里只是 APDv1 的 runner/service 包装层

通用 App Server 客户端、CLI、HTTP gateway、Unix/WebSocket transport 的文档在 [CLIENT.md](CLIENT.md)。

## 当前范围

当前实现是可交付的 APDv1 App Server 化部署服务：

- 对外调用入口：`app_server/deploy_api.py`
- 长期 worker：`app_server/runner.py serve`
- 底层执行：官方 `codex app-server`
- 状态/队列/日志：独立写入 `app_server/` 和 `.codex/state/app_server_*`
- 旧 batch 链路：`batch/run_codex_batch.sh` 不受影响

底层 Codex App Server 调试工具、通用 CLI 和 transport 客户端见 [CLIENT.md](CLIENT.md)。
