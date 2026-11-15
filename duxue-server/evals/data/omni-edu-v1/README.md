# Omni-Edu 本地评测批次

启动命令、评分与审核口径唯一维护在[本地评测设计](../../../../docs/technical/eval-offline.md#omni-edu-本地文件评测)。

- [manifest.json](manifest.json)：任务清单、学科、层级、执行目标、分组与文件哈希。
- [selection.json](selection.json)：确定性的制作配方及排除记录。
- [teaching-correctness/](teaching-correctness/)：解题和作答诊断。
- [guidance-logic/](guidance-logic/)：引导场景。
- [sources/](sources/)：所选上游原记录及合成改编、内容审阅依据；**不能直接当被测输入**。
- [assets.oss.json](assets.oss.json)：所选图片的阿里云OSS稳定引用（无凭据或临时签名）。
- [assets/](assets/)：所选原图的本地审计镜像；运行时引用OSS。
- [preparation/](preparation/)：模型辅助制作指令与审核说明。
- [validation.json](validation.json)：本地结构、配额和文件完整性校验；不是模型成绩或教师认证。

来源：[lhpku20010120/Omni-Edu](https://huggingface.co/datasets/lhpku20010120/Omni-Edu)，固定 revision `67b2607f7bd01185c2c47087aa7591e435b77ac6`。

本批诊断的学生尝试和辅导请求/脚本为合成改编，分类表示本项目的评测目标，不冒充上游原生师生记录。学段、参考与评分要求均为 `proposed`；高考同等要求标签不等于高考真题出处证明，也未经教师认证。

上游数据集声明为 `other` 许可，各组成来源和原始材料的使用条款继续适用。逐条来源见 `sources/` 中的 `dataset` / `source_license`；缺失许可字段不代表无限制使用。本目录是本地开发评测准备，不表示已获得重新发布或商业再分发授权。
