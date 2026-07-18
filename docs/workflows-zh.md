# 工作流 —— 生产与开发检查清单（Workflows）

> **本文件是 [`workflows.md`](workflows.md) 的中文翻译；一切以英文版为准**（翻译可能滞后于英文原文）。所有代码
> 标识符、文件路径、CLI 命令与参数、环境变量（`KLOOP_*`）、`[proxy]` / `[production]` / `[to build]` 标签，以及
> 治理状态名（Core / Provisional-Core / Candidate / Fixture / Archived 等）一律保留英文原文；文内链接仍指向英文
> 权威文档（它们是单一事实来源）。

> 两份可勾选的检查清单，每个环境一份，反映**当前的诚实状态**（Core + 唯一的 Provisional-Core 默认项；`[to build]`
> = 尚未自动化）。开发机 ↔ 生产的环境划分，以及 `[proxy]` / `[production]` 标签约定见
> [`environments.md`](environments.md)；哪些能力属于 Core、哪些只是脚手架见 [`capabilities.md`](capabilities.md)；
> 权威的 18 节生产 SOP 见 [`production-guide.md`](production-guide.md)。本文是覆盖它们的顶层清单。

---

## JIRA 到提交的工作流 —— 端到端概念（The JIRA-to-commit workflow）

GroundLoop 存在的意义，就是这一条**闭环**：从一张 **JIRA Bug 工单 + 其故障日志**，走到一次**已绑定的 Gerrit 变更
（Change）**，并留下一条**可追溯的 JIRA↔commit 链**——把人工的“130+ 个仓库里，这个缺陷归谁、修在哪里”的分诊
自动化。三条属性定义了它：

1. **由确定性控制平面掌控流程。** `core/run_ticket` 用普通 Python 顺序编排这八个阶段；模型只在每一步提供*内容*
   （抽取出的信号、仓库排名、候选补丁），从不决定下一步做什么。
2. **闭环不见真值（oracle-blind）。** 归属仓库是一个*预测输出*，**绝不是输入**；`run_ticket` 没有任何 oracle
   参数，因此打分是严格**独立的离线过程**——一次执行同时既是一次真实的修复尝试，又是一个被计分的基准样本，而基准
   无法污染这次尝试。
3. **两端仍是 mock。** JIRA 接入（`IssueSource`）与 Gerrit 提交/绑定（`ChangeSink`）目前分别是
   `MockJira` / `MockGerrit`；而*中间段*（match → localize → fix）跑在真实基础设施上。

### 端到端的八个阶段

> （下图与英文版一致，为保持 ASCII 对齐未作翻译。①–⑧ 为八个阶段。）

```
 ┌───────────────────────── JIRA end · IssueSource  (MockJira today) ─────────────────────────┐
 │  Bug ticket = summary + description + FAILURE LOGS  (logcat / stack / native #00 pc … )     │
 │                                    the logs are the primary evidence                        │
 └────────────────────────────────────────────┬───────────────────────────────────────────────┘
                                               │  ① intake      issues.fetch(ticket_id)
                                               ▼
                                     ② extract     → Signals (exception · stack frame · class ·
                                               │                 method · .so · error code)
                                               ▼
                            ③ MATCH   index.rank_repos → owning repo     ◄════ THE GATE
                                               │      top-1 = prediction        (a predicted output +
                                               ▼                                 hidden-oracle field,
                            ④ materialize   estate.materialize → work-tree       NEVER a loop input)
                                               │      (checkout the chosen repo)
                                               ▼
                            ⑤ localize   index.retrieve → suspicious files       (plain FTS5 keyword)
                                               │
                                               ▼
                            ⑥ fix   fixer.propose → Patch   — or ABSTAIN         (never fabricate)
                                               │
                                               ▼
 ┌───────────────────────── Gerrit end · ChangeSink  (MockGerrit today) ──────────────────────┐
 │  ⑦ submit   changes.submit → Change   (Change-Id + JIRA key in the subject)                 │
 │  ⑧ bind     changes.bind → link Change ↔ ticket  +  transition the ticket (write-back)      │
 │             ▶ the append-only, auditable chain: discovery → logs → repo → localization →     │
 │               fix → commit ↔ ticket   (the traceable JIRA↔commit chain)                     │
 └─────────────────────────────────────────────────────────────────────────────────────────────┘

 ┄┄┄ separate offline pass · ORACLE-BLIND ┄┄►  grade(RunRecord, hidden oracle) → scorecard
      the loop emits its prediction with NO ground truth in scope; the grader reads the oracle after.
```

- **JIRA 端（接入 + 回写）。** 工单经 `IssueSource.fetch` 进入；完成时 bind 阶段把变更与工单关联并流转工单状态
  （`IssueSource.transition` / `post_comment` 是回写接口）。目前 `MockJira` 从文件系统读取工单——**尚无实时 REST
  拉取或回写**。
- **中间段（真正的工作，跑在真实基础设施上）。** `extract` → **`MATCH`** 归属仓库（关卡——`rank_repos` 的 top-1，
  经由真实跨仓库 atlas 上的 component-affinity 先验）→ `materialize`（用 `--repos` 真实检出）→ `localize`（纯 FTS5
  的 `retrieve`）→ `fix`（`PlanningFixEngine` 给出有据可依的补丁，或宁可**弃权（abstain）**也不编造）。
- **Gerrit 端（提交 + 绑定）。** 补丁变为一个 `Change` 并绑定到工单。目前 `MockGerrit` 合成一个按内容哈希的
  Change-Id + 一份本地台账——**尚无实时 Gerrit 推送**。

### 这对当前状态意味着什么

在迄今唯一一次 `[production]` 运行中，闭环把**全部 8 个阶段跑到了一次 *mock* 的已绑定变更**（manifest 记录
`change_sink=mock`）：JIRA↔commit 链在*机制上*已端到端跑通，但由于两端是 mock，它**还不是一条真实、实时、可追溯的
链路**。补上这一缺口，是通往完全真实 Core 的余下增量工作——一个实时的 JIRA REST `IssueSource`（拉取 + 评论/流转
回写）与一个实时的 Gerrit `ChangeSink`（真实变更 + 可验证的 JIRA↔commit 绑定）；两者都是下方分阶段表中的
`[to build]` 行。两端*之间*的一切都是 Core 或 Core-when-configured，且已在真实 GEI 数据上运行过。

---

## 生产工作流（Production workflow）

**Production 是什么：** 针对**真实 GEI 数据**运行、得到一份已打分、可追溯结果的最小 Core 系统。下面的一切只使用
[`capabilities.md`](capabilities.md) 中的 **Core** 组件——外加自 2026-07-13 起唯一的 **Provisional-Core** 默认项
（Bug Plan Mode / `--fixer plan`：基于故障安全（fail-safe）机制 + 安全性论证而默认开启，其*有效性*仍受生产门控）。

### 第 1 层 —— 运行时闭环（机制：一张工单，8 个确定性阶段）

`core/run_ticket` 不见真值（oracle-blind）——它从不看到答案；打分是独立的离线过程。

1. **intake** —— `MockJira` 从文件系统读取工单。`[to build: live JIRA REST source]`
2. **extract** —— `ComponentExtractor` / `AndroidSignalExtractor` 抽取 component + 日志信号。
3. **match** —— component→repo 的**亲和先验（affinity prior）**（RRF 融合到 `AtlasIndex` 上）挑出归属仓库。
   *配置了亲和工件时为 Core；否则诚实地回退到 `flood`（并如实记录为 `flood`）。*
4. **materialize** —— `CheckoutEstate` 检出所选仓库（`--repos`）。*省略 `--repos` ⇒ `MockEstate` 空工作树 ⇒ fix
   无法打分。*
5. **localize** —— `AtlasIndex.retrieve` = 在符号单元上做**纯 FTS5 关键词检索**。
6. **fix** —— `PlanningFixEngine`（“Bug Plan Mode”，即 `--fixer plan` **默认项**，Provisional-Core）先规划 →
   过闸 → 重规划 → 宁可**弃权（abstain）**也不产出越界/无据的补丁（fail-safe）。`ModelPatchEngine`
   （`--fixer model`）是单发（single-shot）的退出项。*有效性（`resolved_rate`）受生产门控——默认项是一次安全性
   选择（0 编造），尚不是已测得的解决率胜出。*
7. **submit** —— `MockGerrit` 记录一次变更。`[to build: live Gerrit sink]`
8. **bind** —— `MockGerrit` 关联 change↔ticket。`[to build: real traceable JIRA↔commit chain]`

> 每个阶段可用的全部特性——所有状态、证据与文件引用——见下方的**分阶段能力全景表（Per-stage feature map）**。

### 第 2 层 —— 运维 SOP（每一次生产运行）

**预检（Pre-flight）**
- [ ] 加载凭据（不会自动加载）：`set -a; . ./.env; set +a`
- [ ] **`KLOOP_DEV` 必须为未设置** —— 它是解锁密封夹具（`--index` / `--fixer canned` / `--case`）的 dev-gate；
  生产运行保持其关闭（仅密封 / Type-1 运行会设 `KLOOP_DEV=1`）
- [ ] **`KLOOP_LABS`：真实 Core 生产运行时保持未设置**（默认仍为 `component`/`atlas`/`plan`）。**仅**在**生产
  *测试*** 部署中设 `KLOOP_LABS=1`（或 `--profile labs`），以把实验栈（routing 匹配；localize/fix 仍为 Core）设为
  默认并换取其 `[production]` 读数；manifest 记录 `profile=labs`，二者绝不会混淆。各 Candidate 臂也可显式单独运行
  （`--match-arm {semantic,functional,dispatch}`）——每个在缺少凭据/工件时都会 fail-closed。
- [ ] 就绪检查：`gloop doctor --atlas-db $KLOOP_ATLAS_DB` → **READY**（仓库/单元计数符合预期）
- [ ] 密封门禁通过（无需网关）：`.venv/bin/python -m pytest -q`
- [ ] **在真实 ext4 上运行**（直接用 `/home/vinc`、`/var/tmp`、`/dev/shm`）——绝不在 v9fs 挂载上（对数 GB 的
  atlas 跑 sqlite）

**配置输入（离线、零成本）**
- [ ] 在完整历史 oracle 上挖掘亲和先验：`gloop mine-affinity --dataset $FULL_ORACLE --out component_affinity.json`
- [ ] 装载已验证的杠杆：`export KLOOP_AFFINITY=component_affinity.json`（`component` 默认项会自动启用该先验；
  **无工件 ⇒ 会响亮地回退到 `flood` 基线**）
- [ ] 确认 `KLOOP_PRODUCE_API_KEY` 已设置（否则 `--fixer plan` / `--fixer model` 会 **fail-closed**——这是设计
  如此）

**运行（默认：`component` 臂 = Core · `plan` 修复器 = Provisional-Core “Bug Plan Mode”）**
- [ ] `gloop run --dataset <ds> --catalog <cat> --index-db $KLOOP_ATLAS_DB --repos <19-repo-mirror> --work <dir> --changes <path> --out run-N`
  - fail-closed 契约：`--fixer plan` / `--fixer model` 在缺少凭据**或**缺少有效 `--repos` 时报错（`--repos`
    守卫会核实 catalog 快照确实存在——不静默兜底、不编造路径）
  - 批处理会写出 `<out>/manifest.json`——一份溯源附属文件（时间戳、atlas 身份、`match_arm`、`fixer`、亲和哈希、
    produce+embed 模型固定项、`change_sink=mock`、`n_cases`）

**打分（离线；oracle 仅在此处被读取）**
- [ ] `gloop grade-run --runs run-N --dataset <ds> --index-db $KLOOP_ATLAS_DB --out card-N.json`
  - 计分卡现在带有逐样本的 `predicted_repo` / `oracle_repo` / `signals` / `cost_usd` / `fixer`（便于漏检 RCA）
- [ ] 阅读打印出的**晋升资格提示（promotion-eligibility notes）**——对于一次可打分解决率的 `--fixer plan` 运行，
  grade-run 会标出 Provisional-Core 义务（PlanningFixEngine → 确认 Core / 回退）
- [ ] 相对上一版本的回归检查：`gloop grade-run … --compare <prev-card.json>` → 一份逐阶段的
  改善/持平/回退判定 + 一个 `.compare.json` 附属文件

**验收（门槛——见 [`production-guide.md`](production-guide.md) §6）**
- [ ] `component` recall@3 ≫ `flood` recall@3（否则是亲和表 / `Ticket.component` 连接为空——是**数据**问题，不是
  权重问题）
- [ ] functional recall@1/@3 落在 406 目标附近 **≈ 0.50 / 0.90 `[production]`**（诚实的 `--loo`）
- [ ] localize file@5 符合预期；fix **可打分**（需要 `--repos`）
- [ ] 每一个有效性数字都打上 `[production]` 标签

**反馈 → 开发（闭合回路）**
- [ ] 把该次运行追加到 [`results-log.md`](results-log.md)，打 `[production]` 标签
- [ ] 把漏检（label≠owner、近似并列、覆盖缺口）记为给 Dev 的 **Candidate** 工作项
- [ ] `[to build]`：分诊库、人工质量叠加层、时延/阈值监控（production-guide §9–18）

---

## 开发工作流（Dev workflow）

**Dev 是什么：** 隔离的 proxy 空间，能力在此构建并验证，**然后**才可触及 Production。Dev 可以很复杂，但绝不能改变
默认的生产行为——一个新能力在 `[production]` 读数为其换来晋升之前，一直是需显式开启的 **Candidate**。

### 第 1 层 —— 内环（任何改动，每一次）

- [ ] 环境搭建（一次性）：`uv sync --extra dev --extra produce`
- [ ] 只改**适配器 / 组装根（composition root）**——绝不改 `groundloop/core/`，绝不改 `engines/atlas/store.py`
  中的 atlas schema
- [ ] 一个 Candidate **不得**改变默认生产行为（加一个需显式开启的开关；不动 Core 默认项）
- [ ] Type-1 密封测试（无网络 / 无真实 LLM）：`.venv/bin/python -m pytest -q` → 全绿
- [ ] 反泄漏不变式全绿：`tests/test_invariants.py`（闭环保持 oracle-blind）
- [ ] Lint 干净：`.venv/bin/ruff check groundloop tests`
- [ ] 仅在全绿 + ruff 干净时提交；结尾附 `Co-Authored-By:` 行；若在 `main` 上先开分支

### 第 2 层 —— Candidate → Core 晋升（一个新能力）

- [ ] 把它构建为一个新的 adapter/臂，在组装根（`cli/__init__.py`）或既有编排器处接入——`core/` 保持冻结
- [ ] 在 [`capabilities.md`](capabilities.md) 中登记为 **Candidate**（状态 + 其晋升所需条件）
- [ ] Type-2-on-proxy 评测：在 9 仓库的 `atlas-9.db` + synth/挖掘数据集上跑
  `gloop eval` / `fixeval` / `funceval` / `faulteval`（**在 ext4 上**）→ 一个 `[proxy]` 读数（仅机制）
- [ ] **对抗式核验**结果——绝不轻信单一 proxy 数字（规模偏差教训：proxy 0.68 对 production 0.10）
- [ ] 在 [`results-log.md`](results-log.md) 记录该 `[proxy]` 读数，打标签
- [ ] **晋升门槛：** 经生产清单把它上线 → 一个 `[production]` 读数；**仅当**它在真实数据上*持续优于*当前 Core
  **且**通过稳定性 + 成本 + 回归检查时才晋升
- [ ] 晋升时：在组装根翻转默认项，在 `capabilities.md` 里把该能力从 **Candidate → Core**，并记录该次晋升
  `[production]`
- [ ] 若落败：保持 **Candidate**，或移入 **Archived**——但仅在一个*真正定论*的空结果上（度量有效、无混淆；参见 KB
  的重新裁定，了解一个无效的空结果是如何被撤回的）

---

## 分阶段能力全景表（所有状态 · Per-stage feature map）

每个阶段的每个特性，附其状态背后的证据以及晋升所需条件。**状态图例：**
**Core** = 生产默认项，`[production]` 已验证 · **Provisional-Core** = 基于 fail-safe 机制 + 安全性论证而默认开启，
*有效性*受生产门控（最终确认为 Core 或回退）· **Core\*** = Core-when-configured（需其工件/开关）· **Candidate** =
Dev-Labs、需显式开启、仅 `[proxy]` · **Dev-Labs Infra** = 常设的测量装置 · **Fixture** = 密封 Type-1 替身
（绝不作默认）· **Archived** = 已测得空结果 · **Dormant** = 概念有价值，但当前实现效果弱/无信号——阻塞于重新设计，
并非已有定论的空结果 · **`[to build]`** = 尚未实现。（宽表——请右滑；状态/证据可追溯至
[`capabilities.md`](capabilities.md) + [`results-log.md`](results-log.md)。）

| 阶段（port） | 特性 | 状态 | 触达方式 | 证据 | 通往 Core 的阻塞 | 文件 |
|---|---|---|---|---|---|---|
| **1 intake**（IssueSource） | `MockJira`（文件系统工单） | Fixture | 默认（唯一） | `[production]` 读了 GEI 工单；无回写 | 被替换，而非晋升 | `adapters/mock/jira.py` |
| | live JIRA REST source | `[to build]` | — | 无 | 构建 fetch + 评论/流转回写 | — |
| **2 extract**（SignalExtractor） | `AndroidSignalExtractor` | Core | 默认基座 | `[production]`（在 component 之下） | — | `domains/android_ivi/signal_extractor.py` |
| | `ComponentExtractor`（加入 `Ticket.component`） | Core | component 臂（默认） | `[production]` | — | `domains/android_ivi/component_signals.py` |
| | `FaultSignalExtractor` | Candidate | routing 臂 / faulteval | `[proxy]` faultslice 0.86 | 一个 `[production]` 读数 | `domains/android_ivi/fault_signals.py` |
| | `FunctionalTextExtractor` | Candidate | `gloop run --match-arm functional` / funceval | `[proxy]` functional 0.68 | 一个 `[production]` 读数（现已可在 run 触达） | `domains/android_ivi/functional_signals.py` |
| | `DispatchExtractor` | Candidate | `gloop run --match-arm dispatch` / funceval | `[proxy]` dispatch 0.94（crash） | 一个 `[production]` 读数（现已可在 run 触达） | `domains/android_ivi/functional_signals.py` |
| | `RecordingExtractor`（信号捕获旁路） | Core | 批处理 `--out`（默认） | `[production]`-ready——把闭环的 `signals` 记入 run-record（漏检 RCA 数据）；镜像 `RecordingEstate`，core 冻结 | — | `adapters/extractor_recording.py` |
| **3 match**（`rank_repos`） | `AtlasIndex`（flood，FTS5 成员） | Core | `--match-arm flood` / 基座 | `[production]` recall@1 0.10 | — | `adapters/index/atlas.py` |
| | `ComponentPriorIndex`（亲和先验 + RRF） | Core\* | `--match-arm component`（默认）+ `--affinity`/`KLOOP_AFFINITY` | `[production]` 0.10→**0.50** / @3 0.90 | 提供挖掘出的亲和工件（否则诚实 flood） | `adapters/index/component_prior.py` |
| | `FaultRoutingIndex`（faultslice + routing） | Candidate | `--match-arm routing` / faulteval | `[proxy]` routing 0.94，抗诱饵 | 一个 `[production]` 读数 | `adapters/index/fault_routing.py` |
| | `FunctionalTextIndex`（bge-m3 仓库文本） | Candidate | `gloop run --match-arm functional`（需 embedder + `--functional-profile`）/ funceval | `[proxy]` 0.68 对 flood 0.32 | 一个 `[production]` 读数（现已可在 run 触达） | `adapters/index/functional_text.py` |
| | `DispatchIndex`（crash\|functional 路由） | Candidate | `gloop run --match-arm dispatch`（需 embedder + `--functional-profile`）/ funceval | `[proxy]` crash 上 0.94（无回归） | 一个 `[production]` 读数（现已可在 run 触达） | `adapters/index/functional_text.py` |
| | `SemanticAtlasIndex`（bge-m3 向量） | Candidate | `gloop run --match-arm semantic`（需 `KLOOP_EMBED_BASE_URL`）/ `gloop eval --semantic` | `[proxy]` recall 0.02→0.23 | 一个 `[production]` 读数（现已可在 run 触达） | `adapters/index/atlas_semantic.py` |
| | `LLMJudgeIndex`（LLM 重排） | Candidate（仅 eval） | `gloop eval --judge`（2026-07-16 从 run `--match-arm` 移除——召回从未测得） | 无记录 | 经 eval 的一个 `[production]` 读数 | `adapters/index/atlas_judge.py` |
| | `TokenIndex`（M0 桩） | Fixture | `--index <json>` | 无（retrieve 返回 `[]`） | （永不） | `adapters/index/simple.py` |
| **4 materialize**（RepoEstate） | `CheckoutEstate`（真实归属仓库检出） | Core\* | `--repos` | `[production]`-intended（那次生产运行未传） | 设为默认 / 强制 `--repos` | `adapters/estate.py:87` |
| | `RecordingEstate`（结果装饰器） | Core | 批处理 `--out`（默认） | `[production]`（批处理路径） | — | `adapters/estate.py:57` |
| | `MockEstate`（空工作树） | Fixture | 无 `--repos` 时的默认 | `[production]` → fix 无法打分 | （永不） | `adapters/estate.py:13` |
| | `GitFixtureEstate`（@base 快照） | Dev-Labs Infra | fixeval | `[proxy]` 测试台 | —（非闭环角色） | `adapters/estate.py:29` |
| **5 localize**（`retrieve`） | `AtlasIndex.retrieve`（FTS5 关键词） | Core | **run 默认项**（`--localize atlas`，2026-07-16 恢复）；`--localize tokens` 将其包一层作为可触达的显式选项 | `[production]` **7/10 file@5** | — | `adapters/index/atlas.py:30` |
| | `SemanticAtlasIndex.retrieve`（bge-m3 向量） | Candidate（2026-07-16 搁置） | 已从 `--localize` 移除（在 `file@1` 上测得为负）；`SemanticAtlasIndex` 仍保留给 `--match-arm semantic` | `[proxy]` 对 localize 为负 | 一个真实动机 + 一个 `[production]` 读数 | `adapters/index/atlas_semantic.py:50` |
| | `LocalizeDispatchIndex`（逐工单 FTS5⇄bge-m3 路由） | **Archived 2026-07-16** | —（已从 `--localize` 移除；模块 + 测试删除，可从 git 恢复） | `[production]` 测得空结果 `file@1 0/10`（在 `ComponentExtractor` 下惰性失效） | 已归档——增益完全来自 FTS5-tokens 分支，以 `--localize tokens` 保留 | *(git history)* |
| | `SignalQueryIndex`（信号感知 FTS5：查询抽取出的代码 token，回退到 prose） | **Candidate**（2026-07-16 从 Provisional-Core 回退） | `--localize tokens`（可触达的显式选项，**无 embedder**——纯 FTS5；默认是 `atlas`） | `[proxy]` functional 隔离 `file@1` 0.010→**0.166**（16×）；有一类回退（`audio −0.017`）；**无 `[production]` 读数** | 一个 `[production]` GEI `file@1` 读数 → 若胜出则晋升为默认 | `adapters/index/signal_query.py` |
| **6 fix**（FixEngine） | `PlanningFixEngine` —— **“Bug Plan Mode”**（规划→过闸→重规划→弃权→执行；执行出的 diff 会再次按候选范围过闸） | **Provisional-Core（默认；有效性受生产门控）** | `--fixer plan`（**run 默认项**） | `[proxy]` plan recall@1 0.48/@5 0.68，groundedness 0.56，**fab 0.0**（安全性已证；解决率从未可打分） | 一个 `[production]` `resolved_rate` 读数（grade-run 晋升提示）→ 确认 Core / 回退 | `adapters/fix/planning.py` |
| | `ModelPatchEngine`（单发） | Core\* | `--fixer model`（**退出项**） | `[production]` 已运行；fix 无法打分（空工作树） | 可打分的工作树（`--repos`） | `adapters/fix/model_patch.py` |
| | `CannedFixEngine`（密封桩） | Fixture | `--fixer canned` | — | （永不） | `adapters/fix/canned.py` |
| | 开发经验 KB / Skill 注入 | Dormant | `fixeval --skills kb [--skills-inject fix-only]` | `[proxy]` **0 正向信号**：旧空结果被推翻（混淆 Δ−0.10 file@1，度量选错）；`resolved_rate` 复测不确定（0 下限） | 三轴重新设计（注入机制、更丰富的 Knowledge 表示、闭环结果学习）+ 带解决率余量的真实修复切片 | `adapters/skills/mock.py` |
| | Knowledge 注入（蒸馏） | Dormant | `fixeval --knowledge {candidate,validated}` | `[proxy]` 在 `plan_target_recall` 上 0/60（度量选错）——0 正向信号，并非有效空结果 | 三轴重新设计 + 真实修复切片 | `kb/knowledge.py` |
| **7 submit**（ChangeSink） | `MockGerrit.submit`（合成变更） | Fixture | 默认（唯一） | `[production]` 已运行（合成） | 被替换，而非晋升 | `adapters/mock/gerrit.py` |
| | live Gerrit sink | `[to build]` | — | 无 | 推送真实变更 + Change-Id | — |
| **8 bind**（ChangeSink） | `MockGerrit.bind`（change↔ticket） | Fixture | 默认（唯一） | `[production]` 已运行（无真实链路） | 被替换，而非晋升 | `adapters/mock/gerrit.py` |
| | 真实可追溯 JIRA↔commit 链 | `[to build]` | — | 无 | 实时 JIRA + Gerrit 回写 | — |
| **run-record**（批处理 `--out` 输出） | 持久化的 `signals` + 修复 `cost_usd`/`tokens` + `fixer` 种类 | Core | 批处理 `--out`（默认） | `[production]`-ready 反馈数据平面——core `RunRecord` 保持冻结；经旁路 + `GatewayModel` 自计成本捕获 | — | `run/record.py`, `run/batch.py` |
| | `manifest.json` 溯源（时间戳 · atlas 身份 · produce+embed 模型固定项 · 亲和哈希 · `change_sink=mock` · `n_cases`） | Core | 批处理 `--out`（默认） | `[production]`-ready 运行归因 | — | `run/manifest.py` |
| **offline**（grade） | `grade-run` 逐阶段自评 + 更丰富的行（predicted/oracle 仓库 · `signals` · `cost_usd` · `fixer`） | Dev-Labs Infra | `gloop grade-run` | `[production]` 反馈计分卡 | —（测量装置，绝不晋升进闭环） | `run/grade_run.py` |
| | `grade-run --compare <prev-card>`（逐阶段 改善/持平/回退 判定 + `.compare.json`） | Dev-Labs Infra | `gloop grade-run --compare` | `[production]`-ready 回归门 | — | `run/compare.py` |
| | 晋升资格提示（仅报告；从不自动执行） | Dev-Labs Infra | `gloop grade-run`（自动打印） | 浮现 Provisional-Core 义务（可打分解决率的 plan 运行 → 确认 Core / 回退） | — | `run/promotion.py` |

**Model port（横切，支撑 fix + 任何 eval 重排）：** `GatewayModel` = Core（`adapters/model/gateway.py`）；
`CannedModel` = Fixture（`adapters/mock/model.py`）——密封模型，也是那次 re-point 移除掉的静默降级项。

**生产面守卫与基础设施（横切，2026-07-13）—— 全为 Core：** **dev-gate**（`KLOOP_DEV` / 隐藏的 `--dev`）在生产
shell 中拒绝 Fixture 路径（`--index` / `--fixer canned` / `--case`）——Type-1 经一个 autouse fixture 开启它
（`cli/__init__.py`、`tests/conftest.py`）；被加固的 **`--repos` 守卫**在真实修复器运行前核实 catalog 快照确实
存在（`cli/__init__.py`）；plan/patch 原语被迁到 **`groundloop/fix/`**，使 Core 不再 import Dev-Labs 的
`fixeval/` 包（`groundloop/fix/{plan,patch}.py`）。

**Labs 开关 + SplitIndex（横切；2026-07-16 更新）—— Core：** 实验性匹配臂
（`--match-arm {semantic,functional,dispatch}`）**可从 `gloop run` 选用**（需显式开启的 Candidate——缺少
凭据/工件时 fail-closed），因此每个都能换取其 `[production]` 读数。*（2026-07-16 的工作流简化把 run
`--match-arm judge` 移除 → 仅 eval，并把 localize 菜单收敛为 `{atlas, tokens}`——`--localize {semantic,dispatch}`
被搁置/归档。）* **`KLOOP_LABS=1` / `--profile labs`** 是一个按环境切换的开关（`KLOOP_DEV` 的类比），把 run 的
*默认项*翻转为实验栈（routing 匹配；localize + fix 仍保持 Core 的 `atlas`/`plan`）——**显式开关始终覆盖它**，且在
其未设置时**默认项与 Core 完全一致**（`component`/`atlas`/`plan`；由 `tests/run/test_core_defaults_unchanged.py`
断言）。`SplitIndex`（`adapters/index/split.py`）让 `--localize` 可以不同于 `--match-arm`（排名用一个索引，检索用
另一个——用于 `--match-arm semantic` 搭配 `atlas` localize 时）。manifest 记录 `profile`/`localize`，因此 labs 运行
绝不会被误读为一次 Core 生产运行。

---

> 评测台细节：[`evaluation.md`](evaluation.md) · atlas 构建 + ext4 坑：[`build-setup.md`](build-setup.md)。
