"""One-off isolation setup. Never reads task/test/solution bodies for reasoning."""
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
CASE = Path('D:/DataPatch-work/unseen-carrier-20261026-001')
PROTOCOL = ROOT / 'artifacts/protocols/unseen_blind_setup_20261026.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quoted(value):
    return '"' + value.replace('"', '""') + '"'


def save(value):
    PROTOCOL.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


selection_path = ROOT / 'artifacts/protocols/unseen_blind_selection_20261026.json'
selection = json.loads(selection_path.read_text(encoding='utf-8'))
spec = importlib.util.spec_from_file_location('blind_adapter', ROOT / 'integrations/harbor_agent.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
task = selection['selected_id']
assert task == 'dbt-carrier-delivery-performance'
assert not PROTOCOL.exists(), 'Do not overwrite prior blind setup evidence'
existing_meta = CASE / 'native-case.json'
if existing_meta.exists():
    # Resume this same completed free preparation after a Windows-path metadata
    # mismatch. No solver invocation or SQL edit has occurred.
    meta = json.loads(existing_meta.read_text(encoding='utf-8'))
    assert meta['task_id'] == task and meta['initialized']
    assert json.loads((CASE / 'preparation/base_build.json').read_text(encoding='utf-8'))['returncode'] == 0
else:
    meta = adapter.prepare_native_case(
        ROOT / 'external/data-eng-bench-blind-20261026', CASE, task,
        duckdb_timezone='UTC', packages_cache=ROOT / 'external/package-cache/dbt_utils-1.3.3')
project = CASE / 'project'
manifest = json.loads((project / 'target/manifest.json').read_text(encoding='utf-8'))
nodes = [node for node in manifest['nodes'].values()
         if node.get('resource_type') == 'model'
         and node.get('original_file_path', '').replace('\\', '/') == meta['model']]
assert len(nodes) == 1
# Extract identity only: do not expose baseline raw_code/compiled_code to the solver.
node = nodes[0]
relation = {key: node[key] for key in ('database', 'schema', 'alias')}
relation['materialized'] = node['config']['materialized']
del node, nodes, manifest
with duckdb.connect(meta['database_path']) as connection:
    rows = connection.execute(
        'SELECT table_catalog,table_schema,table_name,table_type FROM information_schema.tables '
        'WHERE table_catalog=? AND table_schema=? AND table_name=?',
        [relation['database'], relation['schema'], relation['alias']]).fetchall()
    assert len(rows) == 1
    kind = 'VIEW' if rows[0][3] == 'VIEW' else 'TABLE'
    sql = 'DROP ' + kind + ' ' + '.'.join(quoted(relation[key]) for key in ('database', 'schema', 'alias'))
    connection.execute(sql)
    after = connection.execute(
        'SELECT count(*) FROM information_schema.tables WHERE table_catalog=? AND table_schema=? AND table_name=?',
        [relation['database'], relation['schema'], relation['alias']]).fetchone()[0]
    assert after == 0
assert not list((CASE / 'checks').glob('*')) and not (CASE / 'solver-instruction.md').exists()
overlay = ROOT / 'external/data-eng-bench-blind-20261026' / selection['overlay_path']
target = project / meta['model']
assert digest(overlay) == digest(target)
record = {
    'created_at': datetime.now(timezone.utc).isoformat(), 'task_id': task, 'case': str(CASE),
    'selection_sha256': digest(selection_path), 'original_instruction_only': True,
    'extra_contracts': False, 'verifier_downloaded_before_agent': False,
    'reference_solution_used': False, 'independent_case_database_copy': True,
    'preparation_runtime': meta, 'baseline_relation': relation,
    'baseline_relation_before': rows, 'baseline_relation_after_drop_count': after,
    'drop_command': sql, 'initial_target_sha256': digest(target),
    'original_instruction_sha256': digest(CASE / 'instruction.md'),
    'stale_artifacts_cleanup_pending': [str(project / 'target'), str(project / 'logs')],
    'setup_script_sha256': digest(Path(__file__)), 'status': 'awaiting_generated_artifact_cleanup'
}
save(record)
print(json.dumps({'protocol': str(PROTOCOL), 'case': str(CASE), 'relation': relation,
                  'initial_target_sha256': record['initial_target_sha256']}))
