# 溯源方 · 受试者访视与数据质疑协同平台

面向 II/III 期多中心注册临床试验的 DM/研究者/监查员协同平台。本轮交付**整套骨架**与
**入组作战台**、**受试者**两个菜单，页面打开即为真实业务数据。

## 一键启动

前置：Docker + Docker Compose v2。

```bash
docker compose up -d --build
```

| 服务 | 地址 | 说明 |
|---|---|---|
| 前端（Nginx） | http://localhost:8101 | 浏览器访问入口，Nginx 反代后端 |
| 后端（FastAPI） | http://localhost:7101 | 固定监听 7101，接口前缀 `/api`，文档 `/docs` |
| PostgreSQL 16 | 宿主 `localhost:5433` → 容器 5432 | 库/用户 `suyuan` |
| Redis 7 | 容器内 6379 | 会话/缓存预留，健康检查可见状态 |

首次启动自动建表并写入幂等种子数据（访视日期相对“今天”生成，任何一天拉起都能看到
今日应随访 / 逾期 / 超窗红点）。重置数据：

```bash
docker compose down -v && docker compose up -d --build
```

## 演示账号（密码统一 `Suyuan@2026`）

| 账号 | 角色 | 数据范围 |
|---|---|---|
| `dm` | 数据管理员（CRO/申办方） | 全部中心 |
| `inv01` / `inv02` / `inv03` | 研究者（北京/上海/广州） | 仅本中心，可申请查看全名 |
| `mon01` / `mon02` / `mon03` | 监查员（各中心） | 仅本中心，不可查看全名 |

研究中心：北京协和临床研究中心（BJ）、上海瑞金临床药理中心（SH）、广州中山医学研究中心（GZ）。
种子覆盖状态：筛选中、已入组、已完成、脱落、中止、筛选失败、剔除，并含**作废筛选号/
受试者编号**留痕（如 BJ-S005、BJ-007，永不复用）。

## 本轮功能

### 入组作战台 `/dashboard`
- 各中心入组进度（目标/入组/筛选/转化率/完成率/脱落/中止/剔除）与总体漏斗（筛选→入组→在研→完成）；
- 今日应随访清单；逾期（窗内）与已超窗红点聚合 KPI + 分表明细；
- 按账号中心范围自动过滤（研究者/监查员只见本中心）。

### 受试者链路 `/subjects`
- **完整状态机**：筛选登记 →（分配筛选号）→ 入组（分配受试者编号、姓名脱敏）→
  完成 / 脱落 / 中止 / 剔除；筛选中可转筛选失败。
- **非法状态回退拦截**：终态（完成/脱落/中止/筛选失败/剔除）拒绝一切回退，
  返回 409 并弹出可直接展示给研究者的中文原因；脱落/中止/剔除/筛选失败必须填原因。
- **编号规则**：`中心前缀 + 顺序号`（筛选号 `BJ-S001`，受试者编号 `BJ-001`），
  数据库行锁取号防并发重号；作废号推进游标、**永不复用**，分配/作废全部写入号码留痕。
  受试者列表「号码台账」可查看全量分配/作废记录（含不挂受试者的作废号，如 `BJ-S005`、`BJ-007`）。
- **PII 脱敏**：入组后列表/详情默认显示「缩写+编号」（如 `李**（BJ-002）`）；
  仅**本中心研究者**可经**二次确认 + 填写理由**临时查看全名，且每次查看写入
  全名查看记录（操作人/账号/时间/理由），监查与稽查可溯源；监查员/DM 调用直接 403。

### 平台能力
- **三端适配**：1440px 桌面（完整侧栏）/ 1024px 平板（图标侧栏、栅格折行）/
  390px 手机（抽屉导航、卡片双列、表格横滑）。
- **中心隔离**：所有查询按所属中心过滤；越权访问（如改 URL 访问其他中心受试者）
  返回明确 **403 错误页**（含原因与返回入口），不是空白页。
- **弱网/离线**：顶部红色横幅提示设备离线；“连着 Wi-Fi 但服务不通”显示黄色横幅并
  每 30 秒探活 `/api/health`；恢复后显示绿色指引条，要求**手动刷新数据**后再操作，
  避免弱网期间重复提交（种子中 GZ-S004 作废号即该场景的留痕示例）。

## 本地开发（不用 Docker）

```bash
# 后端
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
APP_DATABASE_URL=postgresql+psycopg2://suyuan:suyuan_pwd_2026@localhost:5433/suyuan \
APP_REDIS_URL=redis://localhost:6379/0 \
python -m app.seed
uvicorn app.main:app --reload --port 7101

# 前端（8101，/api 自动代理到 7101）
cd frontend
npm install && npm run dev
```

核心业务规则（状态机、编号、脱敏、窗期）为零三方依赖的纯模块，可离线单测：

```bash
cd backend && python3 -m unittest discover -s tests -v
```

## 目录

```
backend/   FastAPI + SQLAlchemy 2 + PostgreSQL + Redis + PyJWT
  app/domain.py            状态机/编号/脱敏/窗期（纯规则，可单测）
  app/routers/             auth / dashboard / subjects / sites
  app/seed.py              幂等种子（相对日期访视、作废号、PII 查看留痕）
frontend/  Vue 3 + Vite + Element Plus + ECharts + Pinia
  views/                   Login / Dashboard / SubjectList / SubjectDetail
```

> 生产部署前请修改 `APP_JWT_SECRET` 与数据库密码；接口已具备 JWT 鉴权与中心级行过滤。
