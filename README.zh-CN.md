# 自适应项目治理（Adaptive Project Governance）

自适应项目治理（APG）是一套面向代码仓库和项目工作区的治理控制器。它的作用不是替代开发者做产品决策，也不是自动把代码发布到所有环境，而是把一次项目变更变成一条**有边界、可验证、可回滚、可追溯**的工程事务。

## 它解决什么问题

长期维护的项目通常同时存在旧代码、未提交修改、多个运行环境、外部服务和历史失败证据。仅凭“命令退出码为 0”或“某个包已经生成”，无法证明变更真的适合发布、安装、运行或推广。

APG 为这些判断建立独立证据：

- 变更前确认项目根目录、治理规则、Git 状态、依赖和已有证据；
- 将意图、范围、风险、验收条件、回滚方案和 owner approval 写入 ChangeRecord；
- 按受影响范围选择 Gate，并保存命令、状态、耗时和脱敏后的证据；
- 对文件和配置使用哈希校验，发现漂移时停止而不是覆盖；
- 把本地包、全局磁盘、运行中的宿主、provider/network 和下游项目分别验收。

## 标准工作流

1. `audit`：只读盘点，不写入目标项目。
2. `adopt`：在审核过的审计证据基础上，添加治理控制。
3. `plan-change`：预览一项有界变更；apply 必须有相应授权。
4. `check`：运行 fast、full 或 release Gates，并生成收据。
5. `doctor`：检查规则、基线、适配器和收据账本是否一致。

APG 保留历史收据和失败记录。遇到未知漂移、范围超出、关键 Gate 失败或回滚条件不满足时，事务会停止，后续重试需要新的边界和授权。

## 证据边界

本仓库 `main` 发布的是 APG `0.4.0-dev.20260814` 开发快照。核心包包含 91 个 manifest 声明文件以及 `MANIFEST.json`，共 92 个包文件；仓库另外保留 5 个公共 README、许可证和流程图文件。P3-A 至 P3-J 保持仓库验证完成，P4-1 定义宿主集成契约，P4-2A 选择官方 Codex App 作为首个宿主，P4-2B0 增加 `NONE`、`ROUTINE`、`MODERATE`、`HIGH` 和 `CRITICAL` 自适应路由。已治理项目从 `doctor` 进入，未治理项目从只读 `audit` 进入，并关闭隐式 skill 调用。APG 安装字节和全局 managed 路由块已经同步到该候选版本。

Codex 宿主 reload 与有界 APG 宿主 invocation 仍需独立验收。这个 GitHub 快照不自动证明：

- 宿主已经 reload 或成功调用 APG；
- runtime 已加载并验收新版本；
- provider、模型、网络端点或外部服务可用；
- 任何目标项目已经执行、部署、试点或正式发布；
- 已经创建正式 tag 或 GitHub Release。

这些阶段必须使用独立的 Change ID、授权、前置检查、成功证据、独立验收和回滚方案。

## 当前版本

- 版本：`0.4.0-dev.20260814`
- Manifest 声明文件数：91
- 核心包实际文件数：92（包含 `MANIFEST.json`）
- 仓库公共文件总数：97
- `MANIFEST.json` SHA-256：`ddbdc28adcd4de39ec24a0bf578b81ec3ab412867ce97913a68f947ef1dc8b21`
- 离线 guided-intake 示例：6 个
- 运行方式：开发快照、本地、离线、证据优先

不可变的 `v0.3.0` tag 保持不变；本次同步不创建 tag 或 GitHub Release。

详细操作约定见英文 [operator guide](docs/README.md)，技能契约见 [SKILL.md](SKILL.md)。
