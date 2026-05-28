import os
import re
import javalang
from core.logger import log

def get_vertical_slices(repo_path: str):
    """
    Maps the vertical flows of the project (Controller -> Service -> Repository).
    Returns a list of file lists (each sub-list is one 'Slice').
    """
    java_files = []
    for root, _, files in os.walk(repo_path):
        if "src/main/java" not in root: continue
        for f in files:
            if f.endswith(".java"):
                java_files.append(os.path.join(root, f))

    controllers = []
    for f in java_files:
        with open(f, 'r', encoding='utf-8') as content:
            code = content.read()
            if "@RestController" in code or "@Controller" in code:
                controllers.append(f)

    slices = []
    for ctrl in controllers:
        slice_files = [ctrl]
        dependencies = _trace_dependencies(ctrl, java_files)
        slice_files.extend(dependencies)
        # Remove duplicatas mantendo a ordem
        unique_slice = []
        for sf in slice_files:
            if sf not in unique_slice:
                unique_slice.append(sf)
        slices.append(unique_slice)

    return slices

def _trace_dependencies(file_path: str, all_files: str, depth=0):
    """Traces dependencies via dependency injection (recursive). Max depth 3."""
    if depth > 3: return []
    
    deps = []
    with open(file_path, 'r', encoding='utf-8') as f:
        code = f.read()

    # Identify injected class names via @Autowired or constructor
    # 1. @Autowired private ServiceName service;
    # 2. private final ServiceName service; (constructor injection)
    injected_classes = re.findall(r'(?:@Autowired\s+)?(?:private|protected)\s+(?:final\s+)?(\w+)\s+\w+;', code)

    # 3. Constructor injection (constructor arguments)
    class_name = os.path.basename(file_path).replace(".java", "")
    constructor_match = re.search(rf'public\s+{class_name}\s*\((.*?)\)', code, re.DOTALL)
    if constructor_match:
        params = constructor_match.group(1).split(",")
        for p in params:
            parts = p.strip().split()
            if len(parts) >= 2:
                deps.append(parts[-2])  # the class type

    injected_classes.extend(deps)

    found_files = []
    for cls in set(injected_classes):
        if cls in ["String", "Long", "Integer", "BigDecimal", "List", "Map", "Optional"]: continue
        
        # Search for the file corresponding to this class
        for target in all_files:
            if os.path.basename(target) == f"{cls}.java":
                found_files.append(target)
                # Recurse to find the next level (e.g. Service -> Repo)
                found_files.extend(_trace_dependencies(target, all_files, depth + 1))
                break
                
    return found_files
