# MCP Resources 说明

MCP Server 暴露以下只读 resources：

- `apdv1://status`
- `apdv1://requests/{request_id}`
- `apdv1://logs/service`
- `apdv1://logs/{request_id}/{file}`

## 使用原则

- tools 用于执行动作，例如提交、取消、中断。
- resources 用于被动读取状态和日志。

## resource 到内部接口的映射

```text
apdv1://status
  -> GET /status

apdv1://requests/{request_id}
  -> GET /requests/{request_id}

apdv1://logs/service
  -> GET /logs

apdv1://logs/{request_id}/{file}
  -> GET /requests/{request_id}/tail?file=<file>
```

