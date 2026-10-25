# 技术演示用 GitHub Pages 发布

- `docs-presentation/` 是独立 HTML，直接作为 Pages artifact 上传，无需构建器或服务端。
- 工作流仅在该目录或工作流自身合入 `main` 时发布，避免 Server 变更触发演示站点部署。
- Pages 来源设置为 GitHub Actions；项目站点入口是 `https://johanchow.github.io/duxue/`。入口页使用相对链接，保留项目路径兼容性。
- 仅发布 `docs-presentation/`。以后往该目录放文件前须确认内容可公开。
