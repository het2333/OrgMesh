# OrgMesh 企业知识工作台

OrgMesh 面向企业私有部署，提供中文知识搜索、AI 问答、Agent 和演示文稿工具。

基于 [Onyx Community v4.8.1](https://github.com/onyx-dot-app/onyx)，集成 [Presenton](https://github.com/presenton/presenton)。

## 主要功能

- **知识搜索与问答**：关键词与向量混合检索、来源引用、中文 PDF OCR 和企业词表。
- **飞书接入**：文档、知识库、云空间、表格同步，以及员工目录和源权限检查。
- **Agent 工作台**：制度问答、员工入职和项目周报模板，可绑定企业知识库。
- **模型接入**：DeepSeek、通义千问和 OpenAI 兼容服务，可检查流式输出和工具调用。
- **演示文稿**：中文创建、参考文档上传、作品列表、编辑与保存、PPTX/PDF 导出接口。
- **私有部署**：独立账号、邮箱验证、TLS 和凭据加密存储。

## 部署

技术栈为 Python、FastAPI、Next.js、PostgreSQL、OpenSearch、Redis 和 Celery。

部署前需要构建 OrgMesh 镜像，生成专用配置，并准备模型和企业连接器凭据。

- [构建、部署与配置说明](README.orgmesh.md)
- [上游 Onyx 说明](README.onyx.md)
- [Presenton 固定版本](integrations/presenton/upstream.lock.json)

仓库不包含本机账号、API Key、数据库、数据卷、模型权重或运行中的企业配置。

## 当前验证范围

P1 已用合成中文资料验证搜索、Agent 回答、引用及权限链路。企业语料、SSO 和并发需要另行验收。

Presenton 已验证生成、编辑、保存与后台 PPTX 导出。最终页面下载、PDF 导出和短文本 AI 编辑验收仍待完成。

### 2026-10-02 源码检查点

本次提交包含统一历史记录页面、按所有者隔离的历史接口，以及 Go Phase 1 历史只读投影与 Python 回退。
Go 服务为可选组件。它没有替代 Onyx 主后端，也未完成生产部署验收。

Word 集成仅包含 Task 1 浏览器宿主源码。Gate A 的真实浏览器验收仍受环境限制，未通过。
Tasks 2–8 尚未实现，包括真实文档版本 API、候选运行时、Onyx 联动、提案操作和安全撤销。
源码测试与构建结果不能代替真实浏览器、DOCX 保真度和生产环境验收。

此次推送保存当前进度，不代表完整 Word 功能或生产就绪状态。
详见 [进度范围](docs/progress-checkpoint-2026-10-01.md) 和 [Word 验收矩阵](docs/genoffice-word-acceptance-matrix.md)。

原有 Onyx 工作流保存在 `.github/upstream-workflows/`。其中包含上游发布和云服务任务，需适配后再启用。

## 许可证与来源

保留 Onyx 的版权和许可证。社区代码使用 MIT；`ee` 目录保留 Onyx Enterprise License，详见 [LICENSE](LICENSE)。

Presenton 使用 Apache-2.0，固定版本、修改覆盖文件和许可证位于 [integrations/presenton](integrations/presenton)。

OrgMesh 与 Glean 没有隶属关系。
