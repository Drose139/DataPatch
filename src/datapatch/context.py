"""Task-focused public context; no reference solutions or evaluator reads."""
from __future__ import annotations

from collections import Counter, deque
import json
from pathlib import Path
import re
from threading import Timer
from typing import Any

MAX_CONTEXT_CHARS = 24_000
MAX_CANDIDATE_SOURCES = 6
MAX_SOURCE_SQL_CHARS = 3_500
MAX_RELATION_PROFILES = 12
MAX_RELATIONSHIPS = 6
MAX_RELATION_EXAMPLES = 3
MAX_RELATION_QUERY_SECONDS = 2.0
_FORBIDDEN = {"solution", "solutions", "test", "tests", "checks", "evaluator", "evaluation", "oracle", "ground_truth", "target", "logs", "dbt_packages", ".git"}
_STOP = set("the and this that with from into for are all not model models table tables columns column task fix broken correct output create return report project sql dbt duckdb snowflake app data using have should must existing available following query before after order run select instruction required requirements expected path file where when then else end null cast group join left inner full sum count desc asc case as on to is in by a an of it be at or per its use new only than will your name read build type true false information".split())


def _allowed(path: Path, root: Path) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return not any(part.lower() in _FORBIDDEN or part.startswith(".") for part in relative.parts)


def _read_public_text(path: Path, root: Path, limit: int = 200_000) -> str:
    if not _allowed(path, root):
        raise ValueError("Context source is outside the public project assets")
    with path.open(encoding="utf-8", errors="replace") as stream:
        return stream.read(limit)


def _refs(sql: str) -> list[str]:
    refs = re.findall(r"\bref\s*\(\s*['\"]([^'\"]+)['\"]", sql, re.I)
    refs += [table for _, table in re.findall(r"\bsource\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]", sql, re.I)]
    return list(dict.fromkeys(refs))


def _terms(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_]*", text.lower())
    words = [piece for word in words for piece in word.split("_") if len(piece) >= 4 and piece not in _STOP]
    return [word for word, _ in Counter(words).most_common(8)]


def _size(value: dict) -> int:
    return len(json.dumps(value, ensure_ascii=False))


def _name_terms(value: str) -> set[str]:
    """Small lexical normalization, without a domain-specific synonym list."""
    result = set()
    for word in re.findall(r"[a-zA-Z][a-zA-Z0-9]*", value.lower()):
        if word.endswith("ies") and len(word) > 4:
            word = word[:-3] + "y"
        elif word.endswith("s") and not word.endswith("ss") and len(word) > 4:
            word = word[:-1]
        if len(word) >= 4:
            result.add(word)
    return result


def _business_text(instruction: str) -> str:
    # Requirements outweigh repeated connection/profile boilerplate. This is
    # heading-based public-text selection, not a rule for a benchmark task.
    requirements = re.search(r"^#{1,6}\s+(?:business\s+)?requirements\b[^\n]*\n(.*?)(?=^#{1,6}\s|\Z)", instruction, re.I | re.M | re.S)
    return instruction if not requirements else instruction.split("\n##", 1)[0] + "\n" + requirements.group(1)


def _input_entities(instruction: str) -> list[set[str]]:
    phrases = re.findall(r"\b(?:tables?|models?|sources?|inputs?)\s+(?:for|including|such as)\s+([^.!\n]+)", _business_text(instruction), re.I)
    return [terms for phrase in phrases for entity in re.split(r",|\band\b", phrase) if (terms := _name_terms(entity))]


def _source_terms(instruction: str, requested: dict | None) -> dict[str, int]:
    text = _business_text(instruction)
    inputs = re.findall(r"\b(?:tables?|models?|sources?|inputs?)\s+(?:for|including|such as)\s+([^.!\n]+)", text, re.I)
    if inputs:
        # Explicit input lists are stronger retrieval evidence than output
        # measures such as units/revenue or incidental configuration nouns.
        text = " ".join(inputs)
    ignored = (_STOP - {"order"}) | set("metric metrics performance summary identification including comprehensive aggregate aggregates staging relevant explore determine understand relationship relationship fields called named materialize backend database profile setup environment variable variant_information total average price revenue column_name".split())
    counts: Counter[str] = Counter()
    for word in re.findall(r"[a-zA-Z][a-zA-Z0-9_]*", text):
        counts.update(term for term in _name_terms(word) if term not in ignored)
    if requested:
        counts.update({term: 3 for term in _name_terms(requested["model"]) if term not in ignored})
    return {term: min(count, 4) for term, count in counts.most_common(24)}


def _missing_target(instruction: str, focus_model: str | None, paths: list[Path], project: Path, root: Path) -> dict | None:
    """Identify an explicitly requested absent output, not an upstream mention."""
    mentions = re.findall(r"[\w./:\-]+\.sql", instruction.replace("\\", "/"), re.I)
    creation = re.search(r"\b(?:create|build|add)\b.{0,100}?\bmodel\b.{0,35}?\b(?:called|named)\s+[`\"']?([a-zA-Z_]\w*)", instruction, re.I | re.S)
    model = Path(focus_model.replace("\\", "/")).stem if focus_model else (creation.group(1) if creation else None)
    if model is None:
        # A requested SQL path is useful even when the prose omits 'called'.
        create_path = re.search(r"\b(?:create|build|add)\b[^\n]{0,120}?([\w./:\-]+\.sql)", instruction.replace("\\", "/"), re.I)
        if create_path:
            model = Path(create_path.group(1)).stem
    if not model or any(path.stem.lower() == model.lower() for path in paths):
        return None
    matching = [mention for mention in mentions if Path(mention).stem.lower() == model.lower()]
    requested_path = None
    for mention in matching:
        # Translate public absolute Linux paths to this selected local project.
        marker = re.search(r"(?:^|/)models/(.+\.sql)$", mention, re.I)
        if marker:
            candidate = project / "models" / marker.group(1)
            if _allowed(candidate, root):
                requested_path = candidate.relative_to(root).as_posix()
                break
    return {"model": model, "path": requested_path, "exists": False, "identified_by": "explicit focus_model absent from project" if focus_model else "requested new model in instruction"}


def _namespace_matches_directory(path: Path) -> bool:
    namespace, separator, entity = path.stem.lower().partition("__")
    return bool(separator and entity and namespace == "stg_" + path.parent.name.lower())


def _candidate_paths(paths: list[Path], terms: dict[str, int], entities: list[set[str]], prefer_staging: bool = False) -> list[tuple[Path, list[str]]]:
    ranked = []
    for path in paths:
        tokens = _name_terms(path.stem)
        matched = sorted(tokens & terms.keys())
        if not matched:
            continue
        if entities and not any(entity <= tokens or len(entity & tokens) >= 2 for entity in entities):
            # 'line items' within an entity phrase does not authorize any
            # unrelated model with 'line' or 'item' in its name.
            continue
        staging = "staging" in {part.lower() for part in path.parts} or path.stem.lower().startswith("stg_")
        score = sum(terms[word] for word in matched) + (10 if staging else 0) - 0.2 * len(tokens - terms.keys())
        ranked.append((score, path, matched, _namespace_matches_directory(path)))
    staging_ranked = [item for item in ranked if "staging" in {part.lower() for part in item[1].parts} or item[1].stem.lower().startswith("stg_")]
    if prefer_staging and staging_ranked:
        ranked = staging_ranked
    # Greedy coverage prevents six aliases of one frequently mentioned entity
    # from hiding the other inputs requested by the public business contract.
    selected: list[tuple[Path, list[str]]] = []
    covered: set[str] = set()
    signatures: set[tuple[str, ...]] = set()
    while ranked and len(selected) < MAX_CANDIDATE_SOURCES:
        distinct = [item for item in ranked if tuple(item[2]) not in signatures]
        if not distinct:
            break
        # For equally relevant inputs, prefer a namespace matching its source
        # directory over a shorter ambiguous name. This is a lineage hint,
        # never a claim that a queryable/namespaced model is semantically right.
        best = min(distinct, key=lambda item: (-(item[0] + 8 * len(set(item[2]) - covered)), not item[3], len(item[1].stem), item[1].as_posix()))
        ranked.remove(best)
        selected.append((best[1], best[2]))
        covered.update(best[2])
        signatures.add(tuple(best[2]))
    return selected


def _finish(context: dict) -> dict:
    meta = context["metadata"]
    # Budget priority: target SQL, README, bounded lineage, focused schema.
    while _size(context) > MAX_CONTEXT_CHARS - 80:
        if context.get("schema", {}).get("tables"):
            context["schema"]["tables"].popitem()
            context["schema"]["truncated"] = True
            meta["truncated_sections"].append("schema")
        elif context.get("lineage", {}).get("nodes"):
            context["lineage"]["nodes"].pop()
            context["lineage"]["truncated"] = True
            meta["truncated_sections"].append("lineage")
        elif context.get("candidate_sources"):
            context["candidate_sources"].pop()
            meta["truncated_sections"].append("candidate_sources")
        elif context.get("relationship_checks", {}).get("relationships"):
            context["relationship_checks"]["relationships"].pop()
            context["relationship_checks"]["truncated"] = True
            meta["truncated_sections"].append("relationship_checks")
        elif context.get("relationship_checks", {}).get("key_profiles"):
            context["relationship_checks"]["key_profiles"].pop()
            context["relationship_checks"]["truncated"] = True
            meta["truncated_sections"].append("relationship_checks")
        elif context.get("readme", {}).get("content"):
            content = context["readme"]["content"]
            excess = _size(context) - (MAX_CONTEXT_CHARS - 100)
            context["readme"]["content"] = content[:max(0, len(content) - max(excess, 200))]
            context["readme"]["truncated"] = True
            meta["truncated_sections"].append("readme")
        elif context.get("target", {}).get("sql"):
            content = context["target"]["sql"]
            excess = _size(context) - (MAX_CONTEXT_CHARS - 100)
            context["target"]["sql"] = content[:max(0, len(content) - max(excess, 200))]
            context["target"]["truncated"] = True
            meta["truncated_sections"].append("target_sql")
        else:
            break
        meta["truncated_sections"] = list(dict.fromkeys(meta["truncated_sections"]))
    if "candidate_sources" in context:
        meta["candidate_sources_returned"] = len(context["candidate_sources"])
        meta["candidate_sources_truncated"] = len(context["candidate_sources"]) < meta.get("candidate_sources_selected", 0)
    meta["serialized_chars"] = _size(context)
    meta["serialized_chars"] = _size(context)
    return context


def _relationship_checks(database: Path | None, models: list[str], duckdb_timezone: str | None = None) -> dict:
    """Bounded same-name ID evidence on selected inputs, never a key policy."""
    if duckdb_timezone not in (None, "UTC"):
        raise ValueError("Explicit DuckDB timezone must be UTC or omitted")
    result: dict[str, Any] = {
        "available": False, "key_profiles": [], "relationships": [], "truncated": False,
        "source": "read-only live DuckDB; exact selected model names and same-name *_id columns",
        "limits": {"models": MAX_CANDIDATE_SOURCES, "key_profiles": MAX_RELATION_PROFILES,
                   "relationships": MAX_RELATIONSHIPS, "examples_per_relationship": MAX_RELATION_EXAMPLES,
                   "queries": 1 + MAX_RELATION_PROFILES + MAX_RELATIONSHIPS,
                   "query_timeout_seconds": MAX_RELATION_QUERY_SECONDS},
        "queries_executed": 0,
        "note": "Full current input relations, without ticket-specific filters. Uniqueness and matching are evidence, not an authoritative business key or repair instruction.",
    }
    public_names = (name.lower() for name in models if not any(
        word in name.lower() for word in ("solution", "oracle", "evaluator", "ground_truth", "gold_answer")))
    names = list(dict.fromkeys(public_names))
    result["truncated"] = len(names) > MAX_CANDIDATE_SOURCES
    names = names[:MAX_CANDIDATE_SOURCES]
    if len(names) < 2 or database is None or not database.exists():
        result["note"] += " Fewer than two available selected inputs; no relationship query run."
        return result
    quote = lambda name: '"' + name.replace('"', '""') + '"'
    try:
        import duckdb
        with duckdb.connect(str(database), read_only=True) as connection:
            if duckdb_timezone is not None:
                connection.execute("SET TimeZone = 'UTC'")
            def execute(sql: str, params=None):
                result["queries_executed"] += 1
                timer = Timer(MAX_RELATION_QUERY_SECONDS, connection.interrupt)
                timer.daemon = True
                timer.start()
                try:
                    return connection.execute(sql, params or [])
                finally:
                    timer.cancel()

            placeholders = ",".join("?" for _ in names)
            columns = execute(f"SELECT table_schema,table_name,column_name,data_type FROM information_schema.columns WHERE lower(table_name) IN ({placeholders}) AND table_schema NOT IN ('information_schema','pg_catalog') ORDER BY table_schema,table_name,ordinal_position", names).fetchall()
            result["available"] = True
            by_model: dict[str, dict[tuple[str, str], dict[str, tuple[str, str]]]] = {}
            for schema, table, column, kind in columns:
                if column.lower().endswith("_id"):
                    by_model.setdefault(table.lower(), {}).setdefault((schema, table), {})[column.lower()] = (column, kind)
            shared: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
            ambiguous = []
            for model in names:
                relations = by_model.get(model, {})
                if len(relations) != 1:
                    if len(relations) > 1:
                        ambiguous.append(model)
                    continue
                (schema, table), ids = next(iter(relations.items()))
                for normalized, (column, kind) in ids.items():
                    shared.setdefault((normalized, kind), []).append((schema, table, column))
            if ambiguous:
                result["ambiguous_models_skipped"] = ambiguous
            endpoints = []
            for (column, _), relations in sorted(shared.items()):
                if len(relations) > 1:
                    endpoints.extend(relations)
            result["truncated"] |= len(endpoints) > MAX_RELATION_PROFILES
            profiles = {}
            for schema, table, column in endpoints[:MAX_RELATION_PROFILES]:
                relation, key = quote(schema) + "." + quote(table), quote(column)
                sql = f"""WITH counts AS (SELECT {key} AS k,COUNT(*) AS n FROM {relation} GROUP BY {key})
SELECT COALESCE(SUM(n),0),COALESCE(SUM(n) FILTER(WHERE k IS NULL),0),
 COUNT(*) FILTER(WHERE k IS NOT NULL),COUNT(*) FILTER(WHERE k IS NOT NULL AND n>1),
 COALESCE(SUM(n-1) FILTER(WHERE k IS NOT NULL AND n>1),0) FROM counts"""
                row = execute(sql).fetchone()
                profile = {"table": f"{schema}.{table}", "column": column, "row_count": int(row[0]),
                           "null_rows": int(row[1]), "distinct_non_null_keys": int(row[2]),
                           "duplicate_key_groups": int(row[3]), "duplicate_excess_rows": int(row[4])}
                profiles[(schema, table, column)] = profile
                result["key_profiles"].append(profile)
            candidates = []
            for (_, _), relations in sorted(shared.items()):
                for parent in relations:
                    parent_profile = profiles.get(parent)
                    if not parent_profile or parent_profile["duplicate_key_groups"] or not parent_profile["distinct_non_null_keys"]:
                        continue
                    for child in relations:
                        child_profile = profiles.get(child)
                        if child_profile and child_profile["duplicate_key_groups"]:
                            candidates.append((child, parent))
            result["truncated"] |= len(candidates) > MAX_RELATIONSHIPS
            for child, parent in candidates[:MAX_RELATIONSHIPS]:
                child_sql = quote(child[0]) + "." + quote(child[1])
                parent_sql = quote(parent[0]) + "." + quote(parent[1])
                child_key, parent_key = quote(child[2]), quote(parent[2])
                sql = f"""WITH missing AS (
 SELECT c.{child_key} AS k FROM {child_sql} c WHERE c.{child_key} IS NOT NULL
 AND NOT EXISTS (SELECT 1 FROM {parent_sql} p WHERE p.{parent_key}=c.{child_key})
), missing_keys AS (SELECT k,COUNT(*) AS n FROM missing GROUP BY k)
SELECT COALESCE(SUM(n),0),COUNT(*),
 (SELECT list(struct_pack(key := LEFT(CAST(k AS VARCHAR),120),rows := n))
  FROM (SELECT k,n FROM missing_keys ORDER BY n DESC,k LIMIT {MAX_RELATION_EXAMPLES}))
FROM missing_keys"""
                unmatched_rows, unmatched_keys, examples = execute(sql).fetchone()
                child_profile, parent_profile = profiles[child], profiles[parent]
                result["relationships"].append({
                    "kind": "many_to_one_candidate", "child": {"table": child_profile["table"], "column": child[2]},
                    "parent": {"table": parent_profile["table"], "column": parent[2]},
                    "parent_non_null_unique": True, "parent_null_rows": parent_profile["null_rows"],
                    "child_null_rows": child_profile["null_rows"],
                    "matched_non_null_rows": child_profile["row_count"] - child_profile["null_rows"] - int(unmatched_rows),
                    "unmatched_non_null_rows": int(unmatched_rows), "unmatched_non_null_keys": int(unmatched_keys),
                    "unmatched_examples": examples or [],
                })
            # Keep anomalies before complete relations when the shared JSON
            # budget later trims the end of this list.
            result["relationships"].sort(key=lambda row: (-row["unmatched_non_null_rows"], row["child"]["table"], row["parent"]["table"]))
    except Exception as exc:
        result["truncated"] = True
        result["error"] = f"Relationship evidence unavailable or partial: {str(exc)[:180]}"
    return result


def _schema(database: Path | None, names: set[str], terms: list[str], duckdb_timezone: str | None = None) -> dict:
    if duckdb_timezone not in (None, "UTC"):
        raise ValueError("Explicit DuckDB timezone must be UTC or omitted")
    result: dict[str, Any] = {"tables": {}, "source": "live DuckDB information_schema; metadata only", "selection": "exact target/upstream names first, then business-term matches", "truncated": False}
    if database is None or not database.exists():
        result["note"] = "Use search_schema with the target/ref names after the warehouse is ready."
        return result
    try:
        import duckdb
        with duckdb.connect(str(database), read_only=True) as connection:
            if duckdb_timezone is not None:
                connection.execute("SET TimeZone = 'UTC'")
            tables = connection.execute("select table_schema, table_name from information_schema.tables where table_schema not in ('information_schema','pg_catalog')").fetchall()
            ranked = []
            for schema, table in tables:
                if any(token in table.lower() for token in ("ground_truth", "solution", "oracle", "gold_answer", "evaluator")):
                    continue
                name = table.lower()
                score = 100 if name in names else sum(3 for word in terms if word in name)
                if score:
                    ranked.append((score, schema, table))
            ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
            result["matched_tables"] = len(ranked)
            result["truncated"] = len(ranked) > 8
            for _, schema, table in ranked[:8]:
                columns = connection.execute("select column_name, data_type from information_schema.columns where table_schema=? and table_name=? order by ordinal_position", [schema, table]).fetchall()
                result["tables"][f"{schema}.{table}"] = {"columns": [{"name": col, "type": kind} for col, kind in columns[:60]], "column_count": len(columns), "truncated": len(columns) > 60}
    except Exception as exc:
        result["note"] = f"Focused schema unavailable: {str(exc)[:200]}; use search_schema with target/ref names."
    return result


def build_task_context(workspace: Any, instruction: str, focus_model: str | None = None) -> dict:
    """Return <=24k JSON characters of task-relevant *public* project assets.

    ``workspace`` can be a Workspace object or a project Path. No task IDs,
    reference patches, model answers, or hidden validators influence selection.
    When a mock/missing workspace cannot be read, return a small tool-guided
    overview instead of eagerly calling unfiltered schema/lineage tools.
    """
    # Path.root is a drive anchor, whereas Workspace.root is the project path.
    root = Path(workspace if isinstance(workspace, (str, Path)) else workspace.root).resolve()
    project = Path(getattr(workspace, "project_dir", root)).resolve()
    database = Path(getattr(workspace, "database_path", project / "warehouse.duckdb"))
    duckdb_timezone = getattr(workspace, "duckdb_timezone", None)
    context: dict[str, Any] = {"target": None, "lineage": {"nodes": [], "source": "focused parsed dbt refs; upstream only", "truncated": False}, "schema": {"tables": {}}, "guidance": [], "metadata": {"budget_chars": MAX_CONTEXT_CHARS, "sources": [], "truncated_sections": [], "selection": "instruction paths/model names only; no task-ID rules"}}
    if duckdb_timezone is not None:
        context["metadata"]["runtime_settings"] = {"duckdb_timezone": duckdb_timezone}
    try:
        paths = [path for path in sorted((project / "models").rglob("*.sql")) if path.is_file() and _allowed(path, root)]
    except OSError:
        paths = []
    normalized = instruction.replace("\\", "/").lower()
    path_mentions = re.findall(r"[\w./:\-]+\.sql", normalized)
    ranked = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        project_relative = path.relative_to(project).as_posix()
        score, reason = 0, ""
        if focus_model and (Path(focus_model.replace("\\", "/")).stem.lower() == path.stem.lower()):
            score, reason = 1000, "explicit focus_model"
        for mention in path_mentions:
            if mention.endswith(relative.lower()) or mention.endswith(project_relative.lower()):
                if score < 800:
                    score, reason = 800 + min(len(project_relative), 100), "explicit SQL path in instruction"
            elif mention.rsplit("/", 1)[-1] == path.name.lower() and score < 700:
                score, reason = 700, "explicit SQL filename in instruction"
        if re.search(r"(?<![\w])" + re.escape(path.stem.lower()) + r"(?![\w])", normalized) and score < 600:
            score, reason = 600, "exact model name in instruction"
        if score:
            ranked.append((score, relative, path, reason))
    ranked.sort(key=lambda entry: (-entry[0], entry[1]))
    terms = _terms(instruction)
    requested = _missing_target(instruction, focus_model, paths, project, root)
    if requested:
        # Inputs explicitly named in a creation ticket are not the output to edit.
        ranked = []
        context["requested_target"] = requested
    # Business requirements are needed even if the short ticket does not name
    # an existing model. In particular the independent review gets no executor
    # conversation, so a tool-read README cannot substitute for this context.
    for readme in dict.fromkeys([project / "README.md", root / "README.md"]):
        if readme.is_file() and _allowed(readme, root):
            try:
                document = _read_public_text(readme, root)
                context["readme"] = {"path": readme.relative_to(root).as_posix(), "content": document[:8000], "source_chars": len(document), "truncated": len(document) > 8000}
                context["metadata"]["sources"].append(readme.relative_to(root).as_posix())
                if len(document) > 8000:
                    context["metadata"]["truncated_sections"].append("readme")
                break
            except (OSError, ValueError):
                pass
    if not ranked:
        if requested:
            source_terms = _source_terms(instruction, requested)
            context["candidate_sources"] = []
            names: set[str] = set()
            for source_path, matched in _candidate_paths(paths, source_terms, _input_entities(instruction), bool(re.search(r"\bstaging\b", instruction, re.I))):
                try:
                    source_sql = _read_public_text(source_path, root)
                except (OSError, ValueError):
                    continue
                relative = source_path.relative_to(root).as_posix()
                refs = _refs(source_sql)
                clipped = len(source_sql) > MAX_SOURCE_SQL_CHARS
                context["candidate_sources"].append({"model": source_path.stem, "path": relative, "sql": source_sql[:MAX_SOURCE_SQL_CHARS], "source_chars": len(source_sql), "truncated": clipped, "upstream": refs[:20], "matched_terms": matched, "namespace_matches_directory": _namespace_matches_directory(source_path), "identified_by": "public requirement/model-name terms; staging and distinct input coverage preferred; directory-matching namespace breaks relevance ties"})
                context["lineage"]["nodes"].append({"model": source_path.stem, "path": relative, "upstream": refs[:20]})
                context["metadata"]["sources"].append(relative)
                names.update([source_path.stem.lower(), *(ref.lower() for ref in refs)])
                if clipped:
                    context["metadata"]["truncated_sections"].append("candidate_source_sql")
            context["metadata"].update({"task_mode": "create", "candidate_sources_selected": len(context["candidate_sources"]), "source_selection_terms": list(source_terms)})
            context["schema"] = _schema(database, names, list(source_terms), duckdb_timezone)
            context["relationship_checks"] = _relationship_checks(database, [source["model"] for source in context["candidate_sources"]], duckdb_timezone)
            if context["schema"].get("truncated"):
                context["metadata"]["truncated_sections"].append("schema")
        available = [path.relative_to(root).as_posix() for path in paths]
        if not available and callable(getattr(workspace, "list_files", None)):
            try:
                available = [value for value in workspace.list_files().get("files", []) if str(value).endswith(".sql") and not {part.lower() for part in Path(value).parts} & _FORBIDDEN]
            except Exception:
                available = []
        available.sort(key=lambda value: (-sum(word in value.lower() for word in terms), value))
        context["candidate_files"] = available[:12]
        context["metadata"]["candidate_files_truncated"] = len(available) > 12
        context["guidance"] = ([f"The requested output model {requested['model']} does not exist in this project's models. Its absence is expected for this creation task: confirm the preloaded candidate inputs and their grain, then use write_model to create it at the requested path; do not repeatedly search for the absent output.", "Candidate source SQL is selected from public requirement words, not proof of the correct inputs. Inspect only missing relationships/columns using focused read_file, search_schema or query_sql; avoid a full project listing."] if requested else ["No existing target model was identified. Use list_files/read_file to locate the requested model before querying.", f"Use search_schema with specific business terms or discovered ref names (suggestions: {', '.join(terms[:4]) or 'model/ref name'}). Do not request the full warehouse schema."])
        context["metadata"]["target_found"] = False
        return _finish(context)
    _, relative, target, reason = ranked[0]
    try:
        sql = _read_public_text(target, root)
    except (OSError, ValueError):
        context["guidance"] = [f"Target appears to be {relative}; use read_file to inspect it."]
        return _finish(context)
    context["target"] = {"model": target.stem, "path": relative, "sql": sql, "source_chars": len(sql), "truncated": False, "identified_by": reason}
    context["metadata"].update({"target_found": True, "sources": [*context["metadata"]["sources"], relative]})
    if len(ranked) > 1:
        context["other_mentions"] = [entry[1] for entry in ranked[1:4]]
    # A bounded upstream traversal gives get_lineage(target)'s relevant refs and
    # paths without reading thousands of downstream/unrelated SQL files.
    index = {path.stem.lower(): path for path in paths}
    queue = deque([(target, sql, 0)])
    seen: set[str] = set()
    names: set[str] = set()
    while queue and len(context["lineage"]["nodes"]) < 6:
        node_path, node_sql, depth = queue.popleft()
        if node_path.stem in seen:
            continue
        seen.add(node_path.stem)
        refs = _refs(node_sql)
        names.update(name.lower() for name in refs)
        names.add(node_path.stem.lower())
        context["lineage"]["nodes"].append({"model": node_path.stem, "path": node_path.relative_to(root).as_posix(), "upstream": refs[:20]})
        source_path = node_path.relative_to(root).as_posix()
        if source_path not in context["metadata"]["sources"]:
            context["metadata"]["sources"].append(source_path)
        if depth < 2:
            for ref in refs[:10]:
                upstream = index.get(ref.lower())
                if upstream and upstream.stem not in seen:
                    try:
                        queue.append((upstream, _read_public_text(upstream, root), depth + 1))
                    except (OSError, ValueError):
                        pass
    context["lineage"]["truncated"] = bool(queue)
    if queue:
        context["metadata"]["truncated_sections"].append("lineage")
    names.update(name.lower().split(".")[-1].strip('"') for name in re.findall(r"\b(?:from|join)\s+([\w.\"]+)", sql, re.I) if name.lower() not in {"select", "ref", "source"})
    context["schema"] = _schema(database, names, terms, duckdb_timezone)
    relationship_models = [node["model"] for node in context["lineage"]["nodes"]
                           if node["model"] != target.stem and (node["model"].lower().startswith("stg_") or "staging" in Path(node["path"]).parts)]
    context["relationship_checks"] = _relationship_checks(database, relationship_models, duckdb_timezone)
    if context["schema"].get("truncated"):
        context["metadata"]["truncated_sections"].append("schema")
    context["guidance"] = ["The target SQL is preloaded. Inspect only missing upstream details, then make a scoped model edit and run the selected model.", "Schema is filtered to target/ref names and business terms. Visible tests and the final evaluator are not included here."]
    return _finish(context)
