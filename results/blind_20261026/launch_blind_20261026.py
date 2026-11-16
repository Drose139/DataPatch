"""One baseline setup and one paid Agent run. No retry or result-driven edits."""
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

from datapatch.config import Settings
from datapatch.evaluation import source_digest
from datapatch.workspace import Workspace

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_DIR = ROOT / 'artifacts/protocols'
RUN_PROTOCOL = PROTOCOL_DIR / 'unseen_blind_run_20261026.json'
CORE = '49f2808e761b575163949c57e09a3b29be75a1b7aca39134269336990dad4beb'
assert not RUN_PROTOCOL.exists(), 'This one-shot trial has already been launched; do not retry'
assert source_digest() == CORE, 'The tested core must remain v4.4'
settings = Settings.load()
assert settings.model == 'deepseek-flash' and settings.api_key


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


setup_path = PROTOCOL_DIR / 'unseen_blind_setup_20261026.json'
setup = json.loads(setup_path.read_text(encoding='utf-8'))
case = Path(setup['case'])
assert setup['status'] == 'awaiting_generated_artifact_cleanup'
assert all(not Path(path).exists() for path in setup['stale_artifacts_cleanup_pending'])
adapter = load_module('blind_adapter', ROOT / 'integrations/harbor_agent.py')
meta = json.loads((case / 'native-case.json').read_text(encoding='utf-8'))
target = case / 'project' / meta['model']
assert digest(target) == setup['initial_target_sha256']
assert digest(case / 'instruction.md') == setup['original_instruction_sha256']
workspace = Workspace(case, project_dir=case / 'project', database_path=case / 'database/retail.duckdb', duckdb_timezone='UTC')
workspace.default_select = target.stem
baseline = workspace.run_dbt('run')
baseline = adapter.verify_target_build(baseline, workspace.project_dir, meta['model'])
baseline_path = PROTOCOL_DIR / 'unseen_blind_initial_bug_run_20261026.json'
baseline_path.write_text(json.dumps(baseline, indent=2) + '\n', encoding='utf-8')
assert digest(target) == setup['initial_target_sha256']
assert not list((case / 'checks').glob('*')) and not (case / 'solver-instruction.md').exists()
assert not list(case.rglob('test_outputs*.py')) and not list(case.rglob('solve.sh'))
assert (case / 'database/retail.duckdb').stat().st_nlink == 1
snapshot = ROOT / 'artifacts/evaluations/unseen_blind_20261026_source.zip'
frozen = load_module('blind_freezer', ROOT / 'scripts/freeze_source.py').freeze(snapshot)
assert frozen['core_source_sha256'] == CORE
helpers = [ROOT / relative for relative in (
    'integrations/harbor_agent.py', 'integrations/public_packages.py',
    'integrations/run_public_pytest.py', 'scripts/fetch_public_benchmark.py', 'scripts/freeze_source.py',
    'artifacts/protocols/prepare_blind_20261026.py',
    'artifacts/protocols/clean_blind_generated_20261026.ps1',
    'artifacts/protocols/launch_blind_20261026.py')]
record = {
    'created_at': datetime.now(timezone.utc).isoformat(), 'status': 'single_trial_started',
    'task_id': meta['task_id'], 'case': str(case), 'model': settings.model,
    'mode': 'verified', 'planned_trials': 1, 'max_model_calls': 10, 'budget_usd': 0.08,
    'source': frozen, 'helper_sha256': {str(path.relative_to(ROOT)): digest(path) for path in helpers},
    'selection_sha256': digest(PROTOCOL_DIR / 'unseen_blind_selection_20261026.json'),
    'setup_sha256': digest(setup_path), 'original_bug_baseline': str(baseline_path),
    'baseline_target_build_success': baseline['success'],
    'initial_target_sha256': digest(target), 'instruction_sha256': digest(case / 'instruction.md'),
    'runtime_timezone': 'UTC', 'extra_business_contracts': False, 'hidden_feedback_to_agent': False,
    'reference_solutions_used': False, 'verifier_downloaded_before_agent': False,
    'retry_rule': 'No second model run, no task substitution, no retry on HTTP failure',
    'scope': 'Development-unseen task in a known public project; not a pretraining-unseen or cross-project claim'
}
# Exclusive durable receipt blocks a second paid run even if the first process dies.
with RUN_PROTOCOL.open('x', encoding='utf-8') as output:
    output.write(json.dumps(record, indent=2) + '\n')
print('Frozen one-shot protocol; starting Flash (maximum 10 calls, estimated USD 0.08)', flush=True)
result = adapter.run_native_case(case, ROOT / 'external/native-results', mode='verified', max_steps=10,
                                 budget_usd=0.08, source_snapshot=snapshot, contracts_dir=None)
record['status'] = 'agent_stopped'
record['agent_stopped_at'] = datetime.now(timezone.utc).isoformat()
record['agent_report'] = result['report']
record['metrics'] = result['result'].get('metrics', {})
RUN_PROTOCOL.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'report': result['report'], 'metrics': record['metrics'],
                  'stop_reason': result['result'].get('stop_reason'),
                  'error_type': result['result'].get('error_type')}), flush=True)
