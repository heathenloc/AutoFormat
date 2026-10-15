# AutoFormat Windows 测试分发包

此测试包提供一个本地入口，使用系统浏览器完成双文件上传、内置 Brief 解析、编辑前确认、初稿、预览微调、版本与历史分支。它不是独立 EXE 安装器；目标电脑仍须安装 Python 3.12（64 位）、Node.js 24、.NET 10 运行时和 LibreOffice。

包内包含 AutoFormat、项目内 Brief Parsing 副本、Python 运行依赖、DOCX 编辑器、PDF.js 与网页资源。模型密钥、论文、任务存储、虚拟环境和 LibreOffice 本体不打包。依赖的许可证／包元数据随对应库保留。

1. 将测试包解压到一个新目录，保持内部结构。复制 `config.example.json` 到包外的用户配置目录，填写 Node、.NET、LibreOffice 的路径及 LibreOffice 的 SHA-256。构建包已填写所带编辑器的相对路径与 SHA-256；如果更换编辑器，须核对并更新两者。
2. 使用 `Get-FileHash -Algorithm SHA256 -LiteralPath <文件路径>` 获取已核对组件的哈希。`font_files` 为空时读取 Windows 系统／当前用户字体；也可明确列出要记录的字体文件。启动会记录实际字体内容指纹，但不承诺学校要求的每种字体都已安装。
3. 在终端运行 `Start-AutoFormat.cmd --config <包外配置文件> --check --demo`，检查组件和资源，不创建任务存储。检查失败应按提示补齐依赖，不能跳过哈希校验。
4. 离线测试使用 `Start-AutoFormat.cmd --config <配置文件> --demo`。页面明确显示演示模式；它不调用云端模型，不能用于评价模型解析准确率。真实模式去掉 `--demo`，按项目内 Brief Parsing 配置设置 `BRIEF_PARSER_PROVIDER` 及相应密钥环境变量；密钥不要写入配置 JSON 或命令参数。未配置真实服务时不会自动退回演示模式。
5. 默认任务数据位于 `%LOCALAPPDATA%/AutoFormat/tasks`；如果尚无新目录且旧 `%LOCALAPPDATA%/EasyFormat/tasks/versions.sqlite3` 存在，继续读取旧任务目录（不搬移或重写历史文件）。退出再启动可从任务列表重开。可用 `--store <用户数据目录>` 指定另一存储。Ctrl+C 关闭本地主机；网页刷新会丢失内存会话，应从启动器重新打开。

若未注册 Python Launcher，可用 Python 3.12 可执行文件直接运行 `python -I -S -B launch.py --config <配置文件> --demo`。启动脚本使用隔离模式，忽略环境导入路径、用户站点与外部虚拟环境的依赖。`--no-browser` 仅用于自动化验证；启动器不会在日志中打印带会话令牌的 URL。

启动器先根据 `bundle-manifest.json` 校验包内文件、路径及哈希，再加载代码。此校验用于发现损坏或意外改动，不是数字签名或发布者认证。配置和运行数据应放在包外；新增未登记文件或修改包内资源会阻止启动。

当前整轮反馈仍要求规则快照 ready；首次忽略的学术要求仅支持报告查看，尚无发布后重新回答并应用的界面。目录／页码缓存刷新、与 Word 的逐页比对、独立安装器及 WebView2 外壳继续作为未完成验收项。

Windows 的解析器硬进程隔离目前需要 Linux 运行时，配置为 `production` 或强制 `process` 时启动检查会拒绝运行，不能隐式降级。此包用于当前开发／测试环境；真实云端解析尚需独立的凭据与代表性样本验收。
