"""
java/endpoint_mapper.py — Maps endpoint flows: controller → service → repository.

Uses static analysis via regex (no Java parser).

Output:
  {
    "flows": [
      {
        "endpoint": "POST /transactions",
        "controller_file": "/path/TransactionController.java",
        "controller_class": "TransactionController",
        "controller_method": "authorize",
        "service_info": [{"field_name": "...", "field_type": "...", "method": "..."}],
        "files": [ctrl_file, svc_impl_file, repo_file],
      }
    ],
    "file_sharing": {
      "/path/TransactionServiceImpl.java": ["POST /transactions", "GET /transactions/{id}"]
    }
  }
"""

import os
import re
from core.utils import read_file
from java.refactor import get_java_files

_SERVICE_TYPES = ("Service", "Repository", "Manager", "Handler", "Gateway", "Client", "Port", "Facade")
_REPO_MARKERS  = ("JpaRepository", "CrudRepository", "MongoRepository", "ReactiveMongoRepository",
                   "PagingAndSortingRepository", "@Repository")


def build_flow_map(repo_path: str) -> dict:
    """
    Builds the flow map from the project's controllers.
    Returns flows (list) and file_sharing (files shared across 2+ flows).
    """
    java_files    = get_java_files(repo_path, tests=False)
    class_file_map = _build_class_file_map(java_files)

    flows = []

    for file_path in java_files:
        code = read_file(file_path)
        if not code or not _is_controller(code):
            continue

        ctrl_class  = _get_class_name(code)
        base_path   = _get_base_path(code)
        injected    = _find_injected_fields(code)
        endpoints   = _extract_endpoints(code, base_path, injected)

        for ep in endpoints:
            flow_files   = [file_path]
            service_info = []

            for call in ep.get("service_calls", []):
                field_type = call["field_type"]

                # Resolve interface → implementation
                impl_file = (
                    _find_implementation(field_type, java_files, class_file_map)
                    or class_file_map.get(field_type)
                )
                if impl_file and impl_file not in flow_files:
                    flow_files.append(impl_file)

                    # Find repositories used by this service impl
                    svc_code = read_file(impl_file)
                    if svc_code:
                        for _fn, repo_type in _find_injected_fields(svc_code).items():
                            repo_file = class_file_map.get(repo_type)
                            if repo_file and repo_file not in flow_files:
                                repo_code = read_file(repo_file)
                                if repo_code and _is_repository(repo_code):
                                    flow_files.append(repo_file)

                service_info.append({
                    "field_name": call["field_name"],
                    "field_type": field_type,
                    "method":     call["method"],
                    "impl_file":  impl_file,
                })

            flows.append({
                "endpoint":           f"{ep['http_method']} {base_path}{ep['path']}",
                "controller_file":    file_path,
                "controller_class":   ctrl_class,
                "controller_method":  ep["method_name"],
                "service_info":       service_info,
                "files":              flow_files,
            })

    file_sharing = _build_file_sharing(flows)
    return {"flows": flows, "file_sharing": file_sharing}


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------

def _is_controller(code: str) -> bool:
    return "@RestController" in code or "@Controller" in code


def _is_repository(code: str) -> bool:
    return any(marker in code for marker in _REPO_MARKERS)


# ---------------------------------------------------------------------------
# Class / path helpers
# ---------------------------------------------------------------------------

def _build_class_file_map(java_files: list[str]) -> dict[str, str]:
    """Maps class/interface name → absolute file path."""
    result = {}
    for f in java_files:
        name = _get_class_name(read_file(f))
        if name:
            result[name] = f
    return result


def _get_class_name(code: str) -> str:
    m = re.search(r'(?:public\s+)?(?:class|interface|enum|record)\s+(\w+)', code)
    return m.group(1) if m else ""


def _get_base_path(code: str) -> str:
    """Extracts class-level @RequestMapping path."""
    m = re.search(
        r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']*)["\']',
        code,
    )
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# Dependency injection detection
# ---------------------------------------------------------------------------

def _find_injected_fields(code: str) -> dict[str, str]:
    """
    Returns {field_name: field_type} for service/repository-like dependencies.
    Handles field injection AND constructor injection.
    """
    result: dict[str, str] = {}

    # Field injection: private [final] TypeName fieldName;
    for m in re.finditer(r'private\s+(?:final\s+)?(\w[\w<>]*)\s+(\w+)\s*;', code):
        field_type, field_name = m.group(1), m.group(2)
        if any(t in field_type for t in _SERVICE_TYPES):
            result[field_name] = field_type

    # Constructor injection: public ClassName(TypeA paramA, TypeB paramB)
    for m in re.finditer(r'public\s+\w+\s*\(([^)]+)\)', code):
        for pm in re.finditer(r'(\w[\w<>]*)\s+(\w+)(?:\s*,|\s*$)', m.group(1)):
            param_type, param_name = pm.group(1), pm.group(2)
            if any(t in param_type for t in _SERVICE_TYPES):
                result[param_name] = param_type

    return result


# ---------------------------------------------------------------------------
# Endpoint extraction
# ---------------------------------------------------------------------------

def _extract_endpoints(code: str, base_path: str,
                        injected: dict[str, str]) -> list[dict]:
    """Extracts endpoint methods and the service calls within each."""
    endpoints = []
    lines     = code.splitlines()

    i = 0
    while i < len(lines):
        mapping = _detect_mapping_annotation(lines[i].strip())
        if mapping:
            http_method, path = mapping

            # Find the method declaration within the next 6 lines
            method_name = None
            method_start = i + 1
            for j in range(i + 1, min(i + 7, len(lines))):
                m = re.search(r'public\s+[\w<>@,\s\[\]]+\s+(\w+)\s*\(', lines[j])
                if m:
                    method_name = m.group(1)
                    method_start = j
                    break

            if method_name:
                body          = _extract_method_body(lines, method_start)
                service_calls = _find_service_calls(body, injected)
                endpoints.append({
                    "http_method":    http_method,
                    "path":           path,
                    "method_name":    method_name,
                    "service_calls":  service_calls,
                })
        i += 1

    return endpoints


def _detect_mapping_annotation(line: str) -> tuple[str, str] | None:
    """Returns (HTTP_METHOD, path) or None for @XxxMapping lines."""
    m = re.match(
        r'@(Get|Post|Put|Delete|Patch)Mapping'
        r'(?:\s*\(\s*(?:(?:value|path)\s*=\s*)?'
        r'["\']([^"\']*)["\'][^)]*\))?\s*$',
        line,
    )
    if not m:
        return None
    return m.group(1).upper(), (m.group(2) or "")


def _extract_method_body(lines: list[str], start: int) -> str:
    """Extracts the method body starting from the method declaration line."""
    depth   = 0
    started = False
    body    = []

    for i in range(start, len(lines)):
        line = lines[i]
        body.append(line)
        opens  = line.count('{')
        closes = line.count('}')
        if opens > 0:
            started = True
        if started:
            depth += opens - closes
            if depth <= 0:
                break

    return "\n".join(body)


def _find_service_calls(body: str, injected: dict[str, str]) -> list[dict]:
    """Find calls to injected service fields: fieldName.methodName(...)"""
    calls = []
    for field_name, field_type in injected.items():
        for m in re.finditer(rf'\b{re.escape(field_name)}\.(\w+)\s*\(', body):
            calls.append({
                "field_name": field_name,
                "field_type": field_type,
                "method":     m.group(1),
            })
    return calls


# ---------------------------------------------------------------------------
# Implementation resolution
# ---------------------------------------------------------------------------

def _find_implementation(interface_name: str, java_files: list[str],
                          class_file_map: dict[str, str]) -> str | None:
    """Finds the class that implements a given interface."""
    pattern = re.compile(rf'\bimplements\b[^{{]*\b{re.escape(interface_name)}\b')

    for file_path in java_files:
        code = read_file(file_path)
        if code and pattern.search(code):
            return file_path

    # Common naming: UserService → UserServiceImpl
    return class_file_map.get(f"{interface_name}Impl")


# ---------------------------------------------------------------------------
# File sharing analysis
# ---------------------------------------------------------------------------

def _build_file_sharing(flows: list[dict]) -> dict[str, list[str]]:
    """
    Returns files that appear in 2+ flows, mapped to the endpoints using them.
    These are SHARED files — must be refactored with multi-flow context.
    """
    file_endpoints: dict[str, list[str]] = {}
    for flow in flows:
        ep = flow["endpoint"]
        for f in flow["files"]:
            file_endpoints.setdefault(f, []).append(ep)

    return {f: eps for f, eps in file_endpoints.items() if len(eps) > 1}
