# 部署失败项目分析

统计范围：
- 批次：`batch-20260421_022946-389737`
- 来源文件：`failure.txt`
- 只分析明确终态为 `COMPLETED_FAILED` 的任务

分析方法：
- 读取 `failure.txt` 提取非超时失败任务
- 关联任务目录下的 `last_message.txt`、`trace.txt`、`codex.log`
- 检查对应 `DP_LOGS/<project>/deploy.log`、`errors.log`、`summary.md`
- 依据最终停留步骤和最后明确错误信号判断失败原因

本批次部署失败项目共 `3` 个：
- `task-006` `https://github.com/koderover/zadig`
- `task-019` `https://github.com/zabbix/zabbix`
- `task-024` `https://github.com/OpenNMS/opennms`

## task-006 `koderover/zadig`

最终状态：
- `COMPLETED_FAILED`

失败步骤：
- `Phase 4/5` 官方安装完成后的外部入口验收阶段

执行到的程度：
- 按官方 `install_quickstart.sh` 跑了两套受控 Kubernetes 运行时：
  - 先 `kind`
  - 再 `k3d`
- 两次都完成了 Helm 安装
- 核心 Zadig pods 也已经 healthy

直接失败信号：
- 官方对外入口 `http://127.0.0.1:30080/` 持续返回 `HTTP 502`
- 同时，直接对 `svc/zadig-portal` 做 `kubectl port-forward` 后访问返回 `HTTP 200`

原因判断：
- 这说明 Zadig portal 服务本身是活的
- 真正失败的是“官方暴露的公共入口链路”而不是应用容器本身
- 换句话说，部署内部已起来，但外部网关/入口路径没有达到可用标准

结论：
- 卡在主部署完成后的“外部可访问性验收”
- 根因是“官方公共入口 `127.0.0.1:30080` 持续 502，未达到可用部署标准”
- 因为外部验收没过，所以没有进入主审计和 `Phase 6`

## task-019 `zabbix/zabbix`

最终状态：
- `COMPLETED_FAILED`

失败步骤：
- `Phase 4` 官方容器部署拉镜像/起栈阶段

执行到的程度：
- 已按官方 Zabbix 7.4 容器化路径准备 `zabbix-docker` compose 资产
- 先尝试官方 MySQL 方案
- 后切换到官方 PostgreSQL 方案
- 又因镜像问题退回 MySQL 路径并尝试 `mysql:8.0` 兜底

直接失败信号：
- 多次官方镜像拉取失败或异常，包括：
  - mirror `EOF`
  - `429 Too Many Requests`
  - `mysql:8.4-oracle` 解包错误：`Target.Size must be greater than zero`
- 轨迹中还出现镜像镜像站解析失败和单层下载长期卡住

原因判断：
- 失败点不在 Zabbix 应用初始化本身
- 而在宿主机 Docker 镜像拉取链路不稳定，导致关键官方镜像无法可靠获取
- 因为基础镜像拉不完整，栈就无法稳定启动，更无法进入 UI 验证

结论：
- 卡在官方容器部署的镜像获取阶段
- 根因是“宿主 Docker registry / mirror 链路异常，导致官方镜像反复拉取失败或损坏”
- 因此部署未进入可验证的 Zabbix Web UI 阶段

## task-024 `OpenNMS/opennms`

最终状态：
- `COMPLETED_FAILED`

失败步骤：
- 官方镜像路径失败后，转入源码构建路径，但卡在 Java 21 工具链引导阶段

执行到的程度：
- 先尝试官方镜像路径
- 因镜像获取受阻，转向仓库内官方源码构建思路
- 为源码构建补 Java 21 JDK 时，持续尝试外部下载和校验

直接失败信号：
- 第一条官方路径失败信号：
  - `opennms/horizon:35.0.5` 被宿主 Docker mirror 以 `403` allowlist 错误拦住
- 第二条源码构建路径失败信号：
  - 宿主没有可直接使用的 Java 21 toolchain
  - 外部 JDK `.deb` 下载出现坏文件尺寸/校验不匹配
  - 之后改单流 HTTP 下载仍然极慢并长期占用时间预算

原因判断：
- 不是 OpenNMS 业务逻辑启动后报错
- 而是两条前置路径都被宿主环境卡住：
  - 官方镜像路径被镜像站策略拦截
  - 源码构建路径缺 Java 21，补工具链又受网络/下载质量限制

结论：
- 先失败于官方镜像获取，再失败于源码构建前置工具链准备
- 根因是“宿主环境同时缺少可用官方镜像拉取链路和稳定的 Java 21 引导能力”
- 因此主部署未达到可运行 OpenNMS 实例的阶段

## 汇总结论

这 3 个 `COMPLETED_FAILED` 项目并不是同一种失败：

1. `zadig`
- 应用内部基本启动成功
- 但官方公共入口一直 `502`
- 属于“服务起来了，但对外入口不可用”

2. `zabbix`
- 失败发生在官方容器镜像获取阶段
- 属于“基础镜像供应链不稳定，栈根本起不来”

3. `opennms`
- 先被官方镜像路径拦住
- 又在源码构建前的 Java 21 引导阶段被网络/工具链问题卡住
- 属于“两条官方可接受路径都被宿主环境前置条件阻断”

整体上看，这批“部署失败”项目的主要根因不是统一的应用缺陷，而是三类不同问题：
- 外部入口可用性失败
- 容器镜像供应链失败
- 构建工具链前置条件失败
