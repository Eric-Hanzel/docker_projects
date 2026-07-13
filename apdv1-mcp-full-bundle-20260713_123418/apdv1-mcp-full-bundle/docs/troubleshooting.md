# 故障排查

## MCP tool 报 APDv1 API unavailable

说明 APDv1 HTTP API 没有运行，或 `APDV1_API_BASE` 配错。

检查：

```bash
./scripts/start-api.sh
curl --noproxy '*' -sS http://127.0.0.1:18084/healthz
```

## API 正常，但任务不执行

通常是 worker 没有运行。

检查：

```bash
./scripts/start-worker.sh
curl --noproxy '*' -sS http://127.0.0.1:18084/status | python3 -m json.tool
```

## MCP SDK 导入失败

运行：

```bash
./scripts/install-local-deps.sh
```

如果使用虚拟环境，也可以：

```bash
python3 -m pip install -e mcp_server_apdv1
```

## `python3 -m venv` 失败

系统缺少 `python3-venv` 或 `python3-full`。

解决方式：

- 安装系统包。
- 或使用交付包内的 `./scripts/install-local-deps.sh`。

## `apdv1_tail` 没有看到任务日志

先确认请求已经被 worker 接手：

```bash
curl --noproxy '*' -sS http://127.0.0.1:18084/status | python3 -m json.tool
```

如果任务仍在 pending，日志还没有创建。active 后可以读取：

```bash
curl --noproxy '*' -sS \
  'http://127.0.0.1:18084/requests/<request_id>/tail?file=trace&lines=80'
```

## Docker 冲突

APDv1 的任务脚本应使用项目范围清理。不要为了清理单个任务运行全局 prune。

可以先看任务记录里的 `cleanup_project_names`，再按项目标签清理。

