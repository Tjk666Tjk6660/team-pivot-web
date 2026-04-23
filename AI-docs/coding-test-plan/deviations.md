# Matter 迁移 · 非核心实现偏离记录

凡后端 P1 / P2 / P4 与前端 P3 的实现过程中，**非核心实现细节**未完全按 `pivot-product.md` / `pivot-interface.md` 落地的，按下格式登记。

核心变更（见 `matter-migration-plan.md` "核心变更评审门"）必须先评审后动手，不在此处记录。

## 格式

```
- <阶段-任务> | 原文档要求: ... | 实际实现: ... | 原因: ...
```

## 记录

- **P1 status×type 矩阵 / `executing + result`**
  - 原文档要求：`pivot-product.md §五` — `executing` 下 `result` "只在事项准备正式结束时才允许创建"
  - 实际实现：executing 状态下随时允许创建 result（创建 result 即作为终态触发信号）
  - 原因：程序无法判定"准不准备结束"；result 本身就是终态信号，再加一道"准备度"校验既无法自动化也不增价值

- **P1 status×type 矩阵 / `reviewed`**
  - 原文档要求：`pivot-product.md §五` — reviewed "原则上不再新增任何文件"
  - 实际实现：reviewed 严格禁止任何新文件创建（writer 一律拒绝）
  - 原因："原则上"作为软约束对代码无指导意义；选择严格禁保证终态干净，如有补写诉求后续再评审放开

