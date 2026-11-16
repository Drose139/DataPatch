import json
from pathlib import Path

import duckdb

from datapatch.context import MAX_CONTEXT_CHARS, build_task_context
from datapatch.workspace import Workspace


def _model(root: Path, path: str, sql: str) -> Path:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(sql, encoding="utf-8")
    return target


def test_explicit_sql_path_focuses_target_and_relevant_schema(tmp_path):
    sql = "select customer_id, grand_total from {{ ref('int_sales__orders_enriched') }}"
    _model(tmp_path, "models/marts/customer/rpt_customer_metrics.sql", sql)
    _model(tmp_path, "models/intermediate/int_sales__orders_enriched.sql", "select * from {{ ref('stg_orders') }}")
    _model(tmp_path, "models/staging/stg_orders.sql", "select 1 as customer_id")
    with duckdb.connect(str(tmp_path / "warehouse.duckdb")) as db:
        db.execute("create table int_sales__orders_enriched(customer_id varchar,grand_total bigint)")
        db.execute("create table unrelated_alphabetical_first(irrelevant varchar)")
    context = build_task_context(Workspace(tmp_path), "Fix /app/dbt_models_duckdb/models/marts/customer/rpt_customer_metrics.sql; investigate invalid customer metrics.")
    assert context["target"]["path"] == "models/marts/customer/rpt_customer_metrics.sql"
    assert context["target"]["sql"] == sql
    assert context["target"]["identified_by"] == "explicit SQL path in instruction"
    assert any(node["model"] == "int_sales__orders_enriched" for node in context["lineage"]["nodes"])
    assert "main.int_sales__orders_enriched" in context["schema"]["tables"]
    assert "main.unrelated_alphabetical_first" not in context["schema"]["tables"]


def test_budget_truncates_readme_and_schema_before_target_sql(tmp_path):
    sql = "-- target must remain complete\n" + "-- business logic comment\n" * 180 + "select * from {{ ref('customer_source') }}"
    _model(tmp_path, "models/customer_report.sql", sql)
    (tmp_path / "README.md").write_text("Business documentation with escaped quotes \\\" and unicode 客户。\n" * 5000, encoding="utf-8")
    with duckdb.connect(str(tmp_path / "warehouse.duckdb")) as db:
        for table in range(15):
            columns = ",".join(f"long_customer_business_attribute_{n} varchar" for n in range(80))
            db.execute(f"create table customer_source_{table}({columns})")
    context = build_task_context(Workspace(tmp_path), "Repair customer_report customer revenue business logic", focus_model="customer_report")
    assert len(json.dumps(context, ensure_ascii=False)) <= MAX_CONTEXT_CHARS
    assert context["target"]["sql"] == sql
    assert not context["target"]["truncated"]
    assert context["readme"]["truncated"]
    assert context["metadata"]["truncated_sections"]


def test_no_reference_or_evaluator_reads_and_small_missing_workspace_fallback(tmp_path, monkeypatch):
    import datapatch.context as module
    _model(tmp_path, "models/report.sql", "select 1 as amount")
    for folder in ("solution", "tests", "evaluator", "models/tests"):
        _model(tmp_path, f"{folder}/answer.sql", "SECRET_REFERENCE_ANSWER")
    original = module._read_public_text
    touched = []
    def audited(path, root, limit=200_000):
        touched.append(path.relative_to(root).as_posix())
        assert not set(path.relative_to(root).parts) & {"solution", "tests", "evaluator"}
        return original(path, root, limit)
    monkeypatch.setattr(module, "_read_public_text", audited)
    context = build_task_context(Workspace(tmp_path), "Repair models/report.sql; do not inspect solution/answer.sql or tests/answer.sql")
    assert "SECRET_REFERENCE_ANSWER" not in json.dumps(context)
    assert touched == ["models/report.sql"]
    class MissingWorkspace:
        root = tmp_path / "missing"
        project_dir = root
        database_path = root / "warehouse.duckdb"
        def list_files(self):
            return {"files": ["models/report.sql", "tests/answer.sql"]}
    fallback = build_task_context(MissingWorkspace(), "Investigate finance totals")
    assert fallback["target"] is None
    assert fallback["candidate_files"] == ["models/report.sql"]
    assert len(json.dumps(fallback)) < 3000
def test_readme_is_retained_when_short_ticket_does_not_identify_a_model(tmp_path):
    from datapatch.context import build_task_context
    (tmp_path / "models").mkdir()
    (tmp_path / "models/report.sql").write_text("select 1", encoding="utf-8")
    contract = "Exactly one row for every refund, including cancelled orders."
    (tmp_path / "README.md").write_text(contract, encoding="utf-8")
    context = build_task_context(Workspace(tmp_path), "Repair incorrect coverage")
    assert context["metadata"]["target_found"] is False
    assert context["readme"]["content"] == contract


def test_path_input_points_to_project_not_drive_anchor(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models/report.sql").write_text("select 1", encoding="utf-8")
    (tmp_path / "README.md").write_text("Preserve all records", encoding="utf-8")
    context = build_task_context(tmp_path, "Repair models/report.sql")
    assert context["target"]["path"] == "models/report.sql"
    assert context["readme"]["content"] == "Preserve all records"


def test_new_target_preloads_distinct_relevant_inputs_not_an_existing_input_as_target(tmp_path):
    inputs = {
        "models/staging/catalog/stg_catalog__products.sql": "select product_id from {{ source('catalog', 'products') }}",
        "models/staging/catalog/stg_catalog__product_variants.sql": "select variant_id, product_id from {{ source('catalog', 'variants') }}",
        "models/staging/sales/stg_sales__orders.sql": "select order_id, status from {{ source('sales', 'orders') }}",
        "models/staging/sales/stg_sales__order_lines.sql": "select order_id, variant_id from {{ source('sales', 'order_lines') }}",
        "models/staging/finance/stg_ledger.sql": "select 'UNRELATED_FINANCE' as account",
        "models/staging/reference/stg_tax_lines.sql": "select 'UNRELATED_LINE' as tax",
        "models/staging/web/stg_cart_items.sql": "select 'UNRELATED_ITEM' as cart",
    }
    for path, sql in inputs.items():
        _model(tmp_path, path, sql)
    (tmp_path / "README.md").write_text("All products remain in the output.", encoding="utf-8")
    instruction = """Create a model called `fct_catalog_metrics` at models/marts/catalog/fct_catalog_metrics.sql.
## Requirements
Explore staging tables for products, variants, orders, and order line items.
The existing stg_sales__orders provides the order status. Include all products.
"""
    with duckdb.connect(str(tmp_path / "warehouse.duckdb")) as db:
        db.execute("create table products(product_id int)")
        db.execute("create table orders(order_id int, status varchar)")
        db.execute("create table unrelated_ledger(account varchar)")
    context = build_task_context(tmp_path, instruction)
    assert context["target"] is None
    assert context["requested_target"]["path"] == "models/marts/catalog/fct_catalog_metrics.sql"
    assert context["metadata"]["task_mode"] == "create"
    selected = {source["model"] for source in context["candidate_sources"]}
    assert selected == {"stg_catalog__products", "stg_catalog__product_variants", "stg_sales__orders", "stg_sales__order_lines"}
    assert all(source["sql"] and source["upstream"] for source in context["candidate_sources"])
    assert "UNRELATED" not in json.dumps(context)
    assert "main.products" in context["schema"]["tables"]
    assert "main.unrelated_ledger" not in context["schema"]["tables"]
    assert "create" in context["guidance"][0]
    assert context["readme"]["content"] == "All products remain in the output."


def test_new_target_shared_budget_bounds_each_source_and_preserves_readme(tmp_path):
    instruction = "Create a model called fct_business_summary at models/marts/fct_business_summary.sql.\n## Requirements\nExplore tables for customers, products, variants, orders, payments, and refunds."
    for entity in ("customers", "products", "variants", "orders", "payments", "refunds"):
        _model(tmp_path, f"models/staging/stg_{entity}.sql", "-- public source \\\" quoted\\n" * 2000 + f"\nselect * from {{{{ source('raw', '{entity}') }}}}")
    contract = "Preserve the documented grain. " * 400
    (tmp_path / "README.md").write_text(contract, encoding="utf-8")
    context = build_task_context(tmp_path, instruction)
    assert len(json.dumps(context, ensure_ascii=False)) <= MAX_CONTEXT_CHARS
    assert context["readme"]["content"] == contract[:8000]
    assert context["metadata"]["candidate_sources_selected"] == 6
    assert len(context["candidate_sources"]) < 6
    assert all(len(source["sql"]) <= 3500 and source["truncated"] for source in context["candidate_sources"])
    assert "candidate_sources" in context["metadata"]["truncated_sections"]
    assert "candidate_source_sql" in context["metadata"]["truncated_sections"]


def test_new_target_never_reads_reference_assets(tmp_path, monkeypatch):
    import datapatch.context as module
    _model(tmp_path, "models/staging/stg_products.sql", "select 1 as product_id")
    for folder in ("solution", "tests", "checks", "models/solution", "models/checks"):
        _model(tmp_path, f"{folder}/stg_products.sql", "SECRET_REFERENCE_ANSWER")
    touched = []
    original = module._read_public_text
    def audited(path, root, limit=200_000):
        touched.append(path.relative_to(root).as_posix())
        assert not set(path.relative_to(root).parts) & {"solution", "tests", "checks"}
        return original(path, root, limit)
    monkeypatch.setattr(module, "_read_public_text", audited)
    context = build_task_context(tmp_path, "Create a model called fct_products. Explore tables for products.")
    assert "SECRET_REFERENCE_ANSWER" not in json.dumps(context)
    assert touched == ["models/staging/stg_products.sql"]


def test_new_target_missing_fake_workspace_stays_bounded_without_global_tools(tmp_path):
    class MissingWorkspace:
        root = tmp_path / "missing"
        project_dir = root
        database_path = root / "warehouse.duckdb"
        def list_files(self):
            return {"files": [f"models/staging/stg_products_{n}.sql" for n in range(2500)] + ["tests/answer.sql"]}
        def search_schema(self, *args, **kwargs):
            raise AssertionError("Do not request global schema in a missing workspace")
        def get_lineage(self, *args, **kwargs):
            raise AssertionError("Do not request global lineage in a missing workspace")
    context = build_task_context(MissingWorkspace(), "Create a model called fct_products. Explore tables for products.", "fct_products")
    assert context["candidate_sources"] == []
    assert len(context["candidate_files"]) == 12
    assert context["target"] is None
    assert len(json.dumps(context, ensure_ascii=False)) < 5000


def test_new_target_prefers_directory_namespace_over_short_alias_on_relevance_tie(tmp_path):
    for entity in ("payments", "shipments"):
        _model(tmp_path, f"models/staging/{entity}/stg_{entity}.sql", "select 'SHORT_ALIAS' as value")
        _model(tmp_path, f"models/staging/{entity}/stg_{entity}__{entity}.sql", f"select * from {{{{ source('{entity}', '{entity}') }}}}")
    # A namespace alone cannot override better business relevance, and a
    # namespace copied into an unrelated directory is not a source-group hint.
    _model(tmp_path, "models/staging/other/stg_payments__payments_copy.sql", "select 'UNRELATED_COPY' as value")
    _model(tmp_path, "models/staging/ledger/stg_ledger__entries.sql", "select 'UNRELATED_LEDGER' as value")
    context = build_task_context(tmp_path, "Create a model called fct_activity_metrics. Explore staging tables for payments and shipments.")
    assert {source["model"] for source in context["candidate_sources"]} == {"stg_payments__payments", "stg_shipments__shipments"}
    assert all(source["namespace_matches_directory"] for source in context["candidate_sources"])
    assert "SHORT_ALIAS" not in json.dumps(context)
    assert "UNRELATED" not in json.dumps(context)


def test_selected_input_relationships_expose_nonnull_orphans_and_complete_alternative(tmp_path):
    for folder, name in (("assets", "stg_assets__assets"), ("assets", "stg_assets__options"), ("ops", "stg_ops__lines")):
        _model(tmp_path, f"models/staging/{folder}/{name}.sql", "select 1")
    with duckdb.connect(str(tmp_path / "warehouse.duckdb")) as db:
        db.execute("create table stg_assets__assets(asset_id varchar)")
        db.execute("insert into stg_assets__assets values ('A'),('B'),('C')")
        db.execute("create table stg_assets__options(option_id varchar,asset_id varchar)")
        db.execute("insert into stg_assets__options values ('O1','A'),('O2','A'),('O3','B'),('O4','C')")
        db.execute("create table stg_ops__lines(line_id integer,option_id varchar,asset_id varchar)")
        db.execute("insert into stg_ops__lines values (1,'O1','A'),(2,'O1','ghost1'),(3,'O2','A'),(4,'O3','B'),(5,'O4','ghost2'),(6,NULL,NULL)")
        db.execute("create table unrelated_assets(asset_id varchar)")
        db.execute("insert into unrelated_assets values ('UNRELATED_SECRET')")
    context = build_task_context(tmp_path, "Create a model called fct_asset_metrics. Explore staging tables for assets, options, and lines.")
    evidence = context["relationship_checks"]
    edges = {(row["child"]["table"], row["parent"]["table"], row["child"]["column"]): row for row in evidence["relationships"]}
    bad = edges[("main.stg_ops__lines", "main.stg_assets__assets", "asset_id")]
    assert bad["unmatched_non_null_rows"] == bad["unmatched_non_null_keys"] == 2
    assert bad["child_null_rows"] == 1
    assert bad["matched_non_null_rows"] == 3
    assert {sample["key"] for sample in bad["unmatched_examples"]} == {"ghost1", "ghost2"}
    assert edges[("main.stg_ops__lines", "main.stg_assets__options", "option_id")]["unmatched_non_null_rows"] == 0
    assert edges[("main.stg_assets__options", "main.stg_assets__assets", "asset_id")]["unmatched_non_null_rows"] == 0
    assert "UNRELATED_SECRET" not in json.dumps(context)
    assert all("unrelated" not in profile["table"] for profile in evidence["key_profiles"])
    assert "not an authoritative" in evidence["note"]
    assert len(json.dumps(context, ensure_ascii=False)) <= MAX_CONTEXT_CHARS


def test_duplicate_nonnull_parent_key_is_not_claimed_as_many_to_one(tmp_path):
    from datapatch.context import _relationship_checks
    database = tmp_path / "warehouse.duckdb"
    with duckdb.connect(str(database)) as db:
        for relation in ("stg_left", "stg_right"):
            db.execute(f"create table {relation}(entity_id integer)")
            db.execute(f"insert into {relation} values (1),(1),(NULL)")
    evidence = _relationship_checks(database, ["stg_left", "stg_right"])
    assert evidence["available"]
    assert not evidence["relationships"]
    assert all(profile["null_rows"] == 1 and profile["duplicate_key_groups"] == 1 and profile["duplicate_excess_rows"] == 1 for profile in evidence["key_profiles"])


def test_relationship_query_and_output_caps_are_fixed_and_missing_db_is_not_created(tmp_path):
    from datapatch.context import _relationship_checks
    database = tmp_path / "warehouse.duckdb"
    missing = _relationship_checks(database, ["stg_left", "stg_right"])
    assert missing["queries_executed"] == 0
    assert not database.exists()
    with duckdb.connect(str(database)) as db:
        columns = ','.join(f'field_{n}_id integer' for n in range(8))
        for index in range(8):
            db.execute(f"create table stg_{index}({columns})")
            values = (1, 2) if index == 0 else (1, 1, 3, 4, 5, 6, 7)
            for value in values:
                db.execute(f"insert into stg_{index} values ({','.join([str(value)] * 8)})")
    evidence = _relationship_checks(database, [f"stg_{index}" for index in range(8)])
    assert evidence["truncated"]
    assert len(evidence["key_profiles"]) <= 12
    assert len(evidence["relationships"]) <= 6
    assert evidence["queries_executed"] <= evidence["limits"]["queries"] == 19
    assert all(len(row["unmatched_examples"]) <= 3 for row in evidence["relationships"])
    assert all(len(sample["key"]) <= 120 for row in evidence["relationships"] for sample in row["unmatched_examples"])
    assert all(profile["table"] not in {"main.stg_6", "main.stg_7"} for profile in evidence["key_profiles"])


def test_relationship_evidence_shares_context_budget_without_losing_target_or_readme(tmp_path, monkeypatch):
    import datapatch.context as module
    monkeypatch.setattr(module, "MAX_CONTEXT_CHARS", 5000)
    sql = "-- preserve this target expression\n" * 60 + "select * from {{ ref('stg_lines') }} join {{ ref('stg_assets') }} using(asset_id)"
    _model(tmp_path, "models/report.sql", sql)
    _model(tmp_path, "models/staging/stg_lines.sql", "select 1 as asset_id")
    _model(tmp_path, "models/staging/stg_assets.sql", "select 1 as asset_id")
    contract = "Preserve all documented source facts. " * 100
    (tmp_path / "README.md").write_text(contract, encoding="utf-8")
    with duckdb.connect(str(tmp_path / "warehouse.duckdb")) as db:
        db.execute("create table stg_assets(asset_id varchar)")
        db.execute("insert into stg_assets values ('A')")
        db.execute("create table stg_lines(asset_id varchar)")
        db.execute("insert into stg_lines values ('A'),('A'),('missing')")
    context = build_task_context(tmp_path, "Repair models/report.sql")
    assert len(json.dumps(context, ensure_ascii=False)) <= 5000
    assert context["target"]["sql"] == sql
    assert context["readme"]["content"] and contract.startswith(context["readme"]["content"])
    assert context["relationship_checks"]["truncated"]
    assert "relationship_checks" in context["metadata"]["truncated_sections"]

