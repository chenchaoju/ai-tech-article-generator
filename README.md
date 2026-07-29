# 文章工坊

一个基于 FastAPI、Vue 3、PostgreSQL 和 GLM-4.6 的中文技术文章生成系统。系统将用户提供的真实项目背景、问题、排查过程、代码和参考资料整理成适合 CSDN 发布的 Markdown 文章，并在提示词层面禁止虚构经历、测试结果与技术参数。

## 已实现功能

- 文章新建与真实项目材料录入
- 调用 GLM-4.6 生成 Markdown 技术文章
- 前端“模型设置”页面统一配置 API Key、角色模型和联网搜索
- 输入主题后联网检索技术文章，并选择参考来源
- 默认返回 10 篇候选来源并优先覆盖不同网站，可继续加载“更多来源”
- 可选择全网、今日头条、CSDN、掘金、知乎、博客园，或添加自定义网站
- 来源支持按发布日期排序，以及近 7 天、30 天和 1 年筛选
- 根据文章类型、表达风格和排版方式生成 10 个标题，可随时“换一批”
- 专家先整理可拓展论点、材料依据、字数规划和事实边界，并把资料同时交给写手与编辑总监
- 写手与审核官在同一轮调用中依次产出两版正文，编辑总监独立完成终审
- 字数不足时，审核官可以退回写手补写；总监会结合专家解析和当前稿件亲自重组、扩写细节与总结，并始终保存当前最完整稿件
- 修改记录根据各版正文的实际差异生成，不保存前后相同的占位记录
- 发布中心支持 CSDN、今日头条、知乎、掘金、博客园，并可通过官方 API 自动发布到微信公众号
- 创作台不再要求填写多组材料，只保留一个完全可选的补充框
- Markdown 在线编辑与实时预览
- 保存草稿
- 文章列表、关键词搜索与状态筛选
- 文章详情查看
- 一键复制 Markdown，兼容 HTTP 内网或公网 IP 访问
- 从素材库插入图片后立即保存正文与素材信息到文章数据库
- 所有数据库与模型配置集中在项目根目录 `.env`

## 项目结构

```text
ai-tech-article-generator/
├─ backend/
│  ├─ app/
│  │  ├─ api/routes/       # FastAPI 路由
│  │  ├─ core/             # 环境配置
│  │  ├─ db/               # PostgreSQL 会话与建表
│  │  ├─ models/           # SQLAlchemy 模型
│  │  ├─ schemas/          # Pydantic 请求/响应模型
│  │  └─ services/         # GLM-4.6 调用与写作约束
│  ├─ tests/
│  └─ requirements.txt
├─ frontend/
│  ├─ src/
│  │  ├─ api/
│  │  ├─ components/
│  │  ├─ router/
│  │  └─ views/
│  └─ package.json
├─ .env
├─ .env.example
└─ start.ps1
```

## 首次配置

本机已创建 PostgreSQL 数据库：

```text
数据库：ai_tech_articles
用户：xxxx
密码：xxxx
端口：5432
```

可以直接打开前端的“模型设置”页面填写 API Key。密钥只提交给本机
FastAPI 后端并保存到根目录 `.env`，前端读取设置时只会得到脱敏状态。

也可以手动打开项目根目录 `.env`，填写智谱开放平台 API Key：

```dotenv
GLM_API_KEY=你的_API_Key
```

微信公众号自动发布可在前端“模型设置”页面配置，也可以写入 `.env`：

```dotenv
WECHAT_APP_ID=公众号_AppID
WECHAT_APP_SECRET=公众号_AppSecret
WECHAT_AUTHOR=默认作者名
```

公众号后台还需要开启开发者能力，并将运行本系统的公网出口 IP 加入白名单。自动发布会上传文章图片、创建草稿并提交发布；没有可用封面图片时不会提交。

模型默认使用：

```dotenv
GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
GLM_MODEL=glm-4.6
GLM_EXPERT_MODEL=glm-4.6
GLM_WRITER_MODEL=glm-4.6
GLM_REVIEWER_MODEL=glm-4.6
GLM_DIRECTOR_MODEL=glm-4.6
GLM_SEARCH_COUNT=10
GLM_PROXY_URL=http://127.0.0.1:7897
```

`GLM_PROXY_URL` 仅在本机使用代理软件时填写；不使用代理时留空。

## 网站登录与 Cookie

来源检索优先使用公开内容，不要求登录。查看需要登录的原文时，从创作台点击
“打开网站并登录”，由浏览器正常保存该网站的登录状态。系统不会读取浏览器
Cookie，也不会把会话 Cookie 明文保存到 `.env` 或 PostgreSQL。

## 启动

在 PowerShell 中运行：

```powershell
cd C:\project\ai-tech-article-generator
.\start.ps1
```

访问：

- 前端：http://127.0.0.1:5173
- FastAPI 接口文档：http://127.0.0.1:8000/docs

## 手动启动

后端：

```powershell
cd C:\project\ai-tech-article-generator\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

前端：

```powershell
cd C:\project\ai-tech-article-generator\frontend
npm run dev
```

## 生成边界

系统提示词要求 GLM-4.6：

- 只使用用户明确提供的事实；
- 不虚构项目经历、团队背景、错误日志、版本号、测试数据和性能参数；
- 信息不足时省略，或使用“待补充”标记；
- 不使用“随着科技发展”等空泛开场；
- 不把示意代码写成已在真实环境验证的代码。
- 保留用户明确提供的判断、取舍、排查转折和真诚提醒；
- 不虚构焦虑、崩溃、兴奋等情绪来制造戏剧性；
- 审核官修正事实风险，但不能把文章改成冰冷的说明书。

这些约束能降低虚构风险，但发布前仍应由作者核对事实、代码与引用。
