from scripts.export_openapi import OPENAPI_PATH, export_openapi


def test_standalone_openapi_snapshot_is_current() -> None:
    assert OPENAPI_PATH.exists()
    assert export_openapi(check=True) is False
