# 邀请流改造：IM 绑定必选 + 飞书 OAuth 落地

**状态**：待开始
**范围**：完全替换现有 email/password 邀请流；新邀请只能走飞书 OAuth；钉钉 / 企业微信仅预留 provider 字段

## 目标

让管理员发出的邀请链接打开后**直接进入飞书授权页**，被邀请人扫码授权后进入现有 application 审核队列；admin 在审核页一眼能看出"这条申请来自我发的邀请"。彻底取消邮箱/密码邀请路径——以后所有受邀加入的成员都必须绑定 IM。

## 现状

- `/admin/invites` 创建邀请：填 email（必填）+ display_name（可选）+ TTL → 一次性链接
- `/invite/<token>` 着陆：填密码 + display_name + pinyin → POST `/api/invite/<token>/accept` → 落 `PivotUser` + `ExternalBinding(provider="invite", external_id=email, password_hash=bcrypt)`
- 飞书 OAuth 是另一条独立路径（`server/auth/feishu_oauth.py` + `server/auth/routes.py`）：任何人扫码 → 进 application 队列 → admin 审核 → 通过后落 `PivotUser` + `ExternalBinding(provider="feishu")`
- `ExternalBinding` 表本身已支持多 provider，新增 "feishu" 通过 invite 路径不破数据模型

## 流程总览

```
admin 创建邀请 (TTL only)
    ↓
admin 把一次性链接发给 alice
    ↓
alice 打开 /invite/<token> → 着陆页（"你被邀请加入 Pivot"）+ 飞书按钮
    ↓
点按钮 → POST /api/invite/<token>/start → 返回飞书 OAuth redirect_url（state 里嵌签名后的 invite_token）
    ↓
飞书授权 → 回调 /auth/feishu/callback?state=<...>&code=<...>
    ↓
后端：验签 state → 取 invite_token → resolve invite (有效 / 未过期 / 未用)
    ↓ Feishu 拉 profile (name / open_id / union_id / avatar_url)
    ↓
分流：
  • 该 open_id 已是活跃 PivotUser → 直接建 session 跳首页，mark invite used
  • 该 open_id 已有 pending application → 用 invite_token 更新 via_invite_id，提示"申请已存在"
  • 否则 → 写新 application 记录（包含 via_invite_id），mark invite used，给 admin 推飞书通知
    ↓
alice 看到"等待管理员审核"页面（沿用现有 PendingApproval）
    ↓
admin 在 /admin/applications 看到申请，列表行带"邀请来源：<admin 名字>"badge → 审核通过
    ↓
后端：用 pypinyin 把飞书 name 转 pinyin（冲突追加 _2 _3...），落 PivotUser + ExternalBinding(provider="feishu")
    ↓
alice 收到飞书通知"已通过"，自助登录
```

## 数据模型

### `invite` 表（精简）

| 字段 | 改动 |
|---|---|
| `email` | **去掉** |
| `display_name` | **去掉** |
| `id` / `token_hash` / `created_by` / `created_at` / `expires_at` / `used_at` / `used_by_user_id` | 保留 |

**迁移策略**：直接清空 `invite` 表（"已使用"和"未使用"的旧记录都丢弃），重建表。当前部署内部 10 人，没有线上活跃邀请会被打断。

### `application` 表

新增字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `via_invite_id` | `TEXT` nullable | 是哪条 invite 引来的（join 到 `invite.id`）；为空表示自助申请 |

## 接口

| API | 改动 |
|---|---|
| `POST /api/admin/invites` | 入参：`{ttl_days?: int = 7}`（删 email / display_name）。返回保持原样 + 增加 `provider: "feishu"` 字段（本期写死） |
| `GET /api/invite/{token}` | 返回：`{expires_at, provider: "feishu"}`（删 email / display_name） |
| `POST /api/invite/{token}/accept` | **删除** |
| `POST /api/invite/{token}/start` *(新)* | 校验 invite 有效后返回 `{redirect_url}`，前端 location.href 过去；state 是 HMAC 签的 `invite_token`，防伪造 |
| `GET /auth/feishu/callback` | 现有逻辑增加分支：state 解出 invite_token → 走 invite 流（建 application 时带 via_invite_id，并 mark invite used）；无 invite_token → 现有自助申请流不变 |
| `GET /api/admin/applications` | 列表项加 `via_invite` 子对象：`{invite_id, invited_by_pinyin, invited_by_display_name}` 或 null |

## UI

| 页面 | 改动 |
|---|---|
| `/admin/invites` 创建 Dialog | 移除 email / display_name 输入；只剩 TTL；按钮文案改"生成飞书邀请链接" |
| `/admin/invites` 列表行 | 不再显示 email；显示 provider（飞书图标 + 文字）+ 创建人 + 状态 + 剩余时间 |
| `/invite/<token>` 着陆页 | 整页重写：标题"你被邀请加入 Pivot" + 一段简介 + "飞书扫码登录"主按钮 + 剩余时间。**删掉密码/拼音/displayName 表单** |
| `/admin/applications` 列表行 | 来源 badge："飞书自助申请" / "来自 \<admin\> 的邀请" |

## 边界 / 错误处理

| 场景 | 行为 |
|---|---|
| invite 过期 | 着陆页显示"邀请已过期，联系管理员重发"。`POST /start` 返回 410 gone |
| invite 已用 | 同上"已使用"。前端用同一错误页面 |
| 飞书授权失败 / 用户拒绝 | 回到着陆页 + 错误提示。**不消耗 invite**（用户可重试） |
| state HMAC 验签失败 | 回调返回 400，记日志（防伪造攻击信号） |
| 该 open_id 已是活跃 PivotUser | 直接建 session 跳首页；mark invite used；不重复建 application |
| 该 open_id 已有 pending application | 把 `via_invite_id` 更新到现有 application；mark invite used；给 alice 提示"已申请，等审核" |
| pypinyin 转出来 pinyin 冲突 | 追加 `_2` `_3`... 直到不冲突 |
| 飞书 name 无法转拼音（emoji / 全是符号） | fallback 到 `user_<open_id 后 8 位>` |
| 用户不在公司飞书组织 | 飞书 OAuth 自身会拒，回调拿不到 union_id；着陆页提示"请用公司飞书账号" |

## 测试

新增 / 修改：

1. `POST /api/admin/invites` 现在不接受 email/display_name，只接受 ttl_days
2. `GET /api/invite/<token>` 返回不再含 email/display_name
3. `POST /api/invite/<token>/accept` 已删除（404）
4. `POST /api/invite/<token>/start`：合法 token 返 redirect_url；过期/已用返 410
5. 飞书 callback：state 含合法 invite_token → application 写入 via_invite_id + mark invite used
6. 飞书 callback：state 含被篡改的 invite_token → 400 验签失败
7. 飞书 callback：open_id 已存在活跃 PivotUser → 不建 application、直接 session
8. auto-pinyin：冲突时追加数字
9. auto-pinyin：fallback 到 `user_<suffix>`
10. `/api/admin/applications` 返回 via_invite 字段

## 不在范围

- 钉钉 / 企业微信支持（仅在 `provider` 字段上预留）
- 现有密码 invite 用户的迁移：他们已在系统里、密码登录还能用；以后再决定要不要强制重绑 IM
- 邀请链接被转发的安全模型：admin 审核步骤是最终把关
- 邀请链接二维码渲染：本期着陆页只放"飞书登录"按钮，飞书自己的扫码 UI 在 OAuth 跳转后才出现
