# Pivot 产品设计文档

## 一、产品定义

Pivot 是一个围绕 `matter` 运转的系统。

`matter` 是企业工作中的顶层事项。它不是静态对象，而是一条沿时间线持续演进的工作过程。Pivot 的核心，不是围绕模块组织信息，而是围绕 `matter` 的演进组织信息。

Markdown 文档不是系统的顶层对象，而是 `matter` 在时间线上的工作足迹。系统真正要表达的，是这件事如何被提出、如何被分析、如何被推进、如何被核验、如何被沉淀。

因此，Pivot 的一句话定义可以表述为：

**Pivot 是一个以工作数据流为基础、以 AI 调度为核心的事项操作系统。**

## 二、核心设计

### 1. `matter` 是唯一顶层视角

企业工作不是一组彼此孤立的功能模块，而是大量持续推进的事项。每个事项从被提出开始，都会沿着自己的时间线不断演进。

Pivot 的顶层对象就是 `matter`。后续的讨论、执行、验收、复盘，都是同一个 `matter` 在不同时间点上的数据流表现。

### 2. 工作数据流是系统本体

事项的推进过程不能只存在于人的记忆、口头沟通和即时聊天里，而应持续沉淀为可追溯、可分析、可计算的数据流。

在 Pivot 里，Markdown 文档负责保留原始工作足迹。系统不试图把所有语义都压进文档本体，而是在文档之上构建对事项的持续理解。

### 3. AI 是事项调度者

AI 在 Pivot 中的职责，不是局部回答问题，而是基于事项的数据流理解当前状态，判断下一步应当发生什么，并推动事项继续向前演进。

程序和 AI 的分工是：

- 程序负责定义结构、维护约束、收敛问题空间
- AI 负责理解上下文、生成候选解释、做高阶判断和推进建议

## 三、`matter` 状态机

`matter` 只有一套状态机，用来描述“这件事现在推进到哪里了”。

当前固定为六个主状态：

1. `planning`
2. `executing`
3. `paused`
4. `finished`
5. `cancelled`
6. `reviewed`

### 1. `planning`

表示这件事仍处于计划中，当前重点是澄清目标、范围、约束、方案和准备条件。

### 2. `executing`

表示这件事已经开始执行。后续即使发生返工、补充计划、调整方案和新增行动，也仍然属于执行过程的一部分。

### 3. `paused`

表示这件事当前暂时停止推进。它不是完成，也不是取消，而是出于阻塞、等待窗口、资源不足或优先级调整等原因，被临时挂起。后续仍然可以恢复到 `planning` 或 `executing`。

### 4. `finished`

表示这件事已经正式完成。执行闭环到此结束，不再继续新增行动。

### 5. `cancelled`

表示这件事已经被正式取消。事项到此终止，不再继续推进执行。

### 6. `reviewed`

表示这件事已经在完成或取消之后完成复盘，整个生命周期正式收口。

## 四、MD 文档类型系统

MD 文档也只有一套类型系统，用来描述“这份文档承担什么作用”。

当前固定为五类：

1. `think`
2. `act`
3. `verify`
4. `result`
5. `insight`

### 1. `think`

用于承载分析、澄清、方案推演和取舍讨论。

### 2. `act`

用于承载行动方案、执行记录、任务拆解和过程更新。

### 3. `verify`

用于承载对一个或多个 `act` 的验证判断、评价和证据。

### 4. `result`

用于承载一个 `matter` 最终的正式结果。它只负责声明这件事最终是完成还是取消，以及这一最终结论的简短说明。

### 5. `insight`

用于承载复盘、经验、共识、规律和可复用的认知。

## 五、状态与文档类型的关系

`matter` 状态和 MD 文档类型是两套正交定义，不互相替代。

- `matter` 状态回答：这件事现在推进到哪里了
- MD 类型回答：这份内容承担什么作用

因此：

- `executing` 状态下仍然可以持续出现 `think`
- `planning` 状态下也可以出现 `verify`
- `paused` 状态下通常不再新增执行性质文件，而是等待恢复
- 状态不会因为新增某一类文档而自动改变
- 文档类型也不应该被阶段名替代

这套拆分的价值在于：

- 状态机保持稳定，只表达事项推进位置
- 文档系统保持开放，只表达信息作用
- 系统语义更清楚，不再混淆“当前状态”和“文档用途”

当前第一版里，不同状态允许出现的文件类型建议如下：

- `planning`
  - 允许：`think / act / verify`
  - 不允许：`result / insight`
- `executing`
  - 允许：`think / act / verify / result`
  - 其中 `result` 只在事项准备正式结束时才允许创建
- `paused`
  - 允许：`think`
  - 不允许：`act / verify / result / insight`
- `finished`
  - 允许：`insight`
  - 不允许：`think / act / verify / result`
- `cancelled`
  - 允许：`insight`
  - 不允许：`think / act / verify / result`
- `reviewed`
  - 原则上不再新增任何文件

这套边界的目标不是做一套过于复杂的流程控制，而是只限制那些明显不合理的情况，让终态尽量保持干净。

## 六、`index` 的定位

`index` 不是原始事实层，而是事项解释层。

原始 Markdown 文档仍然是第一手事实材料；`index` 负责承载系统围绕这些材料形成的结构化理解。它同时服务两类主体：

- 程序：获得稳定的结构抓手
- AI：获得高密度的上下文入口

`index` 中适合记录的是围绕事项数据流形成的系统解释信息，例如：

- timeline
- 当前状态
- 阶段跃迁点
- 关键文档引用
- 文档摘要
- 文档重要性
- 对关键节点的解释说明

这里有两个边界必须明确：

- `index` 记录解释，不记录原始事实本身
- `index` 的结构控制权属于程序，不属于 AI

更合理的分工是：

- 程序定义 `index` schema
- AI 提供摘要、关系判断和状态变化候选输入
- 程序负责校验、约束、写入和维护

## 七、`matter` 的物理落地

`matter` 在概念上仍然是顶层事项，但在当前阶段，不额外设计独立的 `matter` 实体对象。

当前更合理的落地方式是：

- 原始工作事实保存在 Git 中的 Markdown 文档里
- `matter` 的当前主记录由 `index` 承载
- 程序围绕 `index` 和原始文档维护事项状态与解释

这样做的目的，是守住单一事实源，避免 Git 和 SQL 双主存并存带来的同步、冲突、回滚和审计复杂性。

因此，当前阶段的基本判断是：

- `matter` 是顶层事项概念
- `index` 是 `matter` 的当前主记录和事项解释层
- 不额外引入独立 SQL `matter` 主表

## 八、`index` 的最小结构

当前 `index` 采用 **timeline-first** 的结构，不再把文件清单、状态迁移和事件流拆成并列的多套结构。

核心原则是：

- `timeline` 是 `matter` 的唯一演进主结构
- 时间线上每一项都对应一篇新出现的文件
- 状态变化、引用关系、评论、圈人、验收结果，都附着在文件项上表达
- 除了少量头部快照字段，程序不再维护第二套并列事实结构

### 1. 顶层头部

顶层只保留程序高频读取的当前快照：

```yaml
version: 1

matter:
  id: auth-redesign
  title: Authentication Redesign
  current_status: executing
  created_at: 2026-04-23T10:00:00+08:00
  updated_at: 2026-04-23T15:30:00+08:00
```

这里的头部字段只服务快速读取，不承担完整事实表达。完整演进信息仍然在 `timeline` 中。

### 2. timeline 基本单元

每一条 timeline item 都是一篇文件。当前最小结构如下：

```yaml
- file: discussions/auth-redesign/006_dengke_verify_f6g7.md
  created_at: 2026-04-23T15:30:00+08:00
  creator: dengke
  owner: dengke
  type: verify
  summary: 汇总当前行动验证结果，并形成后续正式结果判断的依据

  quote: discussions/auth-redesign/005_liuyu_act_d4e5.md
  verifications:
    - target: discussions/auth-redesign/003_dengke_act_a1b2.md
      judgement: passed
      comment: 主链路完成，质量一般，但结果可接受
    - target: discussions/auth-redesign/004_liuyu_act_b2c3.md
      judgement: failed
      comment: 关键边界遗漏，当前结果不可接受

  comments:
    - created_at: 2026-04-23T15:31:00+08:00
      body: 主链路通过，边界情况已记录
      mentions:
        - liuyu

  status_change:
    from: executing
    to: finished
```

### 3. 字段含义

- `file`
  - 文件路径，作为该文件项的唯一身份字段
- `created_at`
  - 文件创建时间
- `creator`
  - 文件创建者，即谁把这篇文件正式写入系统
- `owner`
  - 文件责任人，即后续应由谁对这篇文件的推进和结果负责
- `type`
  - 文档类型，只允许 `think / act / verify / result / insight`
- `summary`
  - 该文件的最小解释信息
- `quote`
  - 单值，中文语义统一为“引用”，表示这篇文件主要承接或回应的那篇文件
- `refer`
  - 数组，中文语义统一为“参考”，表示其他补充参考文件
- `verifications`
  - 只用于 `verify` 文件，表示这篇验证覆盖的行动及其判断结果
- `comments`
  - 附着在该文件上的评论流；每条评论都有 `created_at / body / mentions`
- `status_change`
  - 只有当这篇文件触发事项状态迁移时才出现

### 4. 当前明确不进入 schema 的字段

当前以下概念不进入第一版 schema：

- 独立 `goal`
- 独立 `task` 对象
- 独立 `transitions` 列表
- 独立 `files` 列表
- `anchor` / `current_anchor`
- `importance`
- `title`
- 拆分的 `id / filename / path`

原因很简单：这些字段要么没有独立信息增量，要么会过早把模型推向更重的对象结构。

## 九、executing、paused、finished 与 cancelled 的最小规则

### 1. executing

进入 `executing` 后，事项不再依赖某一篇唯一依据文件。执行过程中允许持续出现新的 `think` 文件，对当前理解进行修正和优化。

因此，当前模型不引入“当前执行依据文件”这一概念，只记录：

- 某篇文件是否触发了 `planning -> executing`
- executing 阶段下陆续增加了哪些 `think / act / verify / result / insight`

executing 第一版的最小执行单元，先由 `act` 文件承载，而不是额外设计独立 task 实体。

`act` 的作用不是维护复杂状态，而是明确一段执行责任。它回答的是：

- 要推进什么事情
- 当前交给谁负责
- 它主要承接哪篇已有文件

当前第一版里，`act` 的最小结构建议是：

```yaml
type: act
creator: dengke
owner: liuyu
quote: discussions/auth-redesign/002_liuyu_think_c3d4.md
refer: []
summary: 按修正后的登录链路推进实现，并补齐回跳与 cookie 处理
comments: []
```

这里：

- `creator`
  - 谁创建了这篇 `act`
- `owner`
  - 谁负责推进这篇 `act`
- `quote`
  - 这篇 `act` 主要承接哪篇已有文件
- `refer`
  - 其他补充引用
- `summary`
  - 这篇 `act` 的最小责任描述

`act` 的正文不需要承载复杂状态，而应保持为一份清晰的责任说明。当前建议的最小写法是：

```md
# Summary

按修正后的登录链路推进实现，并补齐回跳与 cookie 处理。

# What To Do

- 调整登录回跳逻辑
- 补齐 cookie 持久化处理
- 确认飞书端内和浏览器打开两种场景

# Notes

- 如果执行过程中发现方案需要修改，可以继续新增 think
- 如果执行过程中形成新的独立工作，可以继续新增新的 act
```

这里也有几个边界：

- `act` 不引入单独的 task status
- `act` 不维护 parent / child act 树
- `act` 不记录 progress 百分比
- 如果执行结果需要判断，应由后续 `verify` 文件来完成，而不是把判断直接写回 `act`

### 1.2 paused

`paused` 是事项的暂挂状态。它既可以出现在 `planning` 阶段，也可以出现在 `executing` 阶段。

当前对 `paused` 的基本理解是：

- 事项当前不继续主动推进
- 它不是完成，也不是取消
- AI 可以降低关注频率，而不是持续高频跟进
- 后续可以恢复回原来的持续状态

因此第一版里，允许的暂停与恢复方式包括：

- `planning -> paused -> planning`
- `executing -> paused -> executing`

至于暂停的原因，可以留在具体文件内容里表达，而不额外在状态机里拆出新的原因型状态。

把事项正式标记为 `paused` 的文件，当前应当使用 `think`。

原因是：

- `paused` 不是执行结果
- `paused` 不是最终结论
- 它表达的是对当前局面的判断：为什么现在不能继续推进，以及未来在什么条件下可以恢复

因此第一版里：

- `planning -> paused`
  - 由一篇 `think` 触发
- `executing -> paused`
  - 也由一篇 `think` 触发

这篇 `think` 至少应当回答三件事：

- 为什么要暂停
- 当前卡在哪里
- 什么条件下可以恢复

同样地，把事项从 `paused` 恢复回持续状态，当前也应当使用 `think`。

原因是：

- 恢复不是一个执行结果
- 恢复本质上也是对当前局面的重新判断
- 它需要说明为什么之前的暂停条件已经变化，以及为什么现在可以继续推进

因此第一版里：

- `paused -> planning`
  - 由一篇 `think` 触发
- `paused -> executing`
  - 也由一篇 `think` 触发

这篇恢复用的 `think` 至少应当回答三件事：

- 为什么现在可以恢复
- 之前导致暂停的条件发生了什么变化
- 恢复后应该回到 `planning` 还是 `executing`

### 1.1 文件创建交互

新的 `think / act / verify / result` 不应当凭空创建，而应当默认从现有文件卡片上继续长出来。

更自然的交互是：

- 在每个现有文件卡片上提供三个入口
  - 基于此新增 `think`
  - 基于此新增 `act`
  - 基于此新增 `verify`
- 用户从某个文件卡片发起创建时，系统自动把当前文件写入新文件的 `quote`

这样做的原因是：

- 除了事项的第一篇文件，后续大部分文件本质上都应当有明确的“引用”对象
- 用户的操作心智是“基于这篇文件继续推进”，而不是抽象地“新建一条记录”
- 整个时间线会自然长成文件流，而不是长成一套独立的任务面板

唯一的例外是事项的第一篇文件。

- 第一篇文件允许直接创建
- 它通常是 `think`
- 但在某些情况下也可以直接是 `act`
- 这时它没有 `quote`

对 `verify` 和 `result` 来说，入口也仍然应当挂在某个文件卡片上。

- 用户从某个文件卡片点击“新增 verify”时，默认是基于这篇文件发起一次新的验证
- 进入表单后，允许用户继续补充这次验证所覆盖的其他 `act`
- 因此，`verify` 的交互起点仍然是单一文件，但它在内容上可以通过 `verifications` 覆盖多个行动
- 用户从某个文件卡片点击“新增 result”时，默认是基于这篇文件发起一次最终结果确认

### 2. creator 与 owner

当前所有文件都统一拥有两个责任字段：

- `creator`
- `owner`

这两个字段的分工是：

- `creator` 表示谁创建了这篇文件
- `owner` 表示当前由谁对这篇文件的推进和结果负责

这条规则适用于所有文件类型，而不是只适用于 `act`。

默认情况下：

- `think`：`creator = owner`
- `verify`：通常 `creator = owner`
- `insight`：通常 `creator = owner`

但在 `act` 文件上，`creator` 和 `owner` 可以不同。这表示一篇执行文件可以由一个人创建，但交由另一个人负责推进。

例如：

- 小组长创建某个 `act`
- 组员作为该 `act` 的 owner 负责执行

`verify` 文件当前也沿用这套规则，但它的语义与 `act` 不同。`act.owner` 表示执行责任人；`verify.owner` 表示判断责任人，也就是谁对这篇 `verify` 中给出的结论负责。

因此，`verify.owner` 可以是：

- 被验证 `act` 的执行者本人
- 对应的小组长或基层管理者
- 与该事项直接相关、并愿意对本次判断负责的协作者

### 3. executing 的追踪重点

executing 阶段当前不追踪 act 的派生树，也不维护 task / subtask 状态树。

当前更重要的是追踪：

- 每个 owner 当前负责哪些 `act`
- 这些 `act` 后续是否被某篇 `verify` 文件统一覆盖和总结
- 某个 owner 是否已经对自己负责的一批 `act` 给出阶段性确认

这里的关键不是维护一棵精确的 act 派生树，而是维护责任闭环。

也就是说：

- 一个 `act` 在执行过程中可以失败、重做、扩展、继续派生新的 `act`
- 系统当前不要求显式追踪这些 `act` 之间的完整继承关系
- 只要这些 `act` 仍然归某个 owner 负责，它们就都可以被后续某篇 `verify` 文件统一解释和收口

这里的 `verify` 不一定由这些 `act` 的执行 owner 自己创建。更常见的情况是：

- `act.owner` 负责做事
- `verify.owner` 负责判断这批 `act` 当前结果如何

因此，executing 当前追踪的是“谁在执行”和“谁来判断”，而不是“act 之间如何形成一棵稳定的派生树”。

因此，executing 的最小追踪单位不是“多级子 act 关系”，而是“owner 责任闭环”。

### 4. verify 与 result 的分工

`verify` 文件可以在时间线上多次出现，代表不同粒度的验证。

一篇 `verify` 文件可以覆盖一组相关 `act`，并对其中每一个 `act` 给出正式判断。当前第一版里，每篇 `verify` 都应当带有一组 `verifications`，其中每个 `act` 的判断结果至少包括：

- `passed`
- `failed`
- `cancelled`

这三种结果的含义分别是：

- `passed`
  - 这篇 `act` 的交付结果成立，可以接受
- `failed`
  - 这篇 `act` 当前结果不成立，不可接受
- `cancelled`
  - 这篇 `act` 明确不再继续推进，且该决定已经被正式记录

其中 `cancelled` 是正式结果，不是隐式消失。它用来记录“为什么这篇 `act` 到此为止”，例如：

- 做到一半确认已经没有继续必要
- 与负责人讨论后决定停止
- 原 act 已被新的方案或新的 act 替代

为了留下明确证据，`verify` 对每个 `act` 的判断除了结果本身，还应附带一条简短评价，说明通过、失败或取消的原因。

因此，`verify` 的正文不需要再重复列出一段独立的 “Covered Acts”。因为一篇 `verify` 已经通过 `verifications` 显式列出了它正在判断的那一组 `act`。

更合理的写法是：在正文中直接展开一个 `Verifications` 段，逐条对应 `verifications` 中的每一个 `act`，并给出判断结果与简短评价。

同样地，在 `index` 里，`verify` 文件也不再使用 `results` 这样的字段名，而应统一使用 `verifications`。因为这里表达的是“对一组行动的验证记录”，不是事项最终结果。

也就是说，`verify` 在 `index` 里的核心结构应当是：

```yaml
verifications:
  - target: discussions/auth-redesign/003_dengke_act_a1b2.md
    judgement: passed
    comment: 主链路完成，质量一般，但结果可接受
  - target: discussions/auth-redesign/004_liuyu_act_b2c3.md
    judgement: failed
    comment: 关键边界遗漏，当前结果不可接受
```

例如：

```md
# Verifications

- 003_dengke_act_a1b2.md
  - judgement: passed
  - comment: 主链路已完成，质量一般，但结果可接受

- 004_liuyu_act_b2c3.md
  - judgement: failed
  - comment: 结果未达要求，关键边界遗漏

- 005_wangwu_act_c3d4.md
  - judgement: cancelled
  - comment: 与负责人讨论后确认该项已无继续必要
```

这里有几个约束：

- `Verifications` 中的条目应当与 `verifications` 字段中的 `target` 一一对应
- 不应评价没有出现在 `verifications` 里的 `act`
- `summary` 应当是这些逐条判断的压缩版，快速概括本篇 `verify` 的整体结论
- 如果后续确实产生了新的工作，不在 `verify` 中通过 “Next” 文本维护，而是直接新增新的 `act` 文件，再去引用当前的 `act` 或 `verify`

`verify` 负责验证和评价行动，但不直接承担一个 `matter` 的最终状态确认。

一个 `matter` 的最终正式结果，交给单独的 `result` 文件承担。

原因是：

- 一个 `matter` 可能有很多篇 `verify`
- 这些 `verify` 分别对应不同 owner、不同 act、不同阶段
- 但一个 `matter` 最终只能有一个正式结果

因此，`result` 的语义是：

- 它是一个 `matter` 的最终结果文件
- 对同一个 `matter`，当前只允许存在一个有效 `result`
- 它负责把事项正式标记为 `finished` 或 `cancelled`
- 它不再逐条展开验证行动，而是建立在已有 `verify` 基础上的最终确认
- 它的 `quote` 和 `refer` 都可以为空，因为它的对象直接就是 `matter` 本身

这里还要明确一个边界：

- `result` 不要求必须建立在某篇 `verify` 之上
- 一个 `matter` 可以先有很多 `verify`，再有 `result`
- 也可以没有任何 `verify`，直接产生 `result`

也就是说，系统不把“先有足够验证，再允许结束事项”做成硬前置条件。

更合理的理解是：

- `verify` 是更严谨的过程记录
- `result` 是最终结果落点
- 是否足够严谨，可以由后续 AI 巡视或团队复盘指出，但不由系统在第一版强制阻止

对应地：

- `verify` 解决“每个 act 当前做得怎么样”
- `result` 解决“这个 matter 最终是什么结果”

当前第一版里，`result` 的最小结构建议是：

```yaml
type: result
creator: dengke
owner: dengke
summary: 事项正式完成，整体结果可接受
outcome: finished
status_change:
  from: executing
  to: finished
comments: []
```

如果事项最终被取消，则改为：

```yaml
outcome: cancelled
status_change:
  from: executing
  to: cancelled
```

`result` 的正文不需要再强制拆出很多结构字段。第一版里，正文保留简洁说明即可：

```md
这个事项已经完成。整体结果可接受，核心目标已经实现，但在易用性和细节打磨上仍有明显不足。
```

这里：

- `outcome`
  - 只表示事项最终客观结果
  - 当前只允许 `finished` 或 `cancelled`
- `summary`
  - 表示对该最终结果的简短说明
  - 它应当比普通文件的摘要更直接地概括最终结论

因此，`result` 文件里有三层不同的内容：

- `outcome`
  - 负责结构化表达事项最终结果
- `summary`
  - 负责压缩表达最终结果的简短说明

- frontmatter 里的 `comments`
  - 仍然只是轻量评论流和圈人
- 正文里的说明文字
  - 可以存在，但不再要求额外固定成 `Details` 字段

只有 `result` 文件才允许触发：

```yaml
status_change:
  from: executing
  to: finished
```

或：

```yaml
status_change:
  from: executing
  to: cancelled
```

一旦进入 `finished` 或 `cancelled`：

- 不再新增 `act`
- 不再新增执行性质的 `think`
- matter 的执行生命周期到此结束
- 后续只剩 `reviewed` 这一后置状态

## 十、当前产品判断

从产品现状看，当前 Pivot 已经具备围绕事项展开讨论、持续沉淀 Markdown 文档、借助 AI 理解上下文、通过 Git 保存工作数据流的基础能力。

因此，当前最重要的工作，不是重新发明一套新系统，而是把现有能力正式解释到新的模型里。

当前可以明确的判断是：

- 现有 discussion 体系可以被解释为 `matter` 在 `planning` 状态下的基础设施
- `concluded` 不应再被理解为“讨论结束”，而应理解为该事项在当前计划阶段已经完成一次有效收口
- 后续设计重点应放在如何围绕 `matter` 的状态迁移继续组织执行、验证、最终结果和复盘，而不是继续扩张讨论系统本身
- `index` 的第一版应优先支撑 `planning/executing -> paused -> 恢复` 与 `planning -> executing -> finished/cancelled -> reviewed` 这两条最小闭环，而不是一开始覆盖全部未来对象

## 十一、当前设计边界

当前这版产品设计，有几个边界已经明确。

### 1. 不再使用 GTD 作为产品主叙事

GTD 可以看作早期启发，但不再作为当前产品定义的核心表达。当前产品文档只围绕 `matter`、状态迁移和工作数据流展开。

### 2. 不再引入独立 `goal` 文档

当前不再把 `goal` 作为独立对象写入产品模型。

事项从 `planning` 进入 `executing` 时，只记录由哪篇文件触发了状态变化，不再额外设计“当前依据文件”这类对象。

### 3. 不构建无限膨胀的细粒度文档角色体系

当前只保留 `think / act / verify / result / insight` 这套最小文档类型系统，不继续扩张新的文档角色名词。

### 4. 不在当前阶段引入 Git 与 SQL 双主存

当前优先守住 `index + Markdown` 这套单一事实源模型，不主动引入独立 `matter` SQL 主记录。

### 5. 不把时间线拆成多套并列结构

当前不再同时维护并列的 `files / transitions / timeline` 三层结构，而是以 timeline 上的文件流作为唯一演进主结构。

### 6. 不引入 `anchor`

当前不记录“当前阶段依据文件”这类 `anchor` 概念。因为 executing 过程中允许持续修正和新增 `think` 文件，不存在稳定、唯一、长期有效的依据文件。

## 十二、下一步设计重点

接下来真正需要继续收敛的，不是愿景，而是实现层面的最小模型。

当前优先级最高的设计问题包括：

1. `quote / refer / verifications / comments` 在前后端如何编辑和展示
2. discussion 现有文件结构如何映射到 timeline-first 的 `index`
3. `creator / owner` 在前后端如何填写、展示和变更
4. `executing` 状态下最小 `act` 文件的写入入口如何设计
5. `verify` 与 `result` 在前后端如何分工与展示
6. 哪些字段由程序直接写入，哪些字段由 AI 提供候选摘要

## 十三、Matter 详情页方向

现有右侧详情页仍然主要在展示 thread/discussion 语义。后续进入 `matter` 模型以后，右侧详情页应逐步改造成一个时间线视图，而不是继续停留在“帖子列表”视图。

第一版方向如下：

- 点开一个 `matter` 后，右侧详情页顶部显示一条时间轴
- 时间轴上按时间顺序排列该 `matter` 的所有文件
- 用户可以通过点击或拖动时间轴，快速跳转到对应时间点的文件
- 时间轴下方仍然是完整文件流，按时间顺序从上往下展示
- 每个文件卡片默认只显示部分内容，点击后再展开更多，沿用当前 discussion 详情页的展开体验

在文件卡片层面，第一版交互保持为：

- 基于当前文件新增 `think`
- 基于当前文件新增 `act`
- 基于当前文件新增 `verify`

这三个动作都意味着：

- 新文件从某个已有文件继续长出来
- 系统自动把当前文件写入新文件的 `quote`

`result` 是一个特例。它虽然也可以从右侧详情页发起，但不要求必须建立在某篇具体文件之上，因为它的对象直接就是 `matter` 本身。

因此，`result` 的入口不应当和普通文件完全混在一起，而应当放在右侧详情页顶部、靠近时间轴的位置，作为一个页面级动作存在。

第一版里，这个动作的基本语义是：

- 文案可以是“生成 Result”
- 点击后进入 `result` 创建流程
- 系统需要先给出明确提示：创建 `result` 代表当前 `matter` 将被正式结束为 `finished` 或 `cancelled`
- 这是事项生命周期的正式收口动作，不是普通文件追加

## 十四、最终判断

Pivot 真正要做的，不是把企业工作的每一个局部动作都工具化，而是把企业工作还原为一条条 `matter` 时间线，并让 AI 在这些时间线上持续理解、判断和推动事项向前演进。

如果这件事成立，Pivot 就不会只是一个讨论系统、任务系统或知识系统，而会成为一个真正围绕事项运转的系统。
