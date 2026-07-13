# 安全说明

APDv1 是自动部署系统，具备执行命令、拉取源码、构建镜像、启动容器、写入交付物和日志的能力。把它封装成 MCP 后，MCP 客户端也间接拥有触发这些动作的能力。

## 推荐默认配置

- MCP 使用 stdio transport。
- APDv1 HTTP API 只绑定 `127.0.0.1`。
- 在专用部署主机上运行。
- 不要把 API 或 MCP transport 暴露到公网。
- 不要把密钥写进示例文件或公开日志。

## 中断工具

`apdv1_abort_current` 需要 `confirm=true`，用于中断当前 active 任务。MCP 对外不暴露停止 worker 的工具，避免误操作。

## 输出和敏感数据

部署结果和日志会写入：

- `apdv1/Deliverable/`
- `apdv1/DP_LOGS/`
- `apdv1/app_server/runs/`
- `apdv1/app_server/results/`
- `apdv1/.codex/state/`

这些目录可能包含部署日志、配置、初始化数据或测试凭据。交付给第三方前应审查并清理。

## Docker 清理

APDv1 任务应使用项目范围的 Docker cleanup。不要为了清理单个任务而运行全局命令，例如：

```bash
docker system prune
docker volume prune
docker image prune -a
```
