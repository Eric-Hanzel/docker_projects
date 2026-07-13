# 安装说明

## 方式一：本地依赖目录，推荐交付使用

这种方式不依赖系统是否安装 `python3-venv`，依赖会安装到当前 bundle 的 `.deps/` 目录。

```bash
cd apdv1-mcp-full-bundle
./scripts/install-local-deps.sh
```

安装完成后，MCP 客户端应调用：

```bash
/absolute/path/to/apdv1-mcp-full-bundle/scripts/start-mcp-stdio.sh
```

## 方式二：Python 虚拟环境

如果系统支持 `python3 -m venv`，也可以使用虚拟环境：

```bash
cd apdv1-mcp-full-bundle
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e mcp_server_apdv1
```

如果 `python3 -m venv` 报错缺少 `ensurepip`，说明系统没有安装 `python3-venv` 或 `python3-full`。可以安装系统包，或者改用上面的 `./scripts/install-local-deps.sh`。

## 前置检查

```bash
command -v codex
docker version
docker compose version
python3 --version
```

## 启动 APDv1 服务

```bash
./scripts/start-worker.sh
./scripts/start-api.sh
./scripts/doctor.sh
```

## 配置 MCP 客户端

编辑 [config/mcp-client.example.json](config/mcp-client.example.json)，把 `/absolute/path/to/apdv1-mcp-full-bundle` 改成真实路径，然后放入你的 MCP 客户端配置。

