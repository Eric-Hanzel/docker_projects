# MCP Tools 说明

## `apdv1_health`

检查 APDv1 HTTP API 是否可达。

返回示例：

```json
{
  "ok": true,
  "service": "apdv1-deploy-api"
}
```

## `apdv1_deploy`

提交单个部署目标。

输入：

```json
{
  "url": "https://github.com/org/project",
  "extras": {}
}
```

说明：

- `url` 必填。
- `extras` 可选，用于传递 license、token、版本约束、交付模式等额外字段。
- 默认交付模式是 `{"delivery_mode":"portable-deliverable","portable_final_required":true}`，生成目录型 portable final bundle。
- 显式本地运行可传 `{"delivery_mode":"local-run","portable_final_required":false}`；这只适合需要现场可访问服务、不需要 portable final 的任务。
- 镜像型交付传 `{"delivery_mode":"portable-deliverable","portable_final_required":true,"image_bundle":true}`。
- 兼容旧写法：`delivery_format=portable|directory|image` 仍可被 MCP 层转换，但新调用不要再使用它。
- 返回 `request_ids`。

字段明细：

| 字段 | 位置 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `url` | 顶层 | 无 | 必填目标 URL。 |
| `delivery_mode` | `extras` 或 batch target | `portable-deliverable` | 可选 `portable-deliverable` 或 `local-run`。 |
| `portable_final_required` | `extras` 或 batch target | portable 为 `true`，local-run 为 `false` | 控制是否要求 portable final。 |
| `image_bundle` | `extras` 或 batch target | `false` | `true` 时走镜像型 final 输出。 |
| `project_name` | `extras` 或 batch target | 自动推断 | 指定输出目录基名。 |
| `version_requirement` | `extras` 或 batch target | 未指定 | 指定版本/tag/commit/稳定版要求。 |
| `license_key`、token 类字段 | `extras` 或 batch target | 未指定 | 传给部署 agent，最终文档应脱敏。 |

## `apdv1_deploy_batch`

批量提交多个部署目标。

输入：

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

每个 target 必须包含 `url`。除 `url` 外的字段会作为 extras 传给部署 agent，例如 `license_key`、`version_requirement`、`delivery_mode`、`portable_final_required`、`image_bundle`。

镜像型 final 只需要在对应 target 加 `image_bundle=true`。local-run 则使用 `delivery_mode="local-run"` 和 `portable_final_required=false`。

返回示例：

```json
{
  "ok": true,
  "request_ids": [
    "req-20260610_120001-abcd1234",
    "req-20260610_120002-bcde2345"
  ],
  "queue_counts": {
    "pending": 2,
    "active": 0,
    "completed": 0,
    "failed": 0,
    "canceled": 0
  }
}
```

## `apdv1_tasks`

用更适合用户阅读的格式列出任务。

输入：

```json
{
  "limit": 20,
  "url": "https://github.com/org/project"
}
```

说明：

- `url` 可选，不传时列出所有可见任务。
- 返回会按 `pending`、`active`、`completed`、`failed`、`canceled` 分组。
- 每条记录会简化为 `request_id`、`status`、`url`、`project_name`、时间和 `run_dir`。

适合回答：

- 当前还有哪些任务没完成？
- 哪些任务完成了？
- 哪些任务失败了？
- 我该复制哪个 `request_id` 去查详情？

## `apdv1_result`

查看用户友好的任务结果摘要。

输入：

```json
{
  "request_id": "req-...",
  "url": "https://github.com/org/project",
  "include_last_message": true,
  "trace_tail_lines": 0
}
```

说明：

- `request_id` 可选。
- `url` 可选。
- 两者都不传时，默认选择当前可见的最新任务。
- 有多个任务时，建议传 `request_id` 精确查询。

返回重点：

- 是否成功
- 当前状态
- 项目名
- 运行目录
- 所选 final 的 `Deliverable` 产物目录，例如 `Deliverable/<project>-final` 或 `Deliverable/<project>-image-final`
- 所选 final 的 `DP_LOGS` 日志目录，例如 `DP_LOGS/<project>-final` 或 `DP_LOGS/<project>-image-final`
- `README_QUICKSTART.md`
- `verification_result.json`
- `audit_result.json`
- `summary.md`
- `last_message`

这比直接看底层 HTTP `/status` 更适合普通用户。

## `apdv1_tail`

读取服务日志或任务日志。

输入：

```json
{
  "request_id": "req-...",
  "file": "trace",
  "lines": 80
}
```

`request_id` 为空时读取服务日志。

任务日志支持：

- `trace`
- `log`
- `events`
- `last-message`
- `protocol`
- `record`

## `apdv1_cancel`

取消 pending 请求，或请求中断匹配的 active 请求。

输入：

```json
{
  "request_id": "req-..."
}
```

返回：

- pending 请求：`{"ok": true, "action": "canceled", ...}`，队列记录移动到 `canceled/`。
- active 请求：`{"ok": true, "action": "abort_requested", ...}`，runner 收到控制信号后中断任务。
- terminal 请求：`{"ok": true, "action": "already_terminal", ...}`。

清理边界：

- pending cancel 不启动任务，因此没有运行资源需要清理。
- active cancel 会走 abort 收尾，执行项目范围 Docker 清理和失败产物清理。
- 不会自动删除 `app_server/runs/`、`app_server/results/` 或 queue 历史记录。

## `apdv1_abort_current`

中断当前 active 请求。

输入：

```json
{
  "confirm": true
}
```

没有 `confirm=true` 时不会执行。

执行后返回 `{"ok": true, "action": "abort_requested", "request_id": "req-..."}`。实际中断和清理由 worker 在当前任务收尾阶段完成。
