# 设计 — Logto Management Skill 扩充

> 状态：已批准并在 v0.2.0 实现
> 日期：2026-07-25

## 1. 为什么要扩充：一次真实使用留下的证据

这份设计不是凭空罗列 API，而是来自一次完整的真实任务——用本 skill 从零把一个账户中心项目配起来并上线。过程中**大部分操作都绕开了 CLI**，靠直接写内联 Python 调 `LogtoClient._request` 完成：

| 实际做的事 | 现有 CLI 是否覆盖 |
|---|---|
| 读 sign-in experience（登录方式、MFA policy、passkey、branding） | ❌ |
| 读/写 Account Center（enabled、逐字段权限、WebAuthn origins） | ❌ |
| 列应用、看 redirect URI、创建 SPA application | ❌ |
| 读 connector 与 9 个邮件模板、批量改模板内容 | ❌ |
| 查 `swagger.json` 找出正确端点路径 | ❌ |
| 列 API resource / scope、列 role | 部分（只有 role） |
| 找用户、建用户、发 role | ✅ |

现有 CLI 只覆盖 `user` 与 `role` 两组。也就是说：**凡是"配置租户"这类工作，skill 目前一律帮不上忙**，而这恰恰是最需要可复现、可审计、可回滚的部分。

### 1.1 过程中真实踩到的坑（决定了设计重点）

这些不是假想的边界情况，是这一轮实测踩出来的：

1. **端点靠猜必错。** MFA 相关路径按直觉写成 `POST /api/my-account/mfa-verifications/totp/secret`，实际 404；查租户自己的 `GET /api/swagger.json` 才发现正确的是 `totp-secret/generate`（POST）与 `mfa-verifications/totp`（PUT）。**端点发现能力应当内置**，而不是每次让使用者自己去翻。
2. **邮件模板的写操作极其危险。** 模板嵌在 connector 的 `config.templates` 数组里，改动必须"读出整个 config → 深拷贝 → 改其中若干项 → PATCH 整个 config"。一旦 PATCH 了部分 config，9 个模板可能被整体覆盖或丢失。手工做这件事没有任何护栏。
3. **`_request` 返回原始 `requests.Response`**，与库里其它返回 `dict` 的方法不一致。第一次调用直接 `AttributeError: 'Response' object has no attribute 'get'`。
4. **参数名是 `json_body` 而不是 `json`**，按惯例写 `json=` 得到 `TypeError`。
5. **自定义域必须显式传 `tenant_id`**，否则在取 token 时才报错。错误信息虽有提示，但发生时机晚、且没告诉使用者去哪里找这个值。
6. **没有 snapshot 能力。** 这一轮的租户盘点报告是人工整理的——下次要复查"我们的 Logto 现在到底怎么配的"，得从头再来一遍。
7. **管理员侧解绑 MFA 是刚需但没有入口。** 设计 e2e 时的真实风险场景：测试账号残留一个 TOTP 绑定后，登录会被要求动态码，而 secret 已丢失——此时只能靠管理员解绑，而 CLI 没有这个能力。

## 2. 设计原则

**读优先、写有护栏。** 每个写命令都有配对的读命令；对整体替换语义的配置（connector、sign-in-exp）强制"读—改—写"并自动备份。

**发现能力内置。** Logto 的端点不可猜。把 `swagger.json` 当一等公民：支持按关键词搜索端点、查看请求/响应 schema。这条能力的价值高于再多包十个具体端点。

**长尾交给通用通道。** 不追求把所有端点都包成子命令。高频、高风险的做成专用命令；剩下的用一个安全的 `api call` 覆盖。

**输出稳定可管道化。** 继续保持"JSON 到 stdout、错误 JSON 到 stderr"的既有契约，方便 agent 消费。

## 3. 命令设计

### P0 — 这一轮真实需要、且手工做危险

#### 3.1 `app` — 应用管理

```bash
logto-mgmt app list [--type SPA|Traditional|MachineToMachine|Native]
logto-mgmt app get <app-id-or-name>
logto-mgmt app create <name> --type SPA \
    --redirect-uri https://example.com/callback \
    --redirect-uri http://localhost:5173/callback \
    --post-logout-uri https://example.com/ \
    [--description TEXT]
logto-mgmt app update-uris <app-id> [--add-redirect URI] [--remove-redirect URI] ...
logto-mgmt app delete <app-id>          # dry-run 默认
```

`app get` 要把 `oidcClientMetadata`、`appLevelAccessControlEnabled`、`isThirdParty` 一并平铺展示——排查登录问题时这几项最常看。

#### 3.2 `email-template` — 邮件模板（最高风险项）

```bash
logto-mgmt email-template list                    # usageType / subject / contentType 概览
logto-mgmt email-template get <usageType>         # 输出完整 HTML
logto-mgmt email-template set <usageType> --subject TEXT --content-file path.html
logto-mgmt email-template replace-text --find "旧文案" --replace "新文案" [--usage-type X]...
logto-mgmt email-template append-footer --html-file footer.html --usage-type SignIn --usage-type BindMfa
logto-mgmt email-template backup [--out dir]      # 写操作前自动执行，也可手动
logto-mgmt email-template restore <backup.json>
```

设计要点：所有写操作内部统一走"读整个 connector config → 深拷贝 → 局部修改 → PATCH 全量 → 回读校验"，并在改动前自动落一份备份。`replace-text` 这种批量文案修正是真实需求（这一轮要把 9 个模板里的品牌名统一）。

#### 3.3 `sign-in-exp` — 登录体验与 MFA 策略

```bash
logto-mgmt sign-in-exp get [--section signIn|mfa|branding|password|all]
logto-mgmt sign-in-exp set-mfa --policy NoPrompt|UserControlled|Mandatory \
    [--factor Totp --factor WebAuthn]
logto-mgmt sign-in-exp set-passkey-signin --enable|--disable
logto-mgmt sign-in-exp set-branding --logo-url URL --favicon-url URL
```

`get` 默认输出精简摘要（登录 identifier、是否 password-primary、MFA policy 与 factors、passkey 开关），而不是把整个巨大对象糊到终端——这一轮为了看清状态写了不少字段筛选代码。

#### 3.4 `account-center` — 账户自服务配置

```bash
logto-mgmt account-center get
logto-mgmt account-center enable | disable
logto-mgmt account-center set-fields --field password=Edit --field email=ReadOnly --field mfa=Edit
logto-mgmt account-center set-webauthn-origins --origin https://account.example.com
```

字段取值只有 `Off` / `ReadOnly` / `Edit` 三种，CLI 应当校验并在非法值时直接报错，而不是等 API 返回 400。

#### 3.5 `api` — 端点发现与安全直调

```bash
logto-mgmt api search mfa                  # 从 swagger.json 搜端点
logto-mgmt api schema "POST /api/my-account/mfa-verifications/totp"
logto-mgmt api call GET /api/roles
logto-mgmt api call PATCH /api/account-center --json-file body.json [--yes]
```

`api search` 是本次设计里**性价比最高的一项**：它把"端点靠猜"这个根本问题解决掉，而且随 Logto 版本自动准确。非 GET 的 `api call` 需要 `--yes` 确认。

### P1 — 让审计与运维可复现

#### 3.6 `snapshot` — 租户配置快照与 diff

```bash
logto-mgmt snapshot dump [--out snapshot.json] [--markdown report.md]
logto-mgmt snapshot diff <old.json> [<new.json>]
```

一次抓齐 applications / resources+scopes / roles / sign-in-exp / account-center / connectors（模板只记摘要与 hash，不落全文避免噪音）/ 用户总数。这一轮的租户盘点报告是人工写的；有了这个命令，它变成一条命令的产物，且能定期 diff 出"谁悄悄改了配置"。

#### 3.7 `resource` — API resource 与 scope

```bash
logto-mgmt resource list
logto-mgmt resource create <name> --indicator https://api.example.com [--ttl 3600]
logto-mgmt resource scope add <resource> <scope> [--description TEXT]
logto-mgmt role add-scope <role> <resource> <scope>
```

补上 role 与 scope 的绑定——现有 `role` 组只能建 role、发 role，挂不了权限，这让 RBAC 只能半自动。

#### 3.8 `user mfa` — 管理员侧 MFA 运维

```bash
logto-mgmt user mfa list <email>
logto-mgmt user mfa delete <email> <verification-id>   # dry-run 默认
```

对应 `GET/POST /api/users/{userId}/mfa-verifications` 与 `DELETE .../{verificationId}`。这是"用户换手机、验证器丢了"的标准救援动作，也是测试账号被卡住时唯一的出路。

#### 3.9 `org` — organization

```bash
logto-mgmt org list | create | add-member | set-mfa-policy
```

之所以现在就列进来：分层强制 MFA（只对 admin 强制、学员不强制）的落地方式正是 organization-level MFA policy，这件事迟早要做。

### P2 — 有价值但不急

- `connector list` / `connector test-send`（验证 SMTP 配置连通性）
- `custom-jwt`（自定义 token claim 脚本的读写）
- `webhook`
- `doctor` — 启动前自检：`.env` 里的 `op://` 是否解析成功、tenant_id 能否从 endpoint 推导、M2M token 能否取到、以及**逐端点探测权限**（哪些返回 200 / 403）。这一轮在 Cloudflare 侧靠逐端点探测才发现"token 有效但缺某项权限"，Logto 侧同样值得有。

## 4. Library 层的人机工程修复

这几处是使用中直接绊倒人的地方，建议在扩充同时一并修：

| 现状 | 问题 | 建议 |
|---|---|---|
| `_request` 返回 `requests.Response` | 与其它返回 `dict` 的方法不一致，首次使用必踩 | 提供公开的 `request(...) -> dict`（自动 `.json()`、非 2xx 抛带 code/message 的异常），保留 `raw=True` 逃生口 |
| 参数名 `json_body` | 与 `requests` 惯例不同，`json=` 直接 TypeError | 接受 `json=` 作为别名 |
| 自定义域必须显式 `tenant_id` | 报错发生在取 token 时，且没说去哪找 | endpoint 是 `*.logto.app` 时自动推导；自定义域仍要求显式，但错误信息里给出"在 Console 的 Management API indicator 里能看到"这类指引 |
| 方法名以 `_` 开头却是主要入口 | 暗示私有，实际是长尾唯一通道 | 公开化并写进 README |

## 5. 写操作安全模型

统一按风险分三档：

**整体替换型配置**（connector、sign-in-exp、account-center）：强制读—改—写；写前自动备份到 `.logto-backups/<timestamp>-<resource>.json`；写后回读校验关键字段。这类操作最容易"改一处、丢一片"。

**创建型**（app、resource、role、scope）：直接执行，输出新建对象的 id，便于脚本串联。

**删除型**（app、user、role、mfa verification）：沿用现有 `user delete` 的 dry-run 默认约定——先输出将要删除的对象与一段面向 AI 的警告，只有显式 `--execute` 才真删。

## 6. 明确不做

- 不包装 Account API（`/api/my-account/*`）。那是**终端用户**用自己的 token 调的，属于产品前端职责；管理员 skill 混进去会诱导误用管理员凭证去改用户数据。
- 不做交互式 TUI。输出要能被 agent 直接消费。
- 不追求端点全覆盖。长尾由 `api search` + `api call` 承接。

## 7. 建议实施顺序

1. **先修 library 人机工程 + 加 `api search`/`api call`**。这一步立刻把"任何端点都能安全调用"变成现实，后续每个专用命令都只是锦上添花。
2. `sign-in-exp` + `account-center`（只读优先，写操作随后）。
3. `app`。
4. `email-template`（含备份/恢复）——写之前先把备份机制做好。
5. `snapshot` + `diff`。
6. `resource` / `role add-scope` / `user mfa`。
7. `org`、`doctor`，以及 P2 长尾。

## 8. 公开 repo 约束提醒

本 repo 是公开的。新增文档、测试与 fixture 一律使用占位值（`https://example.com`、`your-tenant-id`、`alice@example.com`、`op://your-vault/your-item/field`），不得出现真实租户 ID、真实 app ID、真实域名或真实邮箱。涉及具体租户的路由与凭证位置写在使用方 workspace 的私有 skill 覆盖层里。
