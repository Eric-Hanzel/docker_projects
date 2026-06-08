# 全部失败项目根因总览

批次：`batch-20260421_022946-389737`

目标：
- 把所有失败项目压缩成一页
- 让人一眼看出每个项目“失败类型、卡点、根因、优先处理方向”

## 一眼看懂

本批次失败项目共 `11` 个，可归为 5 类：

1. `Phase 6` 重放太重，1 小时预算不够
- `tektoncd/pipeline`
- `argoproj/argo-workflows`
- `fluxcd/flagger`
- `NagiosEnterprises/nagioscore`

2. 实际部署已基本成功，但卡在审计/收尾编排
- `argoproj/argo-cd`
- `thanos-io/thanos`

3. 主审计修复未收敛，运行态一致性没闭环
- `librenms/librenms`

4. 主部署本身失败于外部入口或运行前置条件
- `koderover/zadig`
- `zabbix/zabbix`
- `OpenNMS/opennms`
- `centreon/centreon`

5. 宿主环境/供应链问题突出
- Docker mirror / registry 不稳定
- 大体量镜像或系统包下载过慢
- Java 21 / 构建工具链引导不稳

## 总表

| task_id | 项目 | 状态 | 卡住阶段 | 一句话根因 | 归类 | 优先级 |
|---|---|---|---|---|---|---|
| task-006 | `koderover/zadig` | `COMPLETED_FAILED` | 主部署后的外部入口验收 | 内部 portal 已健康，但官方公共入口 `127.0.0.1:30080` 持续 `HTTP 502` | 入口可用性失败 | 高 |
| task-008 | `tektoncd/pipeline` | `TIMED_OUT` | `Phase 6` final bundle 重放 | 为修补 final audit 日志证据而整包重放，Tekton 控制面重建太慢，1 小时内没跑完 | Phase 6 重放过重 | 中 |
| task-009 | `argoproj/argo-cd` | `TIMED_OUT` | `Phase 6` 复审收尾 | bundle-only 验证其实已通过，但父流程没在超时前完成 audit 结果回写和终态落账 | 审计/收尾编排超时 | 高 |
| task-010 | `argoproj/argo-workflows` | `TIMED_OUT` | `Phase 6` helper image 构建 | 构建中下载 `kubectl` / `kind` / `argo` 二进制长时间无进展 | Phase 6 构建下载过慢 | 中 |
| task-014 | `fluxcd/flagger` | `TIMED_OUT` | `Phase 6` kind 集群重建 | final bundle replay 停在 `Creating cluster` / `Preparing nodes`，kind 初始化耗时过长 | Phase 6 集群启动过慢 | 中 |
| task-017 | `librenms/librenms` | `TIMED_OUT` | `Phase 5.5` 主审计修复 | 审计指出 poller/scheduler 运行态不一致，修复后再次 `validate.php` 校验没有在时限内收敛 | 运行态一致性问题 | 高 |
| task-019 | `zabbix/zabbix` | `COMPLETED_FAILED` | 官方容器部署拉镜像 | Docker mirror / registry 链路不稳，镜像拉取报 `EOF`、`429`、解包异常，栈起不来 | 镜像供应链失败 | 高 |
| task-020 | `NagiosEnterprises/nagioscore` | `TIMED_OUT` | `Phase 6` image build | final bundle 构建时 Debian 依赖包过大，APT 下载/安装阶段吃满时间预算 | Phase 6 系统包安装过慢 | 中 |
| task-023 | `thanos-io/thanos` | `TIMED_OUT` | `Phase 6` 最终审计 | final bundle 已验证成功，但 `portable_bundle_auditor` 没在任务时限内返回 | 审计子流程超时 | 高 |
| task-024 | `OpenNMS/opennms` | `COMPLETED_FAILED` | 官方镜像失败后转源码构建 | 官方镜像被 Docker mirror `403` 拦住，源码构建又缺稳定 Java 21 引导能力 | 前置环境/工具链失败 | 高 |
| task-025 | `centreon/centreon` | `TIMED_OUT` | 官方 unattended 安装修复重试 | 上游 `unattended.sh` 与 `25.10` Debian 12 包名不匹配，修补后安装进入长包配置阶段但未在时限内结束 | 上游安装脚本不一致 + 安装耗时过长 | 高 |

## 根因拆解

### 1. 真正属于“项目本身/官方流程”的问题

| 项目 | 根因 |
|---|---|
| `koderover/zadig` | 官方推荐入口链路不可用，内部服务健康但外部访问始终 `502` |
| `librenms/librenms` | 官方部署跑起来后，运行态一致性校验不过，至少 poller / scheduler 状态没有闭环 |
| `centreon/centreon` | 上游官方 `unattended.sh` 与 `25.10` Debian 12 仓库包名不一致，脚本本身存在版本错配 |

### 2. 主要属于“宿主环境 / 供应链 / 网络”的问题

| 项目 | 根因 |
|---|---|
| `zabbix/zabbix` | Docker mirror / registry 不稳定，官方镜像反复拉取失败或损坏 |
| `OpenNMS/opennms` | 官方镜像被 mirror allowlist 拦截，源码构建又受 Java 21 下载与引导能力限制 |
| `argoproj/argo-workflows` | 构建期外部二进制下载过慢或无进展 |
| `NagiosEnterprises/nagioscore` | 系统依赖安装过大，APT 过程耗时过长 |

### 3. 主要属于“流程编排 / 审计收尾”的问题

| 项目 | 根因 |
|---|---|
| `argoproj/argo-cd` | 已通过 final 验证，但父流程未及时完成审计结果回写 |
| `thanos-io/thanos` | final bundle worker 已成功，但 auditor 返回过慢导致任务超时 |
| `tektoncd/pipeline` | 为补审计证据触发整包重放，重放成本太高 |
| `fluxcd/flagger` | final bundle replay 需要重建 kind 集群，时长超过预算 |

## 最值得优先处理的共性问题

如果目标是下一批次尽量提升成功率，优先级建议如下：

1. 先处理“收尾超时但实际已成功”的项目
- `argo-cd`
- `thanos`

原因：
- 这两项离成功最近
- 优化 audit 回写 / 子代理等待策略，收益最大

2. 再处理 `Phase 6` 过重项目
- `tekton`
- `argo-workflows`
- `flagger`
- `nagioscore`

原因：
- 它们不是明确错误，而是 replay/build/startup 成本过高
- 重点应放在减少重放成本、缓存工具/镜像、缩短 final bundle 验证路径

3. 然后处理宿主供应链问题
- `zabbix`
- `opennms`

原因：
- 这类失败不是项目代码问题
- 不解决镜像源、下载源、JDK 引导能力，类似项目还会重复失败

4. 最后处理真正的项目/上游流程问题
- `zadig`
- `librenms`
- `centreon`

原因：
- 需要针对单项目做更细的专项修复

## 最终结论

这一批失败项目里，真正“一启动就错”的并不多。

更核心的结论是：
- 一部分项目其实已经接近成功，但卡在 audit / 收尾编排
- 一部分项目主要输在 `Phase 6` replay 成本太高
- 还有一部分不是项目问题，而是宿主镜像供应链和工具链准备不稳定

如果只看“最一目了然”的根因排序：

1. `Phase 6` 太重，超时预算不够
2. audit / 子代理收尾慢，成功结果没及时落账
3. Docker mirror / 下载链路 / Java 引导不稳
4. 少数项目存在真实的运行态或上游安装脚本问题
