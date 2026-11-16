"""Real child processes verify session setup without suppressing pytest failures."""
from pathlib import Path
import subprocess
import sys


LAUNCHER = Path(__file__).resolve().parents[1] / "integrations/run_public_pytest.py"


def test_launcher_sets_utc_for_each_real_duckdb_connection(tmp_path):
    test = tmp_path / "test_timezone.py"
    test.write_text("""
import duckdb
from duckdb import connect

def test_connections():
    first = duckdb.connect()
    assert first.execute("SELECT current_setting('TimeZone')").fetchone()[0] == 'UTC'
    first.execute("SET TimeZone='Asia/Shanghai'")
    second = connect()
    assert second.execute("SELECT current_setting('TimeZone')").fetchone()[0] == 'UTC'
    assert first.execute("SELECT current_setting('TimeZone')").fetchone()[0] == 'Asia/Shanghai'
    first.close()
    second.close()
""", encoding="utf-8")
    result = subprocess.run([sys.executable, str(LAUNCHER), "--duckdb-timezone", "UTC", "-q", str(test)],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_launcher_preserves_existing_business_assertion_failure(tmp_path):
    test = tmp_path / "test_business.py"
    test.write_text("def test_original_assertion():\n    assert False, 'business requirement remains violated'\n", encoding="utf-8")
    result = subprocess.run([sys.executable, str(LAUNCHER), "--duckdb-timezone", "UTC", "-q", str(test)],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 1
    assert "1 failed" in result.stdout
    assert "business requirement remains violated" in result.stdout
