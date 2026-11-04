"""Merge multiple OpenAPI 3.x documents from independent services."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _rewrite_schema_refs(obj: Any, svc_id: str) -> Any:
    """Rewrite ``#/components/schemas/Name`` → ``#/components/schemas/{svc_id}__Name``."""

    if isinstance(obj, dict):
        ref = obj.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            name = ref.rsplit("/", 1)[-1]
            return {
                **{k: _rewrite_schema_refs(v, svc_id) for k, v in obj.items() if k != "$ref"},
                "$ref": f"#/components/schemas/{svc_id}__{name}",
            }
        return {k: _rewrite_schema_refs(v, svc_id) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rewrite_schema_refs(x, svc_id) for x in obj]
    return obj


def _namespace_remote_spec(svc_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Deep copy remote spec; namespace component schema keys and all refs."""

    s = deepcopy(spec)
    comps = s.setdefault("components", {})
    schemas = comps.get("schemas") or {}
    new_schemas: dict[str, Any] = {}
    for name, body in schemas.items():
        new_schemas[f"{svc_id}__{name}"] = body
    comps["schemas"] = new_schemas
    return _rewrite_schema_refs(s, svc_id)


def merge_openapi(
    specs: list[tuple[str, dict[str, Any]]],
    *,
    title: str = "Panopticon Aggregated API",
    version: str = "1.0.0",
    description: str | None = None,
) -> dict[str, Any]:
    """Merge OpenAPI dicts. Each tuple is ``(service_id, openapi_dict)``.

    - ``gateway`` (monolith) paths and schemas are merged as-is.
    - Other services: refs and ``components.schemas`` keys use ``{svc_id}__`` prefix;
      paths are prefixed with ``/_upstream/{service_id}`` to avoid collisions.
    - Operation tags get a ``[service_id]`` prefix for remote services.
    """
    out: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": title,
            "version": version,
            "description": description or "Aggregated from the control-plane edge and microservice OpenAPI specs.",
        },
        "paths": {},
        "components": {"schemas": {}, "securitySchemes": {}},
    }

    for svc_id, spec in specs:
        if not spec:
            continue
        oa = spec.get("openapi", "3.0.0")
        if isinstance(oa, str) and oa.startswith("3"):
            out["openapi"] = oa

        merged_spec = deepcopy(spec) if svc_id == "controlplane-edge" else _namespace_remote_spec(svc_id, spec)

        path_prefix = "" if svc_id == "controlplane-edge" else f"/_upstream/{svc_id}"

        paths = merged_spec.get("paths") or {}
        for p, path_item in paths.items():
            dest_key = f"{path_prefix}{p}" if path_prefix else p
            if dest_key in out["paths"]:
                dest_key = f"{path_prefix}/__collision__{abs(hash(p)) % 1_000_000}{p}"
            out["paths"][dest_key] = deepcopy(path_item)
            for method in ("get", "post", "put", "patch", "delete", "options", "head"):
                op = out["paths"][dest_key].get(method)
                if not isinstance(op, dict):
                    continue
                tags = op.get("tags") or []
                tag_prefix = f"[{svc_id}] "
                op["tags"] = [tag_prefix + t for t in tags] if tags else [f"[{svc_id}]"]

        comps = merged_spec.get("components") or {}
        for name, schema in (comps.get("schemas") or {}).items():
            out["components"]["schemas"][name] = deepcopy(schema)

        for name, scheme in (comps.get("securitySchemes") or {}).items():
            key = name if name not in out["components"]["securitySchemes"] else f"{svc_id}_{name}"
            out["components"]["securitySchemes"][key] = deepcopy(scheme)

    out["x-controlplane-edge-meta"] = {
        "merge_strategy": "http_aggregation",
        "sources": [s[0] for s in specs],
    }
    return out


def diff_openapi_changelog(
    a: dict[str, Any],
    b: dict[str, Any],
) -> dict[str, Any]:
    """Return a compact summary of differences between two OpenAPI documents."""
    paths_a = set((a.get("paths") or {}).keys())
    paths_b = set((b.get("paths") or {}).keys())
    schemas_a = set((a.get("components") or {}).get("schemas", {}).keys())
    schemas_b = set((b.get("components") or {}).get("schemas", {}).keys())
    return {
        "paths_added": sorted(paths_b - paths_a),
        "paths_removed": sorted(paths_a - paths_b),
        "schemas_added": sorted(schemas_b - schemas_a),
        "schemas_removed": sorted(schemas_a - schemas_b),
        "info_changed": (a.get("info") or {}) != (b.get("info") or {}),
    }


def diff_openapi_to_markdown(diff: dict[str, Any], *, title: str = "OpenAPI changelog") -> str:
    """Render ``diff_openapi_changelog`` output as Markdown."""

    lines = [f"# {title}", ""]

    def _bullets(label: str, key: str) -> None:
        items = diff.get(key) or []
        if not items:
            return
        lines.append(f"## {label}")
        lines.extend(f"- `{x}`" for x in items)
        lines.append("")

    _bullets("Paths added", "paths_added")
    _bullets("Paths removed", "paths_removed")
    _bullets("Schemas added", "schemas_added")
    _bullets("Schemas removed", "schemas_removed")
    if diff.get("info_changed"):
        lines.append("## Info")
        lines.append("- `info` block changed between versions.")
        lines.append("")
    if len(lines) <= 2:
        lines.append("_No structural differences._")
        lines.append("")
    return "\n".join(lines)
