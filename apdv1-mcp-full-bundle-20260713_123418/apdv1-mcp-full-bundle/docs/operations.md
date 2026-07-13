# 运维说明

## 启动服务

```bash
./scripts/start-worker.sh
./scripts/start-api.sh
```

## 自检

```bash
./scripts/doctor.sh
```

doctor 会检查：

- Python 包能否导入。
- MCP SDK 是否可用。
- APDv1 HTTP API 是否可达。
- 队列状态是否可读取。

## 查看服务状态

```bash
curl --noproxy '*' -sS http://127.0.0.1:18084/status | python3 -m json.tool
```

MCP 用户更推荐调用：

```text
apdv1_tasks
```

查看某个任务的最终摘要和产物路径：

```text
apdv1_result
```

## 查看服务日志

```bash
tail -f apdv1/.codex/state/app_server_service.log
```

## 查看某个请求日志

```bash
curl --noproxy '*' -sS \
  'http://127.0.0.1:18084/requests/<request_id>/tail?file=trace&lines=100'
```

## 输出目录

部署任务运行后会写入：

- `apdv1/Deliverable/`
- `apdv1/DP_LOGS/`
- `apdv1/app_server/runs/`
- `apdv1/app_server/results/`
- `apdv1/.codex/state/`

这些都是运行时目录，不会进入 `scripts/package.sh` 生成的最终 tar.gz。

## 任务模型

worker 是单任务模型：

- 同一时间只处理一个项目。
- 新任务进入 pending 队列。
- active 任务完成后才会处理下一个。
- active 任务可通过 `apdv1_abort_current(confirm=true)` 中断。

## 重新打包

```bash
./scripts/package.sh
```

输出在：

```text
dist/apdv1-mcp-full-bundle-YYYYMMDD_HHMMSS.tar.gz
```
