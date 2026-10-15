"""Complete local application: intake, initial review, editing and task recovery."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import webbrowser

from pydantic import BaseModel, ConfigDict, Field
from brief_parser.bootstrap import build_service, build_document_ingestor, runtime_resource_dirs
from brief_parser.config import Settings
from brief_parser.errors import BriefParserError
import brief_parser
from .academic_intake import AcademicTaskIntake
from .local_api import bind_local_api
from .preview import LibreOfficeRenderer, PreviewError, _sha256
from .rule_snapshots import RuleSnapshotStore
from .selection_indexes import SelectionIndexes
from .version_store import VersionStore
from .workflow import DotnetEditor


class StartupError(ValueError):
    """A user-actionable diagnostic containing no dependency/configuration data."""


class DesktopConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: str = Field(pattern=r"^desktop-config/1\.0$")
    node: Path
    dotnet: Path
    editor_dll: Path
    editor_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    soffice: Path
    soffice_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    font_files: list[Path] = Field(default_factory=list, max_length=2048)


def font_inventory(config: DesktopConfig):
    paths = config.font_files
    if not paths:
        directories = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"]
        if os.environ.get("LOCALAPPDATA"):
            directories.append(Path(os.environ["LOCALAPPDATA"]) / "Microsoft/Windows/Fonts")
        paths = sorted({p.resolve() for directory in directories for p in directory.glob("*")
                        if p.suffix.lower() in {".ttf", ".ttc", ".otf"} and p.is_file()})
    if not paths or len(paths) > 2048:
        raise StartupError("未找到可读取的字体集合，请配置 font_files。")
    values = []
    for path in paths:
        with path.open("rb") as stream:
            if stream.read(4) not in {b"\x00\x01\x00\x00", b"ttcf", b"OTTO", b"true"}:
                raise StartupError("配置的字体文件无法识别。")
        values.append((path.name, _sha256(path)))
    return hashlib.sha256(json.dumps(sorted(values)).encode()).hexdigest(), len(values)


def parser_settings(demo: bool):
    if demo:
        return Settings(mode="integrated", environment="test", provider="fake", log_content=False)
    try:
        settings = Settings.from_env().model_copy(update={"mode": "integrated", "log_content": False, "otel_endpoint": None})
        if settings.provider == "fake": raise ValueError()
        return settings
    except ValueError as error:
        raise StartupError("请配置真实解析服务及密钥，或明确使用 --demo 离线演示；不会自动降级到演示服务。") from error


def load_config(root, path):
    config = DesktopConfig.model_validate_json(path.read_text(encoding="utf-8"))
    return config.model_copy(update={
        **{key: value if value.is_absolute() else root / value for key in ("node", "dotnet", "editor_dll", "soffice") if (value := getattr(config, key))},
        "font_files": [p if p.is_absolute() else root / p for p in config.font_files]})


def preflight(root: Path, config: DesktopConfig, *, demo=False):
    root = root.resolve(strict=True)
    if sys.version_info[:2] != (3, 12): raise StartupError("需要 Python 3.12。")
    if not Path(brief_parser.__file__).resolve().is_relative_to(root / "modules/brief_parsing/src"):
        raise StartupError("解析模块必须来自本应用内的复制版。")
    if not (root / "apps/web/dist/index.html").is_file(): raise StartupError("缺少构建后的网页资源。")
    def command(binary, *args):
        result = subprocess.run([str(binary.resolve(strict=True)), *args], capture_output=True,
            encoding="utf-8", errors="replace", timeout=20, check=False)
        if result.returncode: raise StartupError("运行组件无法启动。")
        return result.stdout.strip()
    node = command(config.node, "--version")
    if not node.startswith("v24."): raise StartupError("需要 Node.js 24。")
    runtimes = command(config.dotnet, "--list-runtimes")
    if not any(line.startswith("Microsoft.NETCore.App 10.") for line in runtimes.splitlines()):
        raise StartupError("需要 .NET 10 运行时。")
    if _sha256(config.editor_dll) != config.editor_sha256: raise StartupError("编辑器哈希与配置不一致。")
    indexes = SelectionIndexes(node=config.node, dotnet=config.dotnet,
        script=root / "scripts/pdf_text_index.mjs", editor_dll=config.editor_dll)
    renderer = LibreOfficeRenderer(soffice_path=config.soffice, expected_soffice_sha256=config.soffice_sha256, data_root=root)
    renderer_version = renderer._get_version()
    fingerprint, fonts = font_inventory(config)
    settings = parser_settings(demo)
    runtime_resource_dirs()
    build_document_ingestor(settings)
    return indexes, settings, fingerprint, {"status": "ready", "python": "3.12", "node": node,
        "dotnet": "10", "renderer": renderer_version, "font_count": fonts, "font_fingerprint": fingerprint,
        "mode": "demo" if demo else "configured"}


def create_application(root, config, store_path, *, demo=False):
    indexes, settings, fingerprint, diagnostics = preflight(root, config, demo=demo)
    service = build_service(settings)
    store = VersionStore(store_path)
    intake = AcademicTaskIntake(store=store, service=service)
    editor = DotnetEditor(dotnet_path=config.dotnet, editor_dll=config.editor_dll,
        expected_editor_sha256=config.editor_sha256)
    def renderer(work):
        return LibreOfficeRenderer(soffice_path=config.soffice,
            expected_soffice_sha256=config.soffice_sha256, data_root=work)
    host = bind_local_api(store=store, snapshots=RuleSnapshotStore(store), indexer=None, editor=editor,
        renderer_factory=renderer, font_fingerprint=fingerprint, intake=intake,
        selection_indexes=indexes, web_dist_dir=root / "apps/web/dist",
        application_mode="demo" if demo else "configured")
    return host, diagnostics


def default_store_path() -> Path:
    """Use the new application directory while reopening existing legacy tasks."""
    data_root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share")))
    current = data_root / "AutoFormat/tasks"
    legacy = data_root / "EasyFormat/tasks"
    if not current.exists() and (legacy / "versions.sqlite3").is_file():
        return legacy
    return current


def main():
    parser = argparse.ArgumentParser(description="启动 AutoFormat 完整本地应用。")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--store", type=Path, default=default_store_path())
    parser.add_argument("--demo", action="store_true", help="明确使用不调用云端模型的离线演示服务")
    parser.add_argument("--check", action="store_true", help="仅检查运行组件，不创建任务存储或启动服务器")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        config = load_config(args.root.resolve(), args.config)
    except (OSError, ValueError): parser.error("启动配置不存在或格式不正确；配置文件不应包含模型密钥。")
    try:
        if args.check:
            print(json.dumps(preflight(args.root, config, demo=args.demo)[-1], ensure_ascii=False)); return
        host, diagnostics = create_application(args.root, config, args.store, demo=args.demo)
    except StartupError as error:
        parser.error(str(error))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, PreviewError, BriefParserError):
        # Exception details from dependencies may include input/configuration.
        parser.error("运行组件检查失败，请核对配置、哈希和已安装的依赖。")
    launch = None
    if not args.no_browser:
        launch = threading.Timer(0.5, webbrowser.open, args=(host.ui_url(),)); launch.daemon = True; launch.start()
    print("AutoFormat 已在本地启动。关闭请按 Ctrl+C。" + (" 当前为离线演示模式。" if args.demo else ""))
    try: host.serve()
    except KeyboardInterrupt: pass
    finally:
        if launch: launch.cancel()
        host.close()


if __name__ == "__main__": main()
