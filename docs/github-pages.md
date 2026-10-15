# GitHub 仓库与 Pages 发布

源码仓库：<https://github.com/heathenloc/AutoFormat>。

2026-10-15 发布状态：源码、现有历史和标签已上传到 `main`，仓库保持私有。启用 Pages 时 GitHub 返回 `422: Your current plan does not support GitHub Pages for this repository.`，因此网站尚未上线；首次工作流也会因 Pages 尚未启用而失败。需要先升级支持私有仓库 Pages 的套餐，或由仓库所有者决定公开仓库，再按下面的步骤启用并手动重跑，无需重建或重新上传网页。

## 展示入口

Pages 启用并部署成功后，入口为：

- 产品网页：<https://heathenloc.github.io/AutoFormat/>
- 交互原型：<https://heathenloc.github.io/AutoFormat/prototype/index.html#upload>
- 技术设计：<https://heathenloc.github.io/AutoFormat/workflow.html>
- AI 选型与调优：<https://heathenloc.github.io/AutoFormat/ai.html>
- 商业思考：<https://heathenloc.github.io/AutoFormat/business.html>

发布目录是 `site/`，包含 `prototype/` 子目录。页面使用相对链接，兼容仓库子路径；无需安装 Node 或构建前端。

GitHub Pages 提供静态展示。交互原型使用内置虚构材料，进度保存在浏览器本地，不上传或处理用户论文。真实应用位于 `apps/web`、`apps/api` 和 `services/docx_engine`，需要 Python、.NET、预览渲染器及本地宿主，不能通过 Pages 运行。

## 首次启用

1. 打开仓库 **Settings → Pages**。
2. 在 **Build and deployment → Source** 中选择 **GitHub Actions**。
3. 打开 **Actions → Deploy AutoFormat website → Run workflow**，选择 `main` 并运行。已存在的工作流是 `.github/workflows/pages.yml`，无需再创建模板工作流。
4. 等待部署任务成功，再访问以上入口。部署结果也会显示在仓库的 `github-pages` environment 中。

不能在 “Deploy from a branch” 中直接选择 `site/`：该模式只提供分支根目录和 `docs/`。本项目用 Actions 将完整 `site/` 上传为 Pages artifact，只发布网页资源。

仓库保持私有时，需要支持私有仓库 Pages 的套餐（个人账户为 GitHub Pro）。GitHub Free 的 Pages 需要公开仓库；如选择此方案，先自行确认整个源码和 Git 历史适合公开，再到 **Settings → General → Danger Zone → Change repository visibility** 修改可见性。发布配置不会自动改变仓库可见性。Pages 网站默认可公开访问，即使源码仓库保持私有。

## 后续更新

提交并推送 `site/` 或发布工作流的改动到 `main` 后会自动部署；其他代码改动不触发网页发布。也可随时从 Actions 手动运行。若部署失败，先查看运行日志，并核对 Pages Source、仓库套餐、Actions 是否启用，以及 `github-pages` environment 是否允许 `main` 部署。

官方说明：[配置发布来源](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)、[自定义工作流与权限](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)。
