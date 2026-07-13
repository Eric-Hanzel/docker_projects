# APDv1 MCP Server

这是 APDv1 自动项目部署队列的 MCP Server 适配器。

它不直接执行部署任务，而是调用 APDv1 HTTP API；HTTP API 再把任务交给 `app_server/runner.py serve`。

## 安装

推荐在完整交付包根目录使用：

```bash
./scripts/install-local-deps.sh
```

也可以在支持 venv 的环境中安装为 Python 包：

```bash
cd mcp_server_apdv1
python3 -m pip install -e .
```

## 启动

完整交付包中应通过脚本启动：

```bash
export APDV1_API_BASE=http://127.0.0.1:18084
../scripts/start-mcp-stdio.sh
```

默认 transport 是 stdio，适合本机 MCP 客户端接入。

## 代码组成

- `src/apdv1_mcp_server/server.py`：MCP tools/resources 定义。
- `src/apdv1_mcp_server/client.py`：APDv1 HTTP API 客户端。
- `src/apdv1_mcp_server/config.py`：环境变量配置。
- `tests/test_client.py`：HTTP client 的轻量单元测试。

