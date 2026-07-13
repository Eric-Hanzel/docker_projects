# Codex 中使用 APDv1 MCP 工具

本文主要说明如何把本包配置到 Codex，并在 Codex 里用自然语言调用 APDv1 MCP 工具完成批量自动化项目环境部署、任务查询、日志查看和结果定位。

## 1. 启动本地 APDv1 服务

先在交付包目录启动 worker 和 HTTP API：

```bash
cd /absolute/path/to/apdv1-mcp-full-bundle
./scripts/install-local-deps.sh
./scripts/start-worker.sh
./scripts/start-api.sh
./scripts/doctor.sh
```

`doctor: ok` 表示本地 APDv1 服务可用。MCP 工具本身通过这个本地 HTTP API 提交和查询部署任务。

## 2. 配置到 Codex

Codex 的 MCP 配置中，把 APDv1 MCP Server 配成 stdio 命令：

```toml
[mcp_servers.apdv1]
command = "/absolute/path/to/apdv1-mcp-full-bundle/scripts/start-mcp-stdio.sh"
```

配置完成后重启 Codex。之后在 Codex 对话里可以直接说：

```text
用 APDv1 部署 https://github.com/alerta/alerta
```

在支持 MCP 的 Codex 中，用户通常不需要手写 JSON。Codex 会根据工具 schema，把自然语言转换为对应的 MCP 工具参数。

## 3. 推荐工作流

常用顺序是：

1. `apdv1_health`：确认 APDv1 服务是否可用。
2. `apdv1_deploy` 或 `apdv1_deploy_batch`：提交单个或多个部署任务。
3. `apdv1_tasks`：查看 pending、active、completed、failed、canceled 队列。
4. `apdv1_result`：查看部署结果、产物路径和关键摘要。
5. `apdv1_tail`：需要排查时查看日志。
6. `apdv1_cancel` 或 `apdv1_abort_current`：需要停止任务时使用。

## 4. 工具输入输出示例

下面的“输入”是 MCP 客户端实际传给工具的结构化参数；在 Codex 中可以用自然语言表达，Codex 会尽量自动转换。

### apdv1_health

用途：检查 APDv1 HTTP API、worker 队列服务是否可达。

自然语言示例：

```text
检查一下 APDv1 MCP 后端是否正常。
```

结构化输入：

```json
{}
```

预期输出示例：

```json
{
  "ok": true,
  "service": "apdv1-deploy-api"
}
```

### apdv1_deploy

用途：提交一个项目部署任务。工具会立即返回请求编号，不会一直等待部署结束。

自然语言示例：

```text
用 APDv1 部署 https://github.com/alerta/alerta。
```

结构化输入：

```json
{
  "url": "https://github.com/alerta/alerta"
}
```

带额外参数的输入示例：

```json
{
  "url": "https://github.com/example/private-app",
  "extras": {
    "license_key": "可选许可证",
    "version_requirement": "latest stable",
    "delivery_mode": "portable-deliverable",
    "portable_final_required": true
  }
}
```

当前 APDv1 标准交付字段：

- `delivery_mode="portable-deliverable"`：默认值，生成目录型 portable final。
- `portable_final_required=true`：portable 交付必须为 true。
- `delivery_mode="local-run"` 和 `portable_final_required=false`：只做本机可访问部署，不生成 portable final。

镜像型 final 使用 `image_bundle=true`，并保持 `delivery_mode="portable-deliverable"`。兼容旧写法 `delivery_format=portable|directory|image` 仍可被 MCP 层转换，但新调用不要再使用它。

输入字段速查：

| 字段 | 默认值 | 是否常用 | 作用 |
| --- | --- | --- | --- |
| `url` | 无 | 必填 | GitHub/GitLab 项目地址、官方安装文档地址或其他目标 URL。 |
| `delivery_mode` | `portable-deliverable` | 常用 | `portable-deliverable` 生成可迁移 final；`local-run` 只要求本机跑通。 |
| `portable_final_required` | `true` | 常用 | portable 模式保持 `true`；local-run 通常设为 `false`。 |
| `image_bundle` | `false` | 按需 | `true` 时生成 `<project>-image-final`，适合镜像/离线交付。 |
| `project_name` | 自动推断 | 按需 | 指定输出目录基名，避免自动命名不符合预期。 |
| `version_requirement` | 未指定 | 按需 | 指定版本、tag、commit 或稳定版要求。 |
| `license_key` / token 类字段 | 未指定 | 按需 | 传给部署 agent 使用；结果文档中应脱敏。 |

模式和输出：

| 输入模式 | 预期结果 | 主要输出 |
| --- | --- | --- |
| 不传 extras | 默认 portable final | `apdv1/Deliverable/<project>-final/` 和 `apdv1/DP_LOGS/<project>-final/` |
| `delivery_mode=portable-deliverable` | 目录型 portable final | `README_QUICKSTART.md`、`scripts/deploy.sh`、`scripts/verify.sh`、`verification_result.json`、`audit_result.json` |
| `delivery_mode=portable-deliverable` + `image_bundle=true` | 镜像型 portable final | `apdv1/Deliverable/<project>-image-final/` 和 `apdv1/DP_LOGS/<project>-image-final/` |
| `delivery_mode=local-run` + `portable_final_required=false` | 本机可访问部署 | `apdv1/Deliverable/<project>/`、`apdv1/DP_LOGS/<project>/` 和 live endpoint 信息 |

预期输出示例：

```json
{
  "ok": true,
  "request_ids": [
    "req-20260610_120001-abcd1234"
  ],
  "queue_counts": {
    "pending": 1,
    "active": 0,
    "completed": 0,
    "failed": 0,
    "canceled": 0
  }
}
```

用户下一步应该用 `apdv1_tasks` 看任务是否开始，用 `apdv1_result` 看最终结果。

### apdv1_deploy_batch

用途：一次提交多个项目部署任务。每个对象必须包含 `url`，其他字段会作为 extras 透传给部署 agent。

自然语言示例：

```text
使用 APDv1 MCP 批量提交 3 个 portable-deliverable 测试任务，按队列顺序执行：

1. https://github.com/filebrowser/filebrowser
2. https://github.com/benbusby/whoogle-search
3. https://github.com/louislam/uptime-kuma

请调用 apdv1_deploy_batch。每个 target 都显式使用：
delivery_mode="portable-deliverable"
portable_final_required=true

提交后返回 request_ids，并调用 apdv1_tasks 查看 pending、active、completed 状态。
```

结构化输入：

```json
{
  "targets": [
    {
      "url": "https://github.com/filebrowser/filebrowser",
      "delivery_mode": "portable-deliverable",
      "portable_final_required": true
    },
    {
      "url": "https://github.com/benbusby/whoogle-search",
      "delivery_mode": "portable-deliverable",
      "portable_final_required": true
    },
    {
      "url": "https://github.com/louislam/uptime-kuma",
      "delivery_mode": "portable-deliverable",
      "portable_final_required": true
    }
  ]
}
```

如果要让某个 target 生成镜像型 final，只给那个 target 额外加 `image_bundle=true`：

```json
{
  "url": "https://github.com/org/project",
  "delivery_mode": "portable-deliverable",
  "portable_final_required": true,
  "image_bundle": true
}
```

如果要批量测试 local-run，把每个 target 改成：

```json
{
  "url": "https://github.com/org/project",
  "delivery_mode": "local-run",
  "portable_final_required": false
}
```

预期输出示例：

```json
{
  "ok": true,
  "request_ids": [
    "req-20260610_120001-abcd1234",
    "req-20260610_120002-bcde2345",
    "req-20260610_120003-cdef3456"
  ],
  "queue_counts": {
    "pending": 3,
    "active": 0,
    "completed": 0,
    "failed": 0,
    "canceled": 0
  }
}
```

说明：APDv1 runner 一般按队列逐个处理任务，不是同时部署所有项目。

### apdv1_tasks

用途：查看当前队列和历史任务。这个工具比直接查原始状态更适合用户阅读。

自然语言示例：

```text
现在有哪些任务在排队、运行、完成或失败？
```

结构化输入：

```json
{
  "limit": 20
}
```

按 URL 过滤：

```json
{
  "url": "https://github.com/alerta/alerta",
  "limit": 20
}
```

预期输出示例：

```json
{
  "pending": [],
  "active": [
    {
      "request_id": "req-20260610_120001-abcd1234",
      "status": "RUNNING",
      "url": "https://github.com/alerta/alerta",
      "project_name": "alerta-9-1-0",
      "run_dir": "/absolute/path/to/apdv1-mcp-full-bundle/apdv1/app_server/runs/..."
    }
  ],
  "completed": [],
  "failed": [],
  "canceled": [],
  "hint": "Use apdv1_result with request_id for exact details, or omit request_id to inspect the latest visible task."
}
```

### apdv1_result

用途：查看一个任务的最终状态、结果、产物目录、日志目录和最后消息。用户不知道 `request_id` 时，可以不传，工具会尝试查看最近可见任务。

自然语言示例：

```text
查看刚才那个部署任务的结果，告诉我产物在哪里。
```

结构化输入：

```json
{}
```

指定请求编号：

```json
{
  "request_id": "req-20260610_120001-abcd1234",
  "include_last_message": true,
  "trace_tail_lines": 80
}
```

按 URL 查找：

```json
{
  "url": "https://github.com/alerta/alerta"
}
```

成功时的预期输出示例：

```json
{
  "ok": true,
  "request_id": "req-20260610_120001-abcd1234",
  "status": "COMPLETED_SUCCESS",
  "result": "success",
  "url": "https://github.com/alerta/alerta",
  "project_name": "alerta-9-1-0",
  "artifacts": {
    "project_name": "alerta-9-1-0",
    "deliverables": [
      {
        "name": "alerta-9-1-0-final",
        "path": "/absolute/path/to/apdv1-mcp-full-bundle/apdv1/Deliverable/alerta-9-1-0-final",
        "quickstart": "/absolute/path/to/apdv1-mcp-full-bundle/apdv1/Deliverable/alerta-9-1-0-final/README_QUICKSTART.md"
      }
    ],
    "logs": [
      {
        "name": "alerta-9-1-0-final",
        "path": "/absolute/path/to/apdv1-mcp-full-bundle/apdv1/DP_LOGS/alerta-9-1-0-final",
        "summary": "/absolute/path/to/apdv1-mcp-full-bundle/apdv1/DP_LOGS/alerta-9-1-0-final/summary.md",
        "verification_result": "/absolute/path/to/apdv1-mcp-full-bundle/apdv1/DP_LOGS/alerta-9-1-0-final/verification_result.json",
        "audit_result": "/absolute/path/to/apdv1-mcp-full-bundle/apdv1/DP_LOGS/alerta-9-1-0-final/audit_result.json"
      }
    ]
  }
}
```

如果任务失败，`ok` 通常是 `false`，`status` 会显示失败状态，`last_message` 或 `trace_tail` 会提供排查线索。

### apdv1_tail

用途：查看服务日志或某个请求的日志尾部。

自然语言示例：

```text
查看这个任务最近 100 行 trace 日志。
```

结构化输入：

```json
{
  "request_id": "req-20260610_120001-abcd1234",
  "file": "trace",
  "lines": 100
}
```

可选 `file`：

```text
trace, log, events, last-message, protocol, record
```

预期输出：返回文本日志内容，例如最近的部署阶段、失败原因、验证结果或产物路径。

### apdv1_cancel

用途：取消 pending 任务；如果任务已经 active，则请求中断该任务。

自然语言示例：

```text
取消 req-20260610_120001-abcd1234 这个部署任务。
```

结构化输入：

```json
{
  "request_id": "req-20260610_120001-abcd1234"
}
```

预期输出示例：

```json
{
  "ok": true,
  "action": "canceled",
  "request_id": "req-20260610_120001-abcd1234",
  "record_path": "/absolute/path/to/apdv1/.codex/state/app_server_queue/canceled/req-20260610_120001-abcd1234.json"
}
```

如果该请求已经是 active，返回中的 `action` 会是 `abort_requested`。pending cancel 只移动队列记录；active cancel 和 `apdv1_abort_current` 会请求中断当前任务，随后由 runner 的收尾逻辑执行项目范围 Docker 清理和失败产物清理。历史 run/results/queue 记录不会自动删除。

### apdv1_abort_current

用途：强制请求中断当前 active 任务。这个工具影响正在运行的任务，所以需要明确确认。

自然语言示例：

```text
确认中断当前正在运行的 APDv1 部署任务。
```

结构化输入：

```json
{
  "confirm": true
}
```

没有确认时的输出：

```json
{
  "ok": false,
  "error": "Set confirm=true to abort the active APDv1 request."
}
```

## 5. Codex 中的自然语言用法

在 Codex 里，推荐这样说：

```text
检查 APDv1 是否健康。
```

```text
用 APDv1 部署 https://github.com/alerta/alerta，完成后帮我查看结果和产物目录。
```

```text
使用 APDv1 MCP 批量提交 2 个 portable-deliverable 测试任务：
https://github.com/filebrowser/filebrowser
https://github.com/benbusby/whoogle-search

每个 target 都使用 delivery_mode="portable-deliverable" 和 portable_final_required=true。
提交后告诉我每个 request_id，并调用 apdv1_tasks 查看队列。
```

```text
查看 APDv1 当前队列，告诉我哪些任务 pending、active、failed。
```

```text
查看最近一个任务的结果。如果失败，读取最近 100 行 trace 日志并总结失败原因。
```

Codex 会自动选择工具并填入参数。但部署是异步队列任务，提交成功不等于部署完成；需要后续用 `apdv1_tasks` 和 `apdv1_result` 查询。

## 6. 产物在哪里

部署完成后，优先用 `apdv1_result` 查看产物路径。正常情况下会看到：

```text
apdv1/Deliverable/<project_name>-final/
apdv1/DP_LOGS/<project_name>-final/
```

其中 `<project_name>-final` 是默认最终可交付包，里面应包含 `README_QUICKSTART.md`、`scripts/`、`docker-compose.yml`、源码快照和数据库初始化快照等内容。

成功的非条件 portable run 必须写入 `verification_result.json`，且顶层包含 `passed=true` 和 `basic_function_verified=true`，并通过 final portable audit 写入 `audit_result.json`。

`apdv1_result` 返回的 `artifacts` 会优先列出：

- `deliverables[].path`：最终交付物目录。
- `deliverables[].quickstart`：快速启动文档。
- `logs[].path`：最终日志目录。
- `logs[].summary`：总结。
- `logs[].verification_result`：功能验证结果。
- `logs[].audit_result`：最终审计结果。

如果提交任务时显式传入 `image_bundle=true`，则生成镜像型 final：

```text
apdv1/Deliverable/<project_name>-image-final/
apdv1/DP_LOGS/<project_name>-image-final/
```

镜像型 final 适合离线交付或减少目标机器构建/下载时间；目录型 portable final 更适合审计、修改和通用迁移。

## 7. 直接 HTTP 测试方式

如果不通过 Codex，也可以直接调用本地 HTTP API：

```bash
curl --noproxy '*' -sS -X POST http://127.0.0.1:18084/deploy \
  -H 'Content-Type: application/json' \
  --data @examples/deploy-one.json
```

查看状态：

```bash
curl --noproxy '*' -sS http://127.0.0.1:18084/status
```
