"""Run unchanged public pytest assertions under an explicitly declared UTC session.

dbt subprocesses read the corresponding settings.TimeZone in profiles.yml.
Connections opened by the original Python verifier receive the same setting.
No SQL, assertion, source data, or pytest exit status is rewritten.
"""
from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duckdb-timezone", choices=("UTC",), required=True)
    _, pytest_arguments = parser.parse_known_args(argv)
    if not pytest_arguments:
        parser.error("Provide the original pytest arguments and test path")

    import duckdb
    import pytest

    original_connect = duckdb.connect

    def utc_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        try:
            connection.execute("SET TimeZone = 'UTC'")
        except Exception:
            connection.close()
            raise
        return connection

    duckdb.connect = utc_connect
    try:
        return int(pytest.main(pytest_arguments))
    finally:
        duckdb.connect = original_connect


if __name__ == "__main__":
    raise SystemExit(main())
