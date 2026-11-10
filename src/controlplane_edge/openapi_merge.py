"""Merge multiple OpenAPI 3.x documents from independent services."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _rewrite_schema_refs(obj: Any, svc_id: str, schema_names: set[str]) -> Any:
    """Rewrite schema pointers in OpenAPI structure, never application literals."""
    prefix = "#/components/schemas/"

    def pointer(ref: str) -> str:
        return prefix + svc_id + "__" + ref[len(prefix):] if ref.startswith(prefix) else ref

    def walk(value: Any, kind: str) -> Any:
        if not isinstance(value, dict):
            return deepcopy(value)
        result = deepcopy(value)
        if isinstance(result.get("$ref"), str):
            result["$ref"] = pointer(result["$ref"])

        def mapping(key: str, child: str) -> None:
            if isinstance(result.get(key), dict):
                result[key] = {name: walk(item, child) for name, item in result[key].items()}

        def sequence(key: str, child: str) -> None:
            if isinstance(result.get(key), list):
                result[key] = [walk(item, child) for item in result[key]]

        def single(key: str, child: str) -> None:
            if key in result:
                result[key] = walk(result[key], child)

        if kind == "document":
            mapping("paths", "path")
            mapping("webhooks", "path")
            components = result.get("components", {})
            for category, child in {"schemas": "schema", "parameters": "parameter", "headers": "parameter",
                                    "requestBodies": "body", "responses": "response", "callbacks": "callback",
                                    "pathItems": "path"}.items():
                if isinstance(components.get(category), dict):
                    components[category] = {name: walk(item, child) for name, item in components[category].items()}
        elif kind == "schema":
            for key in ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas"):
                mapping(key, "schema")
            for key in ("allOf", "oneOf", "anyOf", "prefixItems"):
                sequence(key, "schema")
            for key in ("items", "additionalItems", "additionalProperties", "unevaluatedProperties",
                        "unevaluatedItems", "not", "contains", "propertyNames", "if", "then", "else", "contentSchema"):
                single(key, "schema")
            discriminator = result.get("discriminator")
            if isinstance(discriminator, dict) and isinstance(discriminator.get("mapping"), dict):
                targets = {}
                for tag, target in discriminator["mapping"].items():
                    if isinstance(target, str) and target in schema_names:
                        target = prefix + target.replace("~", "~0").replace("/", "~1")
                    targets[tag] = pointer(target) if isinstance(target, str) else target
                discriminator["mapping"] = targets
        elif kind == "path":
            for method in _HTTP_METHODS:
                single(method, "operation")
            sequence("parameters", "parameter")
        elif kind == "operation":
            sequence("parameters", "parameter")
            single("requestBody", "body")
            mapping("responses", "response")
            mapping("callbacks", "callback")
        elif kind == "response":
            mapping("content", "media")
            mapping("headers", "parameter")
        elif kind == "body":
            mapping("content", "media")
        elif kind in ("parameter", "media"):
            single("schema", "schema")
            if kind == "parameter":
                mapping("content", "media")
            else:
                encoding = result.get("encoding", {})
                for item in encoding.values() if isinstance(encoding, dict) else ():
                    if isinstance(item, dict) and isinstance(item.get("headers"), dict):
                        item["headers"] = {name: walk(header, "parameter") for name, header in item["headers"].items()}
        elif kind == "callback":
            result = {name: walk(item, "path") if name != "$ref" and not name.startswith("x-") else item
                      for name, item in result.items()}
        return result

    return walk(obj, "document")


def _namespace_remote_spec(svc_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Namespace schema names, structural references and discriminator mappings."""
    s = deepcopy(spec)
    comps = s.setdefault("components", {})
    schemas = comps.get("schemas") or {}
    comps["schemas"] = {f"{svc_id}__{name}": body for name, body in schemas.items()}
    return _rewrite_schema_refs(s, svc_id, set(schemas))


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
