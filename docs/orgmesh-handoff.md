# OrgMesh 云电脑接续说明

## 获取代码

```bash
git clone https://github.com/het2333/OrgMesh.git
cd OrgMesh
```

仓库保留原 Offira 历史。默认分支的当前内容为 OrgMesh。

## 项目状态

- OrgMesh 基于 Onyx Community v4.8.1，使用中文企业工作台。
- P1 包含中文检索、飞书同步与权限、员工目录、模型检测及 Agent 模板。
- Presenton 通过平台身份、作品权限和模型转发接入。
- 本地聊天使用 DeepSeek API；嵌入使用 `intfloat/multilingual-e5-small`。
- 仓库未包含账号、模型 API Key、数据库、Docker 数据卷或模型权重。

先阅读 [部署说明](../README.orgmesh.md) 和根目录 `AGENTS.md`。
修改后端或前端时，继续阅读对应目录的 `AGENTS.md`。

## 云电脑环境

先确认系统、CPU 架构、可用内存、磁盘、Docker 和网络。
前端构建需要 Node.js 24 和 Bun。Python 依赖由 uv 管理。
在云电脑构建对应架构的镜像。不要依赖开发机的本地镜像。

```bash
docker build -f deployment/Dockerfile.orgmesh-backend -t orgmesh-backend:local .
bash deployment/build_orgmesh_web.sh
bash deployment/build_orgmesh_presenton.sh
```

企业私有部署先使用 `deployment/init_orgmesh_private.py` 生成独立配置。
按部署说明配置 TLS、企业邮箱和 SMTP，再通过 `onyx-private.sh` 启动。
启用 Presenton 时运行 `deployment/enable_orgmesh_presenton.py --env-file deployment/docker_compose/.env.private`。

云电脑对外访问应使用独立用户认证。本机共享所有者入口仅用于本机开发。

## 数据和凭据

克隆仓库不会迁移现有数据。迁移原工作区需要单独备份数据库、文件和演示文稿数据卷。

迁移原数据库时，保留对应加密密钥和认证密钥。使用私密连接传输备份及配置。
不要将 `.env`、`.env.private`、`.orgmesh-local/` 或数据库备份提交到仓库。

## 后续验收

1. 启动后检查核心服务健康状态。
2. 核对搜索、来源、Agent、模型配置和用户权限。
3. 完成 Presenton 页面 PPTX 下载、PDF 导出及短文本 AI 编辑验收。
4. 检查导出文件的中文排版及作品归属。
5. 使用企业实际资料验证飞书、SSO、检索质量和目标并发。

本机曾因资源压力出现服务不健康。云电脑接续时应先排查资源及服务日志。

## 已完成的本轮检查

仓库发布前，47 项针对性测试通过，覆盖 Presenton 网关、私有部署配置和中文查询。
代码快照检查、脚本语法检查和 README 相对链接检查通过。
上述检查不能替代云电脑的部署和导出验收。
