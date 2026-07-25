# 首次安装引导（写给 AI agent 执行）

> 这份文档不是给人读的手册，而是**给 agent 的执行脚本**：当 skill 尚未配好凭证时，agent 应当按这里的步骤带着用户走完第一公里。
> 日期：2026-07-25

## 0. 一个必须先承认的前提：agent 无法自我引导

本 skill 靠 M2M（machine-to-machine）凭证访问 Logto Management API。而**创建 M2M 应用本身就需要 Management API 权限或 Console 登录态**——这是个鸡生蛋问题。

所以：**第一步必然需要人在 Logto Console 里手动操作，agent 不能代劳。** agent 的职责是把步骤讲清楚、把要问的东西一次问全、并在拿到凭证后自动完成验证。不要试图绕过这一步，也不要让用户误以为你能自动搞定。

## 1. 什么时候触发这个引导

出现以下任一情况，就走本引导，而不是反复重试或猜测：

| 症状 | 含义 |
|---|---|
| 项目里没有 `.env` | 从未配置过 |
| 环境变量值仍是字面量 `op://...` | 没有经 `op run` 解析（见第 5 节） |
| 取 token 时 401 / `invalid_client` | App ID 或 Secret 错误 |
| 调 API 时 403 | M2M 应用没有被授予 Management API 角色（见第 3 节） |
| 报错提示需要 `LOGTO_TENANT_ID` | 用了自定义域名（见第 4 节） |

## 2. 让用户在 Logto Console 创建 M2M 应用

告诉用户走这条路径：

1. 打开 Logto Console（Cloud 用户是 `https://cloud.logto.io`；自托管是自己的 Console 地址）
2. 左侧 **Applications** → **Create application**
3. 应用类型选 **Machine-to-machine**
4. 名称建议写清用途，例如 `logto-mgmt-cli`（**一个消费方一个 M2M 应用**，理由见第 3.2 节）
5. 创建后在应用详情页能看到 **App ID** 与 **App Secret**

## 3. 授予权限

### 3.1 要授予什么

在刚创建的 M2M 应用详情页，找到 **Roles**（或 Machine-to-machine roles）区域，授予内建角色：

> **Logto Management API access**

这个角色携带 Management API 资源的 `all` scope。**没有这一步，凭证能取到 token 但所有 API 调用都会 403** —— 这是最常见的配置失败。

### 3.2 关于最小权限：Logto 这里给不了，要换个方式兜

必须对用户讲清楚这一点，不要含糊：

**Logto 的 Management API 资源只定义了一个 scope —— `all`**（实测确认：该资源的 scope 列表长度为 1，描述是 "Default scope for Management API, allows all permissions."）。也就是说**权限是全有或全无，无法按端点或按资源做细粒度授权**。一旦授予，这个凭证就能读写该租户的一切，包括用户、角色、应用、连接器与登录配置。

既然无法在 Logto 侧收窄权限，就用另外三层来兜：

1. **凭证卫生**：secret 只存密码管理器（推荐 1Password），`.env` 里只放 `op://` 引用，永不写明文、永不提交进 git。
2. **一个消费方一个 M2M 应用**：不要多个工具共用同一份凭证。这样任何一方泄露或不再需要时，可以单独吊销/轮换，不影响其它调用方。
3. **依赖本 skill 自身的护栏**：读优先、破坏性操作默认 dry-run、配置写操作自动备份。
4. **定期轮换**：Console 里可以重新生成 App Secret；轮换后更新密码管理器中的条目即可，`.env` 不用动。

## 4. 确认是否需要 tenant ID

- endpoint 形如 `https://<tenant-id>.logto.app` → **不需要**额外提供，可从 endpoint 推导。
- 使用**自定义域名**（如 `https://auth.example.com`）→ **必须**显式提供 tenant ID，否则取 token 会失败。

去哪找：Console 里 API resources 列表中，Logto Management API 的 indicator 形如 `https://<tenant-id>.logto.app/api`，其中的 `<tenant-id>` 就是要填的值。

## 5. 凭证怎么存（**agent 要主动守住这条**）

**不要让用户把 App Secret 粘贴到对话里。** 对话内容会进入日志与转录，明文 secret 一旦进去就很难清干净。

**首选路径（1Password）**：请用户自己在 1Password 里建一个条目（例如 vault `dev`、条目 `logto-m2m`），把 endpoint / app_id / app_secret 存成字段。然后用户只需把**引用路径**告诉 agent，引用路径本身不是机密：

```bash
# .env —— 只放引用，不放明文
LOGTO_ENDPOINT=op://your-vault/your-logto-item/endpoint
LOGTO_APP_ID=op://your-vault/your-logto-item/app_id
LOGTO_APP_SECRET=op://your-vault/your-logto-item/app_secret
# 仅自定义域名需要
# LOGTO_TENANT_ID=your-tenant-id
```

调用时由 `op run` 在进程启动前解析：

```bash
op run --env-file .env -- logto-mgmt <command>
```

若设了 `OP_SERVICE_ACCOUNT_TOKEN`，解析全自动；否则 `op` 会弹 Touch ID / 密码确认。

**退路（没有 1Password）**：让用户自己把明文写进 `.env`（agent 不要代写、不要在输出里回显 secret），并确认 `.env` 已被 `.gitignore` 阻塞。

## 6. 验证配置是否成功

配好后由 agent 跑一次**只读**验证，不要一上手就写：

```bash
op run --env-file .env -- logto-mgmt doctor
```

`doctor` 会依次检查：`op://` 是否解析成功、tenant ID 能否确定、M2M token 能否取到、以及逐端点探测权限（哪些返回 200 / 403）。

若暂时还没有 `doctor`，用任意只读命令替代：

```bash
op run --env-file .env -- logto-mgmt role list
```

## 7. 故障排查对照表

| 现象 | 原因 | 处理 |
|---|---|---|
| 错误里出现字面量 `op://...` | 没走 `op run` | 命令前面加 `op run --env-file .env --` |
| `401` / `invalid_client` | App ID / Secret 不对，或 secret 已轮换 | 回 Console 核对，必要时重新生成并更新密码管理器 |
| `403`（token 取到了但调用被拒） | M2M 应用没授予 Management API 角色 | 回第 3.1 节授予 **Logto Management API access** |
| 提示需要 `LOGTO_TENANT_ID` | 用了自定义域名 | 按第 4 节填入 tenant ID |
| `op` 报找不到条目 | 引用路径写错，或 service account 无权访问该 vault | 让用户核对 vault / 条目 / 字段名与访问权限 |
| 写操作报权限不足，读却正常 | 密码管理器里的 service account 可能是只读 | 与凭证权限无关，是密码管理器侧的授权问题 |

## 8. agent 在引导过程中的行为准则

- **一次把要问的问完**，不要来回挤牙膏：需要用户提供的通常只有「endpoint / 是否自定义域 / 1Password 引用路径」三项。
- **永不在输出里回显 secret**，即使用户主动粘贴了也不要复述。
- **不要代替用户点 Console**，也不要声称能自动创建 M2M 应用。
- **配好先跑只读命令**验证，再进行任何写操作。
- 如果用户明确说没有 Logto 租户，那是更前置的问题——先引导注册，再回到本流程。
