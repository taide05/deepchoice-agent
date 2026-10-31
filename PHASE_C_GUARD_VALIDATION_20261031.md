# Phase C 结构 guard 验证（2026-10-31）

> 12 例分层开发集；未跑 200。

## 1. 运行

- 代码 HEAD：`a192f02`
- 样本：同一 12 例分层集
- 12/12 complete
- tokens：**784,648**
- health：2 ok / 10 warn / **0 invalid**
- official 正文页：47

## 2. 结果对比

| 指标 | 12 例子修复前 | guard 验证 |
|---|---:|---:|
| usable | 12/12 | 12/12 |
| decision-grade | 6/12 | **9/12** |
| C4 | 0 | 0 |
| C2 partial | 6 | 3 |

改善：

- F200-021、F200-104、F200-117 等 vendor-dominated 默认分支在 guard 后
  不再作为“已支持排序”，C2 通过；
- F200-183 从 recommended 降为 conditional + 待验证假设。

仍非 DG：

- F200-158：Auth0 默认分支仍只有单一个人博客 + 竞品/托管商二手材料，
  官方正文仅目录级；
- F200-172：SQLMesh 默认分支缺用户场景直接适用证据，迁移对比单厂商；
- F200-183：Pydantic 侧证据 4:1 不对称，审计/权限元数据无一手证据，
  且自审 rationale 写“high”、与实际缺口不一致。

这 3 例不是 guard 没生效，而是**证据确实不足**；guard 已诚实降级，
但它们仍不能算 decision-grade。

## 3. 结论

结构 guard 有效：

- 防止“recommended + vendor-only”继续作为推荐；
- 防止 conditional 默认分支被读成已证实排序；
- 12 例 DG 从 6→9，无 C4。

Phase C 仍未 12/12 闭环，但剩余 3 例属于可解释的证据缺口，
不是“修复逻辑失败”。是否把 Phase C 定义为“结构性问题已闭环、证据缺口保留”
由用户决定。

## 4. 当前状态

- Phase B：闭环；
- Phase C：结构性改进已生效；是否关闭需决定；
- 最终 200：保持冻结；
- 未跑 200；
- 无付费任务在跑。

## 5. 下一步选项

A. 关闭 Phase C：接受 9/12 DG、3 个诚实 C2 partial，进入最终阶段回顾；
B. 继续零付费微调：
   - guard caveat 的 owner-dominated/secondary-dominant 措辞分开（当前模板略笼统）；
   - F200-183 类“降级后 confidence rationale 仍写 high”的一致性检查；
   再做一次 12 例验证（需付费）才值；
C. 不继续 paid 验证，先做最终材料整理。
