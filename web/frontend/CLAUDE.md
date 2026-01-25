[根目录](../../CLAUDE.md) > [web](..) > **frontend**

# Web Frontend 模块

Vue 3 + Vite 前端界面，提供账号管理、浏览器管理和任务执行的 Web UI。

## 变更记录 (Changelog)

| 时间 | 变更内容 |
|------|----------|
| 2026-01-25 21:57:39 | 初始化模块文档 |

---

## 模块职责

- 账号管理界面（列表、搜索、筛选、导入/导出）
- 浏览器窗口管理界面
- 任务执行界面（选择任务类型、执行、实时进度）
- 配置管理界面（卡信息、API Key）

## 入口与启动

**入口文件**: `src/main.ts` 或 `src/main.js`

```bash
# 开发模式
cd web/frontend; npm run dev

# 构建生产版本
cd web/frontend; npm run build

# 预览构建结果
cd web/frontend; npm run preview
```

**访问地址**: http://localhost:5173

## 对外接口

前端通过以下方式与后端通信:

- **REST API**: 通过 fetch/axios 调用 `http://localhost:8000/api/*`
- **WebSocket**: 连接 `ws://localhost:8000/ws` 接收实时进度

## 关键依赖与配置

### 依赖

- Vue 3 - 前端框架
- Vite - 构建工具
- Element Plus - UI 组件库
- Vue Router - 路由

### 配置文件

- `vite.config.ts` - Vite 构建配置
- `package.json` - 依赖和脚本

## 页面组件

| 组件 | 路径 | 职责 |
|------|------|------|
| `AccountsView.vue` | `src/views/AccountsView.vue` | 账号管理页面 |
| `BrowsersView.vue` | `src/views/BrowsersView.vue` | 浏览器管理页面 |
| `TasksView.vue` | `src/views/TasksView.vue` | 任务执行页面 |
| `ConfigView.vue` | `src/views/ConfigView.vue` | 配置管理页面 |

## 测试与质量

当前无自动化测试。建议:
- 使用 Vitest 进行单元测试
- 使用 Cypress 或 Playwright 进行 E2E 测试

## 常见问题 (FAQ)

**Q: 开发服务器启动失败？**
A: 确保已运行 `npm install`，检查 Node.js 版本 >= 18

**Q: API 请求失败？**
A: 确保后端服务已启动（端口 8000），检查 CORS 配置

**Q: WebSocket 连接失败？**
A: 检查后端 WebSocket 服务状态，确认端口未被占用

## 相关文件清单

```
web/frontend/
├── index.html
├── package.json
├── vite.config.ts
├── src/
│   ├── App.vue           # 根组件
│   ├── main.ts           # 入口文件
│   ├── components/       # 通用组件
│   │   └── HelloWorld.vue
│   └── views/            # 页面组件
│       ├── AccountsView.vue
│       ├── BrowsersView.vue
│       ├── TasksView.vue
│       └── ConfigView.vue
└── public/               # 静态资源
```
