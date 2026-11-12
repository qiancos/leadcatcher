# 部署到 Render（免费版，约 5 分钟）

仓库里已经带了 `render.yaml`（Render Blueprint），不需要在控制台里一项项填配置。

## 一、一键部署

1. 打开 <https://render.com>，用 GitHub 账号登录（首次会要求授权访问仓库）
2. 点 **New +** → **Blueprint**
3. 选择仓库 `qiancos/leadcatcher` → **Apply**
4. Render 会让你填两个环境变量（都可以留空）：
   - `LLM_API_KEY`：填了就走真实模型，留空自动降级为本地规则引擎
   - `ADMIN_TOKEN`：填了访问要口令，留空则免口令（Demo 建议留空）
5. 等 3–5 分钟，拿到地址：`https://leadcatcher-xxxx.onrender.com`

**验收**：打开 `/api/health` 应返回 `{"status":"ok"}`；首页应能看到 31 条演示线索。

## 二、两个必须知道的限制

### 1. 免费实例的磁盘是临时的

重启、重新部署都会清空 SQLite。所以启动命令里加了 `python seed.py`：
**磁盘一空就自动重灌 31 条演示数据**，保证面试官点开时页面不是空的。

代价是：你在线上手工录入的线索，重启后会消失。

要真正持久化，需要：
- 升级到付费实例（最低约 $7/月）
- 取消 `render.yaml` 末尾 `disk:` 三行的注释，重新部署

### 2. 免费实例会休眠

15 分钟无访问会休眠，下次访问首屏要 30–60 秒（冷启动 + 建库 + 灌数据）。
**演示前 5 分钟先自己打开一次预热**，别让面试官等。

## 三、手动部署（不用 Blueprint）

如果更习惯在控制台点：

| 配置项 | 值 |
| --- | --- |
| Runtime | Python 3.12 |
| Build Command | `pip install -r server/requirements.txt` |
| Start Command | `cd server && python seed.py && uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/api/health` |

环境变量同上表。

## 四、关于「提交构建产物」这件事

`server/app/static/` 是 `npm run build` 的产物，正常做法是交给 CI 构建、不提交。
这里提交了，原因是：

- Render 的 **Python runtime 里没有 Node**，构建阶段跑不了 `vite build`；
- 另一条路是多阶段 Docker（node 构建 → python 运行），但**本机没装 Docker，我无法验证**；
- 于是我选了**自己能验证到底**的那条路：本地构建 → 提交产物 → 部署时只装 Python 依赖。

这是有意的取舍，不是不知道规矩。要改回标准做法，只需加一个 Dockerfile 并把
`server/app/static/` 重新加回 `.gitignore`。

## 五、其他部署方式

| 方式 | 适用场景 | 备注 |
| --- | --- | --- |
| Railway | 想挂持久化卷又不想折腾 | 支持 Dockerfile / Python，卷比 Render 宽松 |
| 轻量云服务器 | 长期演示 | nginx 反代 + systemd 跑 uvicorn，SQLite 文件在磁盘上天然持久 |
| 仅本地 | 面试现场演示 | `python -m uvicorn app.main:app --port 8000`，配合录屏兜底 |

## 六、部署后自检清单

- [ ] `https://<域名>/api/health` 返回 ok
- [ ] 首页有 31 条线索（否则看日志里 `seed.py` 的报错）
- [ ] 录入一条新对话，能返回解析结果
- [ ] 大盘三个图有数据，不是空图
- [ ] `/docs` 能打开 Swagger（演示时可以直接给面试官看接口）
- [ ] 手机端打开虽然没适配，但不应白屏
