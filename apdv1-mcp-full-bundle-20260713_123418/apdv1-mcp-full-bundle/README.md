# APDv1 MCP 完整交付包

这个目录是把 APDv1 批量自动项目环境部署 agent 封装成标准 MCP Server 后的完整交付包。

它包含两层：

- `apdv1/`：真正执行部署任务的 APDv1 运行时。
- `mcp_server_apdv1/`：标准 MCP 适配器，把 APDv1 的部署队列能力暴露成 MCP tools/resources。

MCP Server 不直接部署项目。它通过本地 APDv1 HTTP API 提交任务、查询状态、读取日志和中断任务；实际部署仍由 `apdv1/app_server/runner.py serve` 执行。

## 快速启动

```bash
cd apdv1-mcp-full-bundle
./scripts/install-local-deps.sh
./scripts/start-worker.sh
./scripts/start-api.sh
./scripts/doctor.sh
```

然后把 `config/mcp-client.example.json` 复制到你的 MCP 客户端配置中，并把 `/absolute/path/to/apdv1-mcp-full-bundle` 改成真实绝对路径。

## 目录总览

```text
apdv1-mcp-full-bundle/
  apdv1/                 APDv1 部署运行时快照
  mcp_server_apdv1/      MCP Server Python 包
  scripts/               安装、启动、自检、打包脚本
  config/                MCP 客户端配置和环境变量样例
  docs/                  中文操作文档
  examples/              示例部署目标
  dist/                  打包后的 tar.gz 交付归档
  .deps/                 本机测试/安装生成的 Python 依赖目录，不进入交付归档
  .venv/                 可选虚拟环境目录，不进入交付归档
```

更详细的目录说明见 [docs/directory-structure.md](docs/directory-structure.md)。

## 工作逻辑

```text
MCP 客户端 / IDE / Agent
        |
        | stdio MCP tools
        v
scripts/start-mcp-stdio.sh
        |
        v
mcp_server_apdv1
        |
        | HTTP: /deploy /status /requests/... /logs
        v
apdv1/app_server/deploy_api.py
        |
        | queue/state/log files
        v
apdv1/app_server/runner.py serve
        |
        | codex app-server
        v
Codex 自动部署 agent
        |
        v
Deliverable/<project>-final/ 和 DP_LOGS/<project>-final/
```

详细工作流程见 [docs/workflow.md](docs/workflow.md)。

MCP 提交默认使用当前 APDv1 标准：`delivery_mode="portable-deliverable"` 和 `portable_final_required=true`，生成目录型 portable final：

```text
apdv1/Deliverable/<project>-final/
apdv1/DP_LOGS/<project>-final/
```

如果目标明确需要镜像交付，传入 `image_bundle=true`，生成镜像型 final：

```text
apdv1/Deliverable/<project>-image-final/
apdv1/DP_LOGS/<project>-image-final/
```

成功的非条件 portable run 必须在 `DP_LOGS/<project>-final/verification_result.json` 写入顶层 `passed=true` 和 `basic_function_verified=true`，并通过 final portable audit，写入 `audit_result.json`。

常用输入模式：

| 输入 | 用途 | 输出 |
| --- | --- | --- |
| 只传 `url` | 默认完整 portable 测试 | `Deliverable/<project>-final/`、`DP_LOGS/<project>-final/` |
| `delivery_mode=portable-deliverable` | 显式完整 portable | 同上，要求 `verification_result.json` 和 `audit_result.json` |
| `delivery_mode=portable-deliverable`, `image_bundle=true` | 镜像/离线交付 | `Deliverable/<project>-image-final/`、`DP_LOGS/<project>-image-final/` |
| `delivery_mode=local-run`, `portable_final_required=false` | 只验证本机可运行 | `Deliverable/<project>/`、`DP_LOGS/<project>/` 和 live endpoint |

可调字段包括 `project_name`、`version_requirement`、`license_key`、token 类字段和目标项目需要的其他 extras。旧字段 `delivery_format` 仍兼容，但新调用应使用 `delivery_mode` / `portable_final_required` / `image_bundle`。

## 主要 MCP 工具

- `apdv1_health`：检查 APDv1 HTTP API 是否可达。
- `apdv1_deploy`：提交单个项目部署任务。
- `apdv1_deploy_batch`：批量提交多个部署任务。
- `apdv1_tasks`：用更适合用户阅读的格式列出 pending、active、completed、failed、canceled 任务。
- `apdv1_result`：查看任务结果摘要；可以不传 `request_id`，默认查看当前可见的最新任务，也可以按 `url` 过滤。
- `apdv1_tail`：读取服务日志或任务日志。
- `apdv1_cancel`：取消 pending 请求或请求中断 active 请求。
- `apdv1_abort_current`：中断当前 active 任务，需要 `confirm=true`。

完整说明见 [docs/tools.md](docs/tools.md)。

## 直接用 HTTP 提交任务

不通过 MCP 时，也可以直接调 APDv1 HTTP API：

```bash
curl --noproxy '*' -sS -X POST http://127.0.0.1:18084/deploy \
  -H 'Content-Type: application/json' \
  --data '{"url":"https://github.com/org/project"}'
```

## 通过 MCP 提交任务

MCP 客户端调用 `apdv1_deploy`：

```json
{
  "url": "https://github.com/org/project",
  "extras": {
    "delivery_mode": "portable-deliverable",
    "portable_final_required": true
  }
}
```

返回的 `request_ids[0]` 用于后续查询和读取日志。

批量提交时调用 `apdv1_deploy_batch`：

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
    }
  ]
}
```

返回的 `request_ids` 用于后续调用 `apdv1_tasks`、`apdv1_result` 和 `apdv1_tail`。

## 运行要求

- Linux 主机。
- Python 3.11 或更新版本。
- Docker 和 Docker Compose。
- `codex` CLI 在 `PATH` 中可用。
- 目标项目需要拉源码或镜像时，主机需要外网访问能力。

## 安全提醒

这个包可以触发真实部署任务，部署过程中可能会拉取源码、构建镜像、启动容器、写入本地文件。建议只在可信主机上运行，默认只绑定 `127.0.0.1`，MCP 采用 stdio 方式接入。
