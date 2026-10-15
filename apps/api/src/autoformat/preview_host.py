"""Standalone local preview host for already-published tasks.

Editing is enabled only with an explicitly pinned editor and renderer.
"""
from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path

from .local_api import bind_local_api
from .rule_snapshots import RuleSnapshotStore
from .version_store import VersionStore
from .selection_indexes import SelectionIndexes
from .workflow import DotnetEditor
from .preview import LibreOfficeRenderer


def main() -> None:
    parser = argparse.ArgumentParser(description="Open an existing AutoFormat task in the local preview UI.")
    parser.add_argument("--store", type=Path, required=True, help="Existing AutoFormat storage root")
    parser.add_argument("--task", required=True, help="Task ID from the initial publication response")
    parser.add_argument("--web-dist", type=Path, required=True, help="Built apps/web/dist directory")
    parser.add_argument("--node", type=Path, help="Trusted Node executable for local PDF text indexing")
    parser.add_argument("--selection-dll", type=Path, help="Built academic editor DLL containing the read-only index")
    parser.add_argument("--editor-sha256", help="Pinned editor DLL SHA-256; enables feedback editing with renderer options")
    parser.add_argument("--soffice", type=Path, help="Trusted LibreOffice executable for new previews")
    parser.add_argument("--soffice-sha256", help="Pinned LibreOffice executable SHA-256")
    parser.add_argument("--font-fingerprint", help="Fingerprint of the configured rendering fonts")
    options = parser.parse_args()
    # Fail before creating a new empty store or launching a browser.
    if not (options.store / "versions.sqlite3").is_file():
        parser.error("The existing version store was not found.")
    store = VersionStore(options.store)
    store.list_versions(options.task)
    root = Path(__file__).resolve().parents[4]
    try:
        indexes = SelectionIndexes.from_project(root, node=options.node, editor_dll=options.selection_dll)
    except (OSError, ValueError):
        indexes = None
        print("Selection indexing is unavailable. Build the .NET engine and install apps/web dependencies to enable it.")

    def unavailable_renderer(_: Path):
        raise RuntimeError("This host only reads existing previews.")

    editor, renderer_factory = None, unavailable_renderer
    execution_options = [options.editor_sha256, options.soffice, options.soffice_sha256, options.font_fingerprint]
    if any(execution_options):
        if not all(execution_options) or indexes is None:
            parser.error("Feedback editing requires indexes, --editor-sha256, --soffice, --soffice-sha256 and --font-fingerprint.")
        editor = DotnetEditor(dotnet_path=indexes.dotnet, editor_dll=indexes.editor_dll,
                              expected_editor_sha256=options.editor_sha256)
        def configured_renderer(work):
            return LibreOfficeRenderer(soffice_path=options.soffice,
                expected_soffice_sha256=options.soffice_sha256, data_root=work)
        configured_renderer(store.root)
        renderer_factory = configured_renderer

    host = bind_local_api(
        store=store, snapshots=RuleSnapshotStore(store), indexer=None, editor=editor,
        renderer_factory=renderer_factory, font_fingerprint=options.font_fingerprint or "preview-host",
        web_dist_dir=options.web_dist,
        selection_indexes=indexes,
    )
    # Credentials live only in the host and the ephemeral fragment; no URL is
    # printed or stored. The reserved listening socket is already accepting.
    launch = threading.Timer(0.5, webbrowser.open, args=(host.ui_url(options.task),))
    launch.daemon = True
    launch.start()
    print("AutoFormat preview is running locally. Close with Ctrl+C.")
    try:
        host.serve()
    finally:
        launch.cancel()
        host.close()


if __name__ == "__main__":
    main()
