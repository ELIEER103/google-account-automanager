[根目录](../../CLAUDE.md) > [web](..) > **backend**

# Web Backend 模块

FastAPI 后端服务，提供 REST API 和 WebSocket 实时通信。

## 变更记录 (Changelog)

| 时间 | 变更内容 |
|------|----------|
| 2026-01-25 21:57:39 | 初始化模块文档 |

---

## 模块职责

- 提供账号管理 REST API（CRUD、批量导入/导出）
- 提供浏览器窗口管理 API
- 提供任务调度和执行 API
- 通过 WebSocket 实时推送任务进度

## 入口与启动

**入口文件**: `main.py`

```bash
# 启动命令
uv run python -m uvicorn web.backend.main:app --reload --port 8000
```

**访问地址**:
- API: http://localhost:8000
- Swagger 文档: http://localhost:8000/docs
- ReDoc 文档: http://localhost:8000/redoc

## 对外接口

### REST API 路由

| 路由前缀 | 文件 | 职责 |
|----------|------|------|
| `/api/accounts` | `routers/accounts.py` | 账号 CRUD、批量导入/导出 |
| `/api/browsers` | `routers/browsers.py` | 浏览器窗口管理 |
| `/api/tasks` | `routers/tasks.py` | 任务创建、查询、取消 |
| `/api/config` | `routers/config.py` | 配置管理（卡信息、API Key） |
| `/ws` | `websocket.py` | WebSocket 实时通信 |

### 主要端点

#### 账号管理 (`/api/accounts`)
- `GET /` - 获取账号列表（分页、筛选、搜索）
- `GET /stats` - 获取账号统计
- `POST /` - 创建账号
- `PUT /{email}` - 更新账号
- `DELETE /{email}` - 删除账号
- `POST /import` - 批量导入
- `GET /export/all` - 导出账号
- `GET /export/2fa` - 导出 2FA（otpauth URI 格式）

#### 浏览器管理 (`/api/browsers`)
- `GET /` - 获取浏览器列表
- `POST /` - 创建浏览器窗口
- `DELETE /{browser_id}` - 删除浏览器窗口
- `POST /{browser_id}/open` - 打开浏览器
- `POST /restore/{email}` - 恢复浏览器窗口
- `POST /sync-2fa` - 同步 2FA 到浏览器

#### 任务管理 (`/api/tasks`)
- `POST /` - 创建任务
- `GET /` - 获取所有任务
- `GET /{task_id}` - 获取任务详情
- `DELETE /{task_id}` - 取消任务

### WebSocket 消息格式

**连接**: `ws://localhost:8000/ws`

**消息类型**:
```json
// 任务进度
{
  "type": "task_progress",
  "data": {
    "task_id": "abc123",
    "task_type": "setup_2fa",
    "status": "running",
    "total": 10,
    "completed": 5,
    "message": "..."
  }
}

// 账号进度
{
  "type": "account_progress",
  "data": {
    "task_id": "abc123",
    "email": "user@example.com",
    "status": "running",
    "current_task": "设置2FA",
    "message": "..."
  }
}

// 日志
{
  "type": "log",
  "data": {
    "level": "info",
    "message": "...",
    "email": "user@example.com"
  }
}
```

## 关键依赖与配置

### 依赖

- FastAPI - Web 框架
- Pydantic - 数据验证
- uvicorn - ASGI 服务器

### 配置文件

- `config.json` - 存储卡信息和 SheerID API Key（项目根目录）

## 数据模型

详见 `schemas.py`:

| 模型 | 用途 |
|------|------|
| `Account` | 账号信息 |
| `AccountStatus` | 账号状态枚举 |
| `TaskType` | 任务类型枚举 |
| `TaskStatus` | 任务状态枚举 |
| `TaskProgress` | 任务进度 |
| `BrowserInfo` | 浏览器窗口信息 |

## 测试与质量

当前无自动化测试。建议:
- 使用 pytest + httpx 进行 API 测试
- 使用 pytest-asyncio 测试 WebSocket

## 常见问题 (FAQ)

**Q: WebSocket 连接失败？**
A: 检查是否超过最大连接数（50），查看 `websocket.py` 中的 `MAX_CONNECTIONS`

**Q: 任务执行卡住？**
A: 检查 `tasks.py` 中的 `ThreadPoolExecutor`，默认 max_workers=5

**Q: CORS 错误？**
A: 查看 `main.py` 中的 CORS 配置，默认允许所有来源

## 相关文件清单

```
web/backend/
├── __init__.py
├── main.py           # 应用入口，路由注册
├── schemas.py        # Pydantic 数据模型
├── websocket.py      # WebSocket 连接管理
└── routers/
    ├── __init__.py
    ├── accounts.py   # 账号管理 API
    ├── browsers.py   # 浏览器管理 API
    ├── config.py     # 配置管理 API
    └── tasks.py      # 任务执行 API（核心）
```
