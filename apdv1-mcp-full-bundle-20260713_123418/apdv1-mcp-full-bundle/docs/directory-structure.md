# 目录结构和作用

本文说明 `apdv1-mcp-full-bundle/` 每个主要目录的组成和用途。

## 顶层目录

```text
apdv1-mcp-full-bundle/
  apdv1/
  mcp_server_apdv1/
  scripts/
  config/
  docs/
  examples/
  dist/
  .deps/
  .venv/
```

## `apdv1/`

APDv1 自动部署运行时快照。真正执行部署任务的是这个目录里的代码。

主要组成：

- `AGENTS.md`：内层 Codex 自动部署 agent 的执行协议和约束。
- `app_server/`：APDv1 App Server 化部署服务。
- `batch/`：旧批处理入口和说明。
- `.codex/`：部署技能、状态脚本、agent 配置和经验库。
- `Deliverable/`：运行后生成的项目交付物目录，运行时产生，不进入 MCP 工具最终 tar.gz。
- `DP_LOGS/`：运行后生成的部署日志目录，运行时产生，不进入 MCP 工具最终 tar.gz。

默认 MCP 目标使用 `delivery_mode="portable-deliverable"` 和 `portable_final_required=true`，生成目录型 portable final：

- `Deliverable/<project>-final/`
- `DP_LOGS/<project>-final/`

如果目标显式选择镜像交付，即 `image_bundle: true`，则生成镜像型 final：

- `Deliverable/<project>-image-final/`
- `DP_LOGS/<project>-image-final/`

成功的非条件 portable run 必须写入 `DP_LOGS/<project>-final/verification_result.json`，且顶层包含 `passed=true` 和 `basic_function_verified=true`，并写入 final `audit_result.json`。

说明：

- `apdv1/app_server/runner.py serve` 是实际 worker。
- `apdv1/app_server/deploy_api.py` 是本地 HTTP API。
- MCP Server 不直接改这个目录里的部署逻辑，只通过 HTTP API 使用它。

## `apdv1/app_server/`

APDv1 部署服务核心。

主要文件：

- `runner.py`：单 worker 队列服务，顺序处理部署任务。
- `deploy_api.py`：HTTP API，提供 `/deploy`、`/status`、`/requests/...`、`/logs` 等接口。
- `client/`：官方 `codex app-server` JSON-RPC 客户端。
- `README.md`：APDv1 App Server 服务说明。
- `CLIENT.md`：Codex App Server client/transport 说明。
- `tests/`：轻量测试。

运行时目录：

- `app_server/runs/`：每个请求的 prompt、trace、events、protocol、codex log。
- `app_server/results/`：请求结果汇总。

这两个运行时目录不进入最终 tar.gz。

## `apdv1/.codex/`

APDv1 运行所需的 Codex 配置和辅助脚本。

主要组成：

- `scripts/`：状态更新、端口注册、经验库、镜像缓存策略等脚本。
- `skills/`：部署、审计、portable bundle、经验沉淀等技能说明。
- `agents/`：子 agent 配置。
- `experience/`：经验库 catalog。
- `config.toml`：Codex 和子 agent 基础配置。
- `port_registry.toml`、`image_cache_policy.json`：端口和镜像缓存策略配置。
- `state/`：运行状态目录，运行时产生，不进入最终 tar.gz。

## `mcp_server_apdv1/`

MCP Server Python 包。

主要组成：

- `pyproject.toml`：Python 包配置，依赖 `mcp==1.27.2`。
- `src/apdv1_mcp_server/server.py`：MCP tools/resources 定义。
- `src/apdv1_mcp_server/client.py`：APDv1 HTTP API 客户端。
- `src/apdv1_mcp_server/config.py`：环境变量配置。
- `tests/test_client.py`：HTTP client 单元测试。

它的职责是协议适配：

```text
MCP tool call -> APDv1 HTTP API -> APDv1 worker
```

它不直接执行部署，也不直接调用 Docker。

## `scripts/`

交付包操作脚本。

主要文件：

- `install-local-deps.sh`：把 MCP SDK 及依赖安装到 `.deps/`。
- `start-worker.sh`：启动 APDv1 worker。
- `start-api.sh`：启动 APDv1 HTTP API。
- `start-mcp-stdio.sh`：启动 MCP Server stdio transport。
- `doctor.sh`：检查依赖、MCP 包、APDv1 API 和队列状态。
- `package.sh`：重新生成交付 tar.gz。

## `config/`

配置样例。

主要文件：

- `apdv1-mcp.env.example`：环境变量样例。
- `mcp-client.example.json`：MCP 客户端配置样例。

## `docs/`

中文文档目录。

主要文件：

- `directory-structure.md`：目录结构和作用。
- `workflow.md`：整体工作逻辑。
- `tools.md`：MCP tools 说明。
- `resources.md`：MCP resources 说明。
- `operations.md`：日常运维命令。
- `troubleshooting.md`：常见问题处理。

## `examples/`

示例输入。

主要文件：

- `deploy-one.json`：单个部署目标示例。
- `deploy-batch.jsonl`：批量部署目标示例。

## `dist/`

打包输出目录。

`scripts/package.sh` 会在这里生成：

```text
apdv1-mcp-full-bundle-YYYYMMDD_HHMMSS.tar.gz
```

最终交付给别人时，通常交付这个 tar.gz。

## `.deps/`

本地依赖目录，由 `scripts/install-local-deps.sh` 生成。

用途：

- 存放 MCP SDK 和 Python 依赖。
- 解决目标机器没有 `python3-venv` 时的安装问题。

说明：

- 这是本机运行产物。
- 不进入最终 tar.gz。
- 可以删除，之后重新运行 `./scripts/install-local-deps.sh`。

## `.venv/`

可选 Python 虚拟环境目录。

说明：

- 只有选择 venv 安装方式时才需要。
- 不进入最终 tar.gz。
- 当前交付更推荐 `.deps/` 路线。
