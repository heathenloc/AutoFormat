"""Standalone HTTP API entrypoint; host adapters remain a later boundary."""

from brief_parser.api.app import create_app

__all__ = ["create_app"]
