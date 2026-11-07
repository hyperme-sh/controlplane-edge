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


_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "options", "head", "trace")


def _security_requirements(requirements: Any, names: dict[str, str]) -> Any:
    if not isinstance(requirements, list):
        return deepcopy(requirements)
    return [{names.get(key, key): deepcopy(scopes) for key, scopes in item.items()}
            if isinstance(item, dict) else deepcopy(item) for item in requirements]


def _path_security(path_item: dict[str, Any], names: dict[str, str], inherited: Any) -> None:
    for method in _HTTP_METHODS:
        operation = path_item.get(method)
        if not isinstance(operation, dict):
            continue
        if "security" in operation:
            operation["security"] = _security_requirements(operation["security"], names)
        elif inherited is not None:
            # Each upstream can have a different root policy. Materialize it on
            # its own operations instead of applying one document's policy globally.
            operation["security"] = _security_requirements(inherited, names)
        for callback in (operation.get("callbacks") or {}).values():
            if isinstance(callback, dict):
                for expression, nested in callback.items():
                    if expression != "$ref" and isinstance(nested, dict):
                        _path_security(nested, names, inherited)


def _security_refs(value: Any, names: dict[str, str]) -> Any:
    if isinstance(value, dict):
        result = {key: _security_refs(item, names) for key, item in value.items()}
        ref = result.get("$ref")
        prefix = "#/components/securitySchemes/"
        if isinstance(ref, str) and ref.startswith(prefix):
            name = ref[len(prefix):]
            result["$ref"] = prefix + names.get(name, name)
        return result
    if isinstance(value, list):
        return [_security_refs(item, names) for item in value]
    return deepcopy(value)


def merge_openapi(
    specs: list[tuple[str, dict[str, Any]]],
    *,
    title: str = "spanopticon Aggregated API",
    version: str = "1.0.0",
    description: str | None = None,
) -> dict[str, Any]:
    """Merge OpenAPI dicts. Each tuple is ``(service_id, openapi_dict)``.

    - ``controlplane-edge`` paths and schema names remain local.
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

        comps = merged_spec.get("components") or {}
        schemes = comps.get("securitySchemes") or {}
        destination = out["components"]["securitySchemes"]
        reserved = set(destination) | set(schemes)
        security_names = {}
        for name in schemes:
            key = name
            if key in destination:
                base = f"{svc_id}_{name}"
                key, suffix = base, 2
                while key in reserved:
                    key = f"{base}_{suffix}"
                    suffix += 1
            security_names[name] = key
            reserved.add(key)
        for name, scheme in schemes.items():
            destination[security_names[name]] = _security_refs(scheme, security_names)

        paths = merged_spec.get("paths") or {}
        for p, path_item in paths.items():
            dest_key = f"{path_prefix}{p}" if path_prefix else p
            if dest_key in out["paths"]:
                dest_key = f"{path_prefix}/__collision__{abs(hash(p)) % 1_000_000}{p}"
            out["paths"][dest_key] = deepcopy(path_item)
            _path_security(out["paths"][dest_key], security_names, merged_spec.get("security"))
            for method in _HTTP_METHODS:
                op = out["paths"][dest_key].get(method)
                if not isinstance(op, dict):
                    continue
                tags = op.get("tags") or []
                tag_prefix = f"[{svc_id}] "
                op["tags"] = [tag_prefix + t for t in tags] if tags else [f"[{svc_id}]"]

        comps = merged_spec.get("components") or {}
        for name, schema in (comps.get("schemas") or {}).items():
            out["components"]["schemas"][name] = deepcopy(schema)


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
