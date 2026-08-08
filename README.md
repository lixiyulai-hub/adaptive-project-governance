# Adaptive Project Governance (APG) 0.3.0

[English](#english) | [中文](#中文)

![APG governance workflow](docs/diagrams/apg-governance-workflow.svg)

## 中文

### APG 是什么

Adaptive Project Governance（APG）是一套面向代码库和自动化项目的、以审计证据为先的治理控制器。它把一次变更从“有人说做过”转化为可检查的工程记录：先确认项目根、规则和当前状态，再界定变更路径、验证影响、运行 Gate，并保留 Receipt 和可执行的回滚边界。

APG 的目标不是增加流程负担，也不是替代工程判断。它为多人协作、长周期演进和 AI 代理执行提供共同的事实基础：**什么被批准、什么实际改变、哪些检查通过、出现问题时能回到哪里**。

### 它解决的问题

- 变更前不清楚项目根、规则、Git 状态或已有证据，导致修改落在错误位置。
- preview、安装、运行时激活、外部发布和下游试用被混为一谈，离线通过被误称为正式上线。
- 自动化修改缺少明确路径范围，历史证据、用户未提交变更或无关输出容易被覆盖。
- 测试只记录 exit code，缺少输入、命令、结果、时间和关联 ChangeRecord，复核时无法回答“为什么相信它”。
- 回滚只是一句说明，没有验证目标、哈希和最小作用域。

### 核心对象

| 对象 | 作用 |
| --- | --- |
| `audit` | 只读识别项目、风险、已有治理状态和潜在漂移。 |
| `init` / `adopt` | 为新项目准备初始化，或以 Route B 方式增量纳入已有项目，不重写既有架构。 |
| `plan-change` | 为高风险或结构性变更生成不可变 ChangeRecord、影响分析和审批范围。preview 不是执行授权。 |
| `check` | 按受影响 Gate 计划执行快速或完整验证，并记录每个 Gate 的证据。 |
| `doctor` | 检查治理文件、基线、收据、适配器和当前状态是否自洽。 |
| ChangeRecord | 变更的目标、范围、验收条件、非目标、风险、遥测和回滚契约。 |
| Gate | 可重复运行的验证命令；成功不只看退出码，也关联命令、结果和证据。 |
| Receipt | 审计收据，记录谁、何时、以何种输入、在哪个范围内执行了什么。 |
| Rollback | 以最小路径和精确后置状态为前提的恢复动作，不删除无关文件。 |

### 标准工作方式

1. **检查事实**：定位真实项目根，阅读本地规则，读取 Git 状态；已有 `.governance/project.toml` 时先运行 `doctor`。
2. **选择接入路径**：未接入项目先只读 `audit`；新项目准备 `init` preview；已有或导入项目采用 Route B 的 `adopt` preview。
3. **界定变更**：列出准确 changed paths、验收条件、非目标和回滚边界。高风险或结构性工作使用 `plan-change`。
4. **获得授权后实施**：preview 只用于审阅。实际写入必须由项目所有者对具体根目录和路径范围授权。
5. **验证并留证**：运行计划所要求的 Gate，读取结果、哈希、清单和 post-state；失败先停在首个失败点并保留证据。
6. **交付或恢复**：交付包含 ChangeRecord、Receipt、检查结果和回滚说明。回滚前先验证目标仍符合记录的后置状态。

### 五个彼此独立的外部边界

一个本地包的验证通过，不会自动完成任何外部阶段。以下事务各自需要独立授权、执行证据和回滚记录：

1. **公开发布（public publication）**：把已验收的包或文档发布到公共仓库、标签或 Release。
2. **全局推广（global promotion）**：安装或链接到工具的全局技能根，确认实际目标和发现结果。
3. **宿主/运行时激活（host/runtime）**：重启或重新加载宿主，并确认它在新的运行时中发现了目标。
4. **Provider/网络验证（provider/network）**：只有在单独授权后调用外部 provider 或网络服务并记录结果。
5. **下游试点（downstream pilot）**：在独立项目中进行真实使用验收，并保留可比较的结果。

这五类状态不能互相推断。例如，GitHub 上存在 Release 不代表所有本地客户端都已完成运行时激活；本地静态检查通过也不代表 provider 或下游试点已完成。

### 支持的工作环境

APG 通过项目根的 `AGENTS.md` 和本地技能适配器接入代理工作流。当前包可用于 Codex、Claude Code、Cursor 及共享技能根的路由场景；每个宿主的实际发现、加载和运行时验收仍必须分别记录。APG 不安装 provider、不发送网络请求，也不替代宿主平台的权限与发布机制。

### 快速开始

在项目根运行以下命令。先使用只读命令确认状态；只有在查看 preview 且得到该项目根的明确授权后，才使用 `--apply`。

```powershell
$apg = 'C:\Users\Administrator\.codex\skills\adaptive-project-governance\scripts\project_governance.py'

# 已接入项目：诊断治理状态
python -B -X utf8 $apg doctor . --json

# 未接入项目：只读审计
python -B -X utf8 $apg audit . --json

# 高风险或结构性变更：先创建 preview
python -B -X utf8 $apg plan-change . --request .\change-request.json --json

# 获得针对该范围的授权后，写入 ChangeRecord 和收据
python -B -X utf8 $apg plan-change . --request .\change-request.json --apply --json

# 执行计划要求的验证阶段
python -B -X utf8 $apg check . --phase full --json
```

### 适用范围与非目标

APG 适用于需要保留变更证据、控制范围和可恢复性的应用、脚本、自动化、导入开源项目与多代理协作项目。它不替代源代码审查、CI、发布平台、基础设施权限、服务监控或人工验收；它把这些活动的边界与证据串联起来。

### 0.3.0 包身份

`v0.3.0` 是已接受的本地 APG 包。`MANIFEST.json` 定义规范文件集合，可独立计算 SHA-256。对 `main` 分支的说明文档更新不重写该不可变标签，也不改变已接受包的身份。

查看 [操作指南](docs/README.md)、[技能契约](SKILL.md) 和 [流程工程图](docs/diagrams/apg-governance-workflow.drawio)。

---

## English

### What APG Is

Adaptive Project Governance (APG) is a repository-scoped, audit-first controller for software and automation work. It turns a change from an informal claim into inspectable engineering evidence: establish the project root, local rules, and current state; bound the change; validate its impact; run Gates; and retain Receipts and a verifiable rollback boundary.

APG does not replace engineering judgment. It gives human collaborators and coding agents a shared factual record of **what was authorized, what changed, which checks passed, and where recovery ends**.

### What It Addresses

- Changes made without first identifying the real project root, local rules, Git state, or existing evidence.
- Previews, installation, runtime activation, public publication, and downstream use treated as one completed stage.
- Automation that overwrites user work, historical evidence, or unrelated outputs because its path boundary is unclear.
- Test reports that preserve only an exit code and cannot answer which command, input, result, or ChangeRecord supports the claim.
- Rollback instructions that have no verified target, post-state hash, or narrow scope.

### Core Building Blocks

| Building block | Purpose |
| --- | --- |
| `audit` | Read-only discovery of project state, risk, governance evidence, and drift. |
| `init` / `adopt` | Prepare a new project or incrementally adopt an existing project through Route B without rewriting its architecture. |
| `plan-change` | Produce an immutable ChangeRecord, impact analysis, and approval boundary for high-risk or structural work. A preview is not authorization. |
| `check` | Execute the affected fast or full Gate plan and record evidence for each Gate. |
| `doctor` | Verify that governance files, baseline, receipts, adapters, and state projections remain coherent. |
| ChangeRecord | Contract for intent, exact paths, acceptance, non-goals, risk, telemetry, and rollback. |
| Gate | Repeatable validation command whose result is connected to command, outcome, and evidence. |
| Receipt | Audit record of who ran what, when, with which inputs, and inside which authorized scope. |
| Rollback | Minimal recovery action that first verifies the recorded post-state and preserves unrelated files. |

### Operating Workflow

1. **Establish facts**: locate the physical root, read local rules, inspect Git; run `doctor` first when `.governance/project.toml` exists.
2. **Choose an adoption path**: use read-only `audit` for an unadopted project; prepare `init` for a new one, or Route B `adopt` for an existing/imported one.
3. **Bound the work**: state exact changed paths, acceptance, non-goals, and rollback. Use `plan-change` for high-risk or structural work.
4. **Implement only after authorization**: a preview is review material, not write authority. The owner authorizes the specific root and paths.
5. **Validate and retain evidence**: run the required Gates; inspect results, hashes, manifests, and post-state. Stop on the first failure and preserve the evidence.
6. **Deliver or recover**: hand over the ChangeRecord, Receipts, check results, and rollback contract. Verify the post-state before rollback.

### Independent External Boundaries

Passing a local package check does not complete any external stage. Each of these requires separate authorization, execution evidence, and rollback evidence:

1. **Public publication**: publish a package or documentation to a public repository, tag, or Release.
2. **Global promotion**: install or link to a tool's global skill root and verify the resolved target and discovery result.
3. **Host/runtime activation**: reload or restart the host and verify that a fresh runtime discovers the target.
4. **Provider/network validation**: call an external provider or network service only under a separate transaction and record the result.
5. **Downstream pilot**: accept real use in an independent project with comparable evidence.

No stage implies another. A GitHub Release does not prove runtime activation in every local client, and an offline check does not prove provider or downstream acceptance.

### Environments and Boundaries

APG integrates with agent workflows through project-root `AGENTS.md` rules and local skill adapters. This package can be used with Codex, Claude Code, Cursor, and shared-skill routing, but each host's discovery, loading, and runtime acceptance remains a separate recorded fact. APG does not install providers, send network traffic, or replace platform permission and release mechanisms.

### Quick Start

Run from the project root. Start with read-only inspection. Use `--apply` only after reviewing the preview and receiving explicit authorization for that project root and bounded path set.

```powershell
$apg = 'C:\Users\Administrator\.codex\skills\adaptive-project-governance\scripts\project_governance.py'
python -B -X utf8 $apg doctor . --json
python -B -X utf8 $apg audit . --json
python -B -X utf8 $apg plan-change . --request .\change-request.json --json
python -B -X utf8 $apg plan-change . --request .\change-request.json --apply --json
python -B -X utf8 $apg check . --phase full --json
```

### Scope and Non-Goals

APG fits applications, scripts, automations, imported open-source work, and multi-agent projects that need evidence, bounded changes, and recoverability. It does not replace code review, CI, release systems, infrastructure permissions, service monitoring, or human acceptance. It makes their boundaries and evidence explicit.

### Package Identity

`v0.3.0` is the accepted local APG package. `MANIFEST.json` defines its canonical file set and can be independently hashed with SHA-256. Documentation updates on `main` do not rewrite the immutable tag or change the accepted package identity.

See the [operator guide](docs/README.md), [skill contract](SKILL.md), and [editable workflow diagram](docs/diagrams/apg-governance-workflow.drawio).
