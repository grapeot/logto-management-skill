# 接口设计 — Logto Management Skill（clean-slate 重做）

> 状态：已批准并在 v0.2.0 实现
> 日期：2026-07-25
> 前置阅读：`expansion_design.md`（为什么要扩充：一次真实使用留下的证据）

## 0. 为什么可以推倒重做

这个 skill 的使用者几乎只有 AI agent，且使用方式由 skill 文档描述——**改了接口，同步改 skill 文档，调用方就自动跟上**。它不像面向人类开发者的库那样背着"别人已经写死了调用代码"的包袱。加上体量很小，所以：

**不做向后兼容妥协。** 直接设计成本该有的样子，一次到位。旧的 `_request` / `json_body` 这类别扭之处不保留 alias。

## 1. 设计目标

一句话：**让 agent 能安全地读懂并改动一个 Logto 租户的任何配置，且改错时能恢复。**

四条具体目标：

1. **可发现**：agent 不需要预先知道端点。Logto 的路径不可猜（实测踩过：MFA 端点按直觉写直接 404）。
2. **可复现**：任何配置状态都能一条命令导出，能 diff。
3. **可恢复**：整体替换语义的写操作自动备份，改坏能回滚。
4. **一致**：命令名、参数名、返回结构、错误结构在所有 group 之间同构，减少 agent 的猜测成本。

## 2. 分层结构

```text
logto-mgmt <group> <verb> [args]        ← CLI，与库的 namespace 一一对应
        ↓
LogtoClient.<group>.<verb>()            ← 库，按资源分 namespace
        ↓
LogtoClient.request()                   ← 唯一的 HTTP 出口（公开，长尾直调也走它）
        ↓
token 缓存 + 401 自动重试 + 统一错误封装
```

**CLI 与库的 namespace 严格同构**：`logto-mgmt app create` ⇄ `client.apps.create()`。这样 agent 读了 CLI 帮助就知道库怎么用，反之亦然。

## 3. 库接口

### 3.1 唯一 HTTP 出口

```python
client.request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json: dict | list | None = None,      # 注意：叫 json，不叫 json_body
    headers: dict | None = None,
    raw: bool = False,
) -> dict | list | requests.Response
```

- 默认**返回已解析的 JSON**（`dict` / `list`），不是 `requests.Response`。空响应体返回 `None`。
- `raw=True` 时返回原始 `Response`，用于下载文件、看响应头等少数场景。
- 非 2xx 抛 `LogtoAPIError`。
- 公开方法（不带下划线）——它是长尾端点的正当入口，不该看起来像私有。

### 3.2 错误类型

```python
class LogtoAPIError(Exception):
    status_code: int
    code: str | None        # Logto 的业务错误码，如 "user.same_password"
    message: str            # Logto 的 message 字段，取不到则用兜底文案
    body: dict | str        # 完整响应体
    url: str
```

比现状多一个 `code`：agent 需要按错误码分支（例如判断"校验记录过期"要重新验证身份），靠字符串匹配 message 很脆。

### 3.3 构造与 tenant 推导

```python
LogtoClient(endpoint, app_id, app_secret, tenant_id=None)
LogtoClient.from_env()          # 从 LOGTO_ENDPOINT / LOGTO_APP_ID / LOGTO_APP_SECRET / LOGTO_TENANT_ID 读
```

`from_env()` 是新增的便利构造——现状下每次都要手写四个 `os.environ[...]`，实测很啰嗦。

tenant_id 规则：endpoint 形如 `*.logto.app` 时自动推导；自定义域必须显式提供，**错误信息里要写清楚去哪找**（Console 的 Management API indicator）。

### 3.4 namespace 一览

```python
client.users            # 用户
client.roles            # 角色（含 scope 绑定）
client.apps             # 应用
client.resources        # API resource 与 scope
client.sign_in_exp      # 登录体验、MFA 策略、passkey、branding
client.account_center   # 账户自服务配置
client.email_templates  # 邮件模板（connector 内嵌）
client.user_mfa         # 管理员侧的用户 MFA 运维
client.orgs             # organization
client.snapshot         # 配置快照与 diff
client.api              # 端点发现（swagger 检索）
```

## 4. CLI 接口

### 4.1 通用约定（所有 group 一致）

| 约定 | 规则 |
|---|---|
| 成功输出 | JSON 到 stdout |
| 失败输出 | JSON 到 stderr：`{error, error_type, status_code, code}`，退出码非 0 |
| 对象定位 | 一律接受 **name 或 id**，内部自动解析。实测痛点：现状要先查 id 再操作 |
| 破坏性操作 | 默认 dry-run，输出将影响的对象 + 面向 AI 的警告 + `execute_command` 字段；加 `--execute` 才真做 |
| 配置写操作 | 强制自动备份 → 读改写 → 回读校验；不提供绕过入口 |
| 输出裁剪 | 大对象默认给摘要，`--full` 出全量。实测痛点：sign-in-exp 全量糊满终端，得自己写字段筛选 |

### 4.2 `api` — 端点发现与直调（**最高优先级**）

```bash
logto-mgmt api search <keyword>...                 # 按关键词搜端点（method/path/summary）
logto-mgmt api schema <method> <path>              # 看某端点的 request/response schema
logto-mgmt api call <method> <path> [--params k=v] [--json-file f | --json '{...}'] [--execute]
```

从租户自己的 `GET /api/swagger.json` 取真相，随 Logto 版本自动准确。非 GET 需 `--execute`。

**这一项解决的是根本问题**：端点不可猜。它的价值高于再多包十个具体端点，因为专用命令永远追不上 API 演进。

### 4.3 `sign-in-exp` — 登录体验与 MFA

```bash
logto-mgmt sign-in-exp get [--section signIn|mfa|passkey|branding|password|all] [--full]
logto-mgmt sign-in-exp set-mfa --policy NoPrompt|UserControlled|Mandatory [--factor Totp]...
logto-mgmt sign-in-exp set-passkey --enable|--disable [--show-button] [--allow-autofill]
logto-mgmt sign-in-exp set-branding [--logo-url URL] [--favicon-url URL]
```

`get` 默认摘要：登录 identifier、是否 password-primary、MFA policy 与 factors、passkey 三个开关。

### 4.4 `account-center` — 账户自服务配置

```bash
logto-mgmt account-center get
logto-mgmt account-center enable | disable
logto-mgmt account-center set-fields --field password=Edit --field email=ReadOnly ...
logto-mgmt account-center set-webauthn-origins --origin https://account.example.com ...
```

字段值只有 `Off` / `ReadOnly` / `Edit`，CLI 本地校验，非法值直接报错而不是等 API 返 400。

### 4.5 `email-template` — 邮件模板（**风险最高**）

```bash
logto-mgmt email-template list                     # usageType / subject / 内容长度 / hash
logto-mgmt email-template get <usageType> [--out file.html]
logto-mgmt email-template set <usageType> [--subject TEXT] [--content-file f] --execute
logto-mgmt email-template replace-text --find TEXT --replace TEXT [--usage-type X]... --execute
logto-mgmt email-template append-html --html-file f --after-marker '<hr...>' --usage-type X... --execute
logto-mgmt email-template backup [--out dir] | restore <backup.json> --execute
```

模板嵌在 connector 的 `config.templates` 数组里，任何写操作都是**整个 config 的 PATCH**——改一处、丢一片的风险极高。所以：所有写操作内部统一走"读全量 → 深拷贝 → 局部改 → PATCH → 回读校验"，并强制先备份。`replace-text` 对应真实需求（批量统一品牌文案）。

### 4.6 `app` — 应用

```bash
logto-mgmt app list [--type SPA|Traditional|MachineToMachine|Native]
logto-mgmt app get <name-or-id>
logto-mgmt app create <name> --type SPA [--redirect-uri URI]... [--post-logout-uri URI]... [--description TEXT]
logto-mgmt app update-uris <name-or-id> [--add-redirect URI]... [--remove-redirect URI]...
logto-mgmt app delete <name-or-id>                 # dry-run 默认
```

`get` 要把 `oidcClientMetadata`、`appLevelAccessControlEnabled`、`isThirdParty` 平铺——排查登录问题时最常看这几项。

### 4.7 `resource` / `role` — 权限

```bash
logto-mgmt resource list | get <name-or-id>
logto-mgmt resource create <name> --indicator https://api.example.com [--ttl 3600]
logto-mgmt resource scope add <resource> <scope> [--description TEXT]

logto-mgmt role list | get <name-or-id>
logto-mgmt role create <name> [--description TEXT]
logto-mgmt role add-scope <role> <resource> <scope>      # 现状缺失，导致 RBAC 只能半自动
logto-mgmt role assign <role> <email> | revoke <role> <email> | users <role>
```

### 4.8 `user` / `user-mfa` — 用户与 MFA 运维

```bash
logto-mgmt user find <email> | create <email> [--name N] | delete <email>
logto-mgmt user-mfa list <email>
logto-mgmt user-mfa delete <email> <verification-id>     # dry-run 默认
```

`user-mfa` 是"用户换手机、验证器丢失"的标准救援动作。真实场景：账号残留一个 TOTP 绑定而 secret 已丢，登录被卡住，只能管理员解绑。

### 4.9 `snapshot` — 快照与 diff

```bash
logto-mgmt snapshot dump [--out snapshot.json] [--markdown report.md]
logto-mgmt snapshot diff <old.json> [<new.json>]
```

一次抓齐 applications / resources+scopes / roles / sign-in-exp / account-center / connectors（模板只记摘要与 hash）/ 用户总数。此前的租户盘点报告是人工写的；有了它就变成一条命令的产物，还能定期 diff 出"谁悄悄改了配置"。

### 4.10 首次安装引导（skill 文档职责，非命令）

skill 文档里要有一条明确的触发规则：**当凭证缺失或权限不足时，agent 应走 `docs/onboarding.md` 的引导流程**，而不是反复重试或猜测。

之所以单列：创建 M2M 应用本身需要 Console 登录态，**agent 无法自我引导**，必须由人在 Console 完成。这一步骤化的人机协作过程需要被写死，否则每个 agent 都会用不同方式（且常常是错的方式，比如让用户把 App Secret 粘进对话）去处理。

一条实测确认的事实要写进引导：**Logto 的 Management API 资源只有一个 scope `all`**，权限是全有或全无，无法按端点细粒度授权。因此"最小权限"只能靠凭证卫生（引用而非明文）、一个消费方一份凭证（便于独立吊销）、以及本 skill 自身的护栏来兜。

### 4.11 `org` / `doctor`

```bash
logto-mgmt org list | create <name> | add-member <org> <email> | set-mfa-policy <org> --policy X
logto-mgmt doctor
```

`org` 之所以现在就要：分层强制 MFA（只对 admin 强制）的落地方式正是 organization-level MFA policy。

`doctor` 做启动前自检：`op://` 是否解析、tenant_id 能否推导、M2M token 能否取到、并逐端点探测权限（哪些 200 / 403）。真实教训：在另一个服务上正是靠逐端点探测才发现"token 有效但缺某项权限"。

## 5. 明确不做

- **不包装 Account API（`/api/my-account/*`）**。那是终端用户拿自己 token 调的，属产品前端职责；管理员 skill 混进去会诱导用管理员凭证改用户数据。
- **不做交互式 TUI**。输出要能被 agent 直接消费。
- **不追求端点全覆盖**。长尾由 `api search` + `api call` 承接。

## 6. 实施顺序

1. 库骨架：`request()` / `LogtoAPIError.code` / `from_env()` / namespace 空壳
2. `api`（search / schema / call）—— 立刻让"任何端点都能安全调用"成立
3. `sign-in-exp` + `account-center`
4. `app`
5. `email-template`（**先做 backup/restore，再做写命令**）
6. `snapshot` + `diff`
7. `resource` / `role add-scope` / `user-mfa`
8. `org` / `doctor`
9. 更新 skill 文档：补首次安装引导的触发规则，指向 `docs/onboarding.md`

`doctor` 在实施顺序里可以提前——它是首次安装引导的验证步骤，越早有越好。

## 7. 公开 repo 约束

本 repo 公开。文档、测试、fixture 一律用占位值（`https://example.com`、`your-tenant-id`、`alice@example.com`、`op://your-vault/your-item/field`），不得出现真实租户 ID、app ID、域名或邮箱。租户专属的路由与凭证位置写在使用方 workspace 的私有 skill 覆盖层。
