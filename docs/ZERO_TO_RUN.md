# Amazon Selector 从零部署与使用

本文面向在 Windows 公司电脑上首次部署的使用者，覆盖手动 WebUI、Hermes，以及兼容
MCP 的其他 Agent Harness。正式流程固定为：Amazon 真实商品 → 卖家精灵市场证据 →
卖家精灵插件“1688 找货” → 真实 1688 详情 → 利润/评分 → 单个 Excel。正式运行不会用
mock 供应商补齐结果。

## 1. 先分清三个入口

| 名称 | 作用 | 是否操作网页 | 本项目中的位置 |
|---|---|---:|---|
| 卖家精灵 Chrome 插件 | 使用可见、已登录的卖家精灵页面导出证据，并执行“1688 找货” | 是 | 正式寻源路径，依赖 9222 专用 Chrome |
| 卖家精灵官方 MCP | 调用卖家精灵官方结构化工具，获取 ASIN、销量、竞品、关键词等市场数据 | 否 | 可选上游数据通道，`MJJL_TRANSPORT=mcp` |
| Amazon Selector MCP | 把本项目的环境检查、任务、候选、报告、人工处理等 19 个工具暴露给 Agent | 间接 | 本机 `http://127.0.0.1:8766/mcp` |

卖家精灵插件与卖家精灵官方 MCP 不是互相完全替代：

- 插件使用用户真实浏览器会话，能执行页面专属的“1688 找货”，也会遇到登录、验证码、
  插件权限和页面变化；这些情况必须由人处理。
- 官方 MCP 不依赖 Chrome 页面，适合稳定取得结构化市场数据，也更容易被程序或 Agent
  调用；它需要卖家精灵开放平台密钥和相应额度，且返回字段可能比 REST 精简。
- 本项目可以用官方 MCP 替代卖家精灵 REST 市场数据通道，但正式“1688 找货”仍依赖
  Chrome 插件。可运行 `python scripts/verify_sellersprite_mcp.py` 检查 MCP 字段是否满足
  当前评分需求。
- Amazon Selector MCP 与卖家精灵官方 MCP 无关：前者是本项目对 Agent Harness 的受控
  门面，后者只是本项目可选调用的一个上游数据源。

## 2. 支持哪些运行方式

| 方式 | 支持状态 | 启动入口 | 适用场景 |
|---|---|---|---|
| Windows 手动 WebUI | 直接支持，推荐 | `start.ps1` | 日常部署、登录、验证码和人工续跑 |
| Hermes 0.20.x | 已提供受限 profile | `scripts/start_hermes_client.sh` | 用自然语言调用完整选品工具集 |
| 其他 MCP Agent Harness | 协议兼容 | Compose `assistant` profile | 宿主支持 Streamable HTTP MCP、Bearer Header 和人工确认 |
| DeepSeek | 取决于承载它的客户端 | 连接 Selector MCP | DeepSeek 是模型；其 Harness 支持上述 MCP 能力时可用 |

因此，“可以从 Hermes 打开运行”是明确支持且已有安装脚本的；“从 DeepSeek Harness
运行”需要具体客户端具备 MCP 客户端能力，不能把任意 DeepSeek 聊天页面视为可直接运行。

## 3. Windows 公司电脑前置条件

1. Windows 10/11、WSL2 和 Docker Desktop（Linux containers）。
2. Google Chrome。`start.ps1` 会创建独立 profile，不复用日常 Chrome profile。
3. Git；Hermes 方式还需提前安装兼容的 Hermes Agent `>=0.20.0,<0.21.0`。
4. 一种模型 API：阿里云 Token Plan、阿里云百炼按量付费、PPIO 或 Anthropic。
5. 卖家精灵账号和 Chrome 插件，以及可登录的 Amazon、1688 账号。

默认端口都只绑定本机：WebUI `8765`、Selector MCP `8766`、Chrome CDP `9222`。不要把
WebUI、MCP 或 9222 暴露到公网。

## 4. 获取代码并创建私有配置

在 WSL 中执行：

```bash
git clone git@github.com:MC-Elixir/Goods-Selector.git
cd Goods-Selector
git switch dev0.1
cp .env.example .env
chmod 600 .env
```

`.env` 含密钥，已被 Git 忽略，禁止提交。二选一配置阿里云：

```dotenv
# 方案 A：阿里云 Token Plan。sk-sp- Key 必须匹配所选地域端点。
MODEL_API_PROVIDER=aliyun_token_plan
ALIYUN_TOKEN_PLAN_API_KEY=你的_sk-sp_key
ALIYUN_TOKEN_PLAN_API_BASE=https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
ALIYUN_TOKEN_PLAN_VISION_MODEL=qwen3-vl-plus
ALIYUN_TOKEN_PLAN_TEXT_MODEL=qwen-plus

# 方案 B：阿里云百炼按量付费。启用时把 MODEL_API_PROVIDER 改为 aliyun。
# MODEL_API_PROVIDER=aliyun
# ALIYUN_API_KEY=你的百炼_key
# ALIYUN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
# ALIYUN_VISION_MODEL=qwen3-vl-plus
# ALIYUN_TEXT_MODEL=qwen-plus

ALIBABA_ALLOW_MOCK_SUPPLIERS=false
ENABLE_SCRAPLING_MATCHER=false
BU_CDP_HTTP=http://host.docker.internal:9222
LOG_DIR=data/logs
```

市场数据有两种选择：

```dotenv
# 默认：不配 MJJL_API_KEY，使用已登录的卖家精灵插件浏览器导出。

# 可选：卖家精灵官方 MCP 市场数据通道。
# MJJL_API_KEY=你的卖家精灵开放平台密钥
# MJJL_TRANSPORT=mcp
# MJJL_MCP_URL=https://mcp.sellersprite.com/mcp
```

不配置 Keepa/Rainforest 时，Amazon 使用项目爬虫。正式寻源仍需卖家精灵插件完成
“1688 找货”，即使市场数据选择了官方 MCP。

## 5. 推荐方式：Windows 手动启动

先启动 Docker Desktop，并等待 Engine ready。然后在 Windows 文件资源管理器打开项目的
Windows 路径，在该目录启动 PowerShell：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\start.ps1
```

不要在 WSL Bash 中运行 `start.ps1`。脚本会：

1. 在 Windows `127.0.0.1:9222` 启动独立 Chrome；
2. 构建并启动 `amazon-selector` 容器；
3. 从容器内验证 `host.docker.internal:9222` 及真实 CDP WebSocket；
4. 验证 WebUI preflight，并打开 `http://127.0.0.1:8765`。

首次启动后，在这个独立 Chrome 中安装/启用并登录卖家精灵插件，同时登录 Amazon 和
1688。打开操作页完成 locator/download 配置和登录检查：

```text
http://127.0.0.1:8765/operator
```

只有 preflight 中 Chrome、卖家精灵插件和所需登录态均就绪后，才开始正式任务。插件
登录、权限、额度或验证码出现问题时，任务会暂停；处理后点击“我已处理，继续任务”。

## 6. 手动使用流程

1. 打开 `http://127.0.0.1:8765`。
2. 先运行环境检查，确保没有 blocking 项。
3. 选择 Amazon US 类目或输入关键词，先用 `limit=1` 做小任务验收。
4. 若操作页提示人工处理，在独立 Chrome 完成登录/验证码，再恢复原任务。
5. 完成后在页面下载单个 Excel；后台 JSON 和诊断保存在 `data/`。

命令行调试入口仍可用，但不是公司电脑的日常正式入口：

```bash
python main.py init-db
python main.py run --category "Home & Kitchen" --limit 1
```

## 7. Hermes 自然语言入口

先按第 4、5 节准备 `.env` 和 9222 专用 Chrome，然后在 WSL 项目根目录执行：

```bash
chmod +x scripts/start_hermes_client.sh
./scripts/start_hermes_client.sh
```

脚本会生成至少 24 位的 `SELECTOR_MCP_TOKEN`，安装/更新受限的
`amazon-selector-client` profile，启动 WebUI 与 MCP sidecar，并进入 Hermes 对话。
可以依次要求：

```text
检查选品环境
列出支持类目
开始一个 1 件商品的 Home & Kitchen 任务
查看任务状态和人工处理项
给我当前排名最高的候选和报告
```

启动、保存、恢复、取消或重试等写操作必须明确确认。Hermes profile 禁用了终端、文件、
通用浏览器、搜索、消息、定时任务和委派，只允许本项目白名单工具。

## 8. 其他 Harness / DeepSeek 模型接入

先启动项目和 MCP sidecar：

```bash
python scripts/setup_hermes_client.py
docker compose --profile assistant up -d --build amazon-selector selector-mcp
```

然后把目标 Harness 的 MCP 客户端配置为：

```text
Transport: Streamable HTTP
URL: http://127.0.0.1:8766/mcp
Header: Authorization: Bearer <.env 中的 SELECTOR_MCP_TOKEN>
```

具体配置文件格式由 Harness 决定。最低要求是：支持 Streamable HTTP MCP、自定义
Authorization Header、工具审批/人工确认，并能保持多轮任务上下文。若某个 DeepSeek
客户端不支持这些能力，它只能作为文本模型使用，不能直接控制本项目。

## 9. 验收

```bash
docker compose ps
curl -fsS http://127.0.0.1:8765/api/config/status
curl -fsS http://127.0.0.1:8765/api/preflight

# 启动 assistant profile 后，不带认证应返回 401，表示认证门已生效。
curl -i http://127.0.0.1:8766/mcp

# 查看诊断，输出中不应包含密钥。
docker compose logs --tail=200 amazon-selector selector-mcp
```

最终业务验收不是“容器启动”而是：完成一个 `limit=1` 的真实任务，产生包含真实 Amazon、
卖家精灵和 1688 证据的 Excel，且 `mock_count=0`。无法取得供应商证据时应失败关闭或要求
人工处理，不能把无证据结果当作可采购结论。

## 10. 常见问题

- **Windows 能访问 9222，容器不能访问**：重新运行 `start.ps1`，按它打印的容器内诊断
  检查 Docker Desktop；不要把 Chrome 改成监听 `0.0.0.0`。
- **SellerSprite extension unavailable**：确认是在独立 9222 Chrome 中安装并登录插件，
  locator profile 和下载目录已在操作页配置，并重新运行 preflight。
- **验证码、登录或额度问题**：保持原任务，人工处理后恢复；不要新建重复任务。
- **构建时下载超时**：先确认 Docker Desktop 网络和 DNS。只有公司网络明确要求代理时才
  设置 Docker/构建代理；普通 WSL Python 安装可先清除 `HTTP_PROXY`、`HTTPS_PROXY`、
  `ALL_PROXY` 后重试。
- **Token Plan 401/模型不可用**：检查 `sk-sp-` Key 是否与北京或新加坡地域 Base URL
  配套，不要把 Token Plan Key 发往普通百炼端点。

## 11. 更新、停止和备份

```bash
git pull --ff-only origin dev0.1
docker compose --profile assistant up -d --build amazon-selector selector-mcp

docker compose --profile assistant stop
```

运行数据位于 `data/`，包括 SQLite、cookies、缓存、日志和导出。升级前备份 `data/` 与
私有 `.env`；这些文件不得提交到 Git 或发给无关人员。
