# EasyFormat 开发约束

在本项目开发前，先阅读 `EasyFormat_Technical_Architecture.md`、`EasyFormat_PRD.md` 和 `BriefParsing_EasyFormat.md`。后续已确认的架构决策以 `EasyFormat_Technical_Architecture.md` 为准。

## Brief Parsing 副本

- 复用代码位于本项目的 `modules/brief_parsing/`；复制来源和文件哈希见该目录的 `SOURCE_SNAPSHOT.json`。
- `E:\Brief Parsing` 原项目目录只可作为只读参考。不得在那里编辑、格式化、清理、安装依赖、运行会写入该目录的命令、提交或生成构建产物。
- 所有学术论文领域包、解析器、校验器、测试和依赖变更都在本项目的复制版中完成。禁止通过 `PYTHONPATH` 或可编辑安装直接依赖原项目目录。
- 如需吸收来源项目后续变更，先记录差异，再显式移植到复制版，并运行通用回归和 EasyFormat 集成测试；不要覆盖复制版。

## 实施原则

- 论文原稿 V0 和已发布的历史版本不可原地修改；每次实际编辑从选定父版本创建新 DOCX、报告与预览。
- 编辑器接收经确认的类型化规则，不直接执行模型输出或用户原话。反馈入口可以解析自由文本，但不确定、冲突或定位不唯一时先询问用户。
- 不得把模板观察值当成学校明文要求；不修改论文语义内容，不编造图表来源或参考文献。
- 只在 `E:\EasyFormat` 内创建或修改项目文件。测试与运行产物应写到项目的忽略目录或操作系统用户数据目录。

