# App Server Client

这是 `app_server/` 下的通用 Codex App Server 客户端文档。

它和 APDv1 部署 runner 是两层不同东西：

- [README.md](README.md): APDv1 部署 runner / 队列服务 / 任务状态
- `CLIENT.md`: 通用 Codex App Server client / CLI / HTTP gateway / transport

## 组件

当前已经把 app-server 协议核心从 runner 编排逻辑中抽出：

- `app_server/client/core.py`
  - `AppServerClient`: 官方 `codex app-server` stdio JSON-RPC 客户端
  - `TaskPaths` / `ClientPaths`: 日志、事件、trace、protocol 文件落盘目标
  - `request()` / `recv()` / `send()`: JSON-RPC 基础调用
  - `ensure_initialized()`: 官方 initialize/initialized 握手
  - `start_thread()` / `start_turn()` / `interrupt_turn()`: 常用高层方法
  - server-request dispatch: approval 自动兜底、unsupported 请求显式失败
- `app_server/client/handlers.py`
  - 可插拔 server-request handler
  - 默认安全兜底策略
- `app_server/client/schemas.py`
  - 生成官方 JSON schema
  - 读取 client/server method index
  - 校验 method 是否存在
- `app_server/client/unix_client.py`
  - 连接既有 `codex app-server --listen unix://PATH`
  - 注意：Codex 的 unix listener 使用 WebSocket framing over Unix socket，不是裸 JSONL
- `app_server/client/websocket_client.py`
  - 连接既有 `codex app-server --listen ws://HOST:PORT`
  - 支持本地开发用的无第三方依赖 `ws://`，不覆盖 `wss://`、复杂代理和完整 JWT/capability token 管理
- `app_server/cli.py`
  - 通用 CLI
- `app_server/daemon.py`
  - 通用 HTTP gateway
- `app_server/tests/test_client_core.py`
  - handlers 和 schema method index 的单元测试

## CLI

协议和 schema：

```bash
python3 app_server/cli.py doctor
python3 app_server/cli.py methods
python3 app_server/cli.py schema --out app_server/schemas/latest
python3 app_server/cli.py validate-method model/list
```

Raw request：

```bash
python3 app_server/cli.py request model/list --params '{}'
```

`request <method> --params '<json>'` 是通用 escape hatch，可调用当前 schema 暴露的任意 client request 方法。可用 `python3 app_server/cli.py methods` 查看当前 Codex 版本暴露的方法索引。

Thread：

```bash
python3 app_server/cli.py thread list
python3 app_server/cli.py thread start
python3 app_server/cli.py thread read --thread-id <thread_id>
python3 app_server/cli.py thread unsubscribe --thread-id <thread_id>
```

Turn：

```bash
python3 app_server/cli.py turn start --text 'say hello' --wait
python3 app_server/cli.py turn interrupt --thread-id <thread_id> --turn-id <turn_id>
```

高层 alias：

```bash
python3 app_server/cli.py model list
python3 app_server/cli.py account read
python3 app_server/cli.py config read
python3 app_server/cli.py skills list
```

## Server-Request 兜底

默认 handler 是无人值守安全策略：

- `item/commandExecution/requestApproval`: 按 `APP_SERVER_APPROVAL_DECISION` 响应，默认 `cancel`
- `item/fileChange/requestApproval`: 按 `APP_SERVER_APPROVAL_DECISION` 响应，默认 `cancel`
- `item/permissions/requestApproval`: 返回无额外权限
- `item/tool/requestUserInput`: 返回空 answers
- `mcpServer/elicitation/request`: 返回 `cancel`
- `item/tool/call`: 返回失败文本
- `account/chatgptAuthTokens/refresh`: 返回 unsupported error
- `applyPatchApproval` / `execCommandApproval`: 返回 `denied`
- 其他未知请求：返回 JSON-RPC unsupported error，并写入 `protocol.json`

如需允许 approval 自动通过：

```bash
APP_SERVER_APPROVAL_DECISION=acceptForSession python3 app_server/cli.py turn start --text '...' --wait
```

## Transport

### stdio

默认客户端会自己启动：

```bash
codex app-server
```

并通过 stdin/stdout JSON-RPC 通信。这是 APDv1 runner 和通用 CLI 的默认模式。

### Unix Socket

先启动已有 app-server：

```bash
mkdir -p .codex/state/test-unix-socket
codex app-server --listen unix://$PWD/.codex/state/test-unix-socket/app.sock
```

再调用：

```bash
python3 app_server/cli.py unix-request \
  --socket "$PWD/.codex/state/test-unix-socket/app.sock" \
  model/list --params '{}'
```

当前环境里直接启动 `codex app-server --listen unix:///tmp/...` 返回 `Operation not permitted`。放在项目可写目录，例如 `.codex/state/test-unix-socket/app.sock` 可以正常启动并已通过 `unix-request` smoke。

### WebSocket

先启动已有 app-server：

```bash
codex app-server --listen ws://127.0.0.1:18083
```

再调用：

```bash
python3 app_server/cli.py ws-request \
  --url ws://127.0.0.1:18083 \
  model/list --params '{}'
```

`ws-request` 已通过本地 smoke。`wss://`、复杂代理、JWT/capability token 管理不在当前最小客户端范围内。

## HTTP Gateway

启动：

```bash
python3 app_server/daemon.py --port 18082
```

接口：

- `GET /healthz`
- `GET /config`
- `POST /request`
- `POST /turn/start`

示例：

```bash
curl -sS http://127.0.0.1:18082/healthz
curl -sS -X POST http://127.0.0.1:18082/request \
  -H 'Content-Type: application/json' \
  --data '{"method":"thread/loaded/list","params":{}}'
curl -sS -X POST http://127.0.0.1:18082/turn/start \
  -H 'Content-Type: application/json' \
  --data '{"text":"say hello"}'
```

当前 HTTP gateway 是轻量本地 gateway。每次请求会临时创建一个 app-server client，不是长期连接池。

## 验证

```bash
python3 -m py_compile \
  app_server/__init__.py \
  app_server/runner.py \
  app_server/cli.py \
  app_server/daemon.py \
  app_server/client/*.py \
  app_server/tests/test_client_core.py

python3 -m unittest app_server.tests.test_client_core
python3 app_server/cli.py doctor
python3 app_server/cli.py model list
python3 app_server/cli.py turn start --text 'Reply exactly: OK' --wait --wait-timeout 120
```

