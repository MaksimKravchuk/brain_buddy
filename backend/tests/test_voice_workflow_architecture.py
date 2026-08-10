"""AST/import-boundary coverage for the Voice Brain Dump workflow (T058).

ADR-0001 requires that the application workflow layer cross the Tasks module
boundary only through the injected ``TaskPort`` -- never by importing
``TaskRepository``/``TaskService`` directly. ADR-0002 requires exactly one
shared ``AsyncOperation`` provider-role substrate for both voice Brain Dump
and a future voice-led Weekly Review, not a second voice engine. These
invariants are asserted here through real AST/import analysis of the shipped
source tree rather than fragile source-text substring checks, so a rename or
reformat cannot silently defeat the guard.
"""

from __future__ import annotations

import ast
from pathlib import Path

import app as app_package
from app.workflows.voice_brain_dump.providers import TextReconcilerPort

APP_ROOT = Path(app_package.__file__).resolve().parent
VOICE_BRAIN_DUMP_ROOT = APP_ROOT / "workflows" / "voice_brain_dump"


def test_optional_reconciler_provenance_does_not_widen_the_public_port() -> None:
    """Legacy/custom reconcilers remain structurally valid.

    Model and template-version provenance are optional adapter capabilities
    discovered fail-safe by the service. Requiring them on the public Protocol
    would make every pre-provenance adapter fail static type checking even
    though reconciliation itself remains compatible.
    """

    assert "model" not in TextReconcilerPort.__dict__
    assert "template_version" not in TextReconcilerPort.__dict__


# Method names that uniquely identify the ADR-0002 provider-role port
# contracts (``FastSttPort.transcribe_window``,
# ``AccurateSttPort.transcribe_sealed_audio``,
# ``TextReconcilerPort.reconcile``). ``reconcile`` alone is common English
# vocabulary, so it only counts as a duplicate-engine signal when the class
# also carries the role attribute every reconciler adapter in
# ``providers.py`` defines (``requires_external_processing``); the other two
# method names are specific enough to stand alone.
_STANDALONE_PORT_METHOD_NAMES = frozenset(
    {"transcribe_window", "transcribe_sealed_audio"}
)
_RECONCILER_METHOD_NAME = "reconcile"
_RECONCILER_ROLE_ATTRIBUTE = "requires_external_processing"


def _module_name_for(path: Path) -> str:
    """Dotted module name for ``path`` relative to the ``app`` package root."""

    relative = path.relative_to(APP_ROOT.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _package_for(path: Path, importing_module: str) -> str:
    """Python's own ``__package__`` value for the module at ``path``.

    A package's ``__init__.py`` IS the package: its ``__package__`` equals
    its own dotted name (already ``__init__``-stripped by
    ``_module_name_for``). A plain submodule's ``__package__`` is its
    dotted name with the trailing module component removed. Getting this
    wrong under-resolves every relative import in every ``__init__.py``
    (there is one at the root of every package this scans), silently
    mapping them to the *parent* package and letting a real violation slip
    through unflagged -- a false negative, not just a cosmetic mislabel.
    """

    if path.name == "__init__.py":
        return importing_module
    if "." not in importing_module:
        return importing_module
    return importing_module.rsplit(".", 1)[0]


def _resolve_relative_import(
    *, package: str, node_module: str | None, level: int
) -> str:
    """Resolve a (possibly relative) ``ImportFrom`` to a dotted module path.

    Mirrors ``importlib._bootstrap._resolve_name``: ``level`` dots strip
    ``level - 1`` trailing components from ``package`` (one dot means "this
    package", i.e. no stripping), then the imported name is appended.
    """

    if level == 0:
        return node_module or ""
    base = package.rsplit(".", level - 1)[0]
    return f"{base}.{node_module}" if node_module else base


def _imported_module_names(path: Path) -> set[str]:
    tree = _parse(path)
    importing_module = _module_name_for(path)
    package = _package_for(path, importing_module)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_relative_import(
                package=package,
                node_module=node.module,
                level=node.level,
            )
            if resolved:
                names.add(resolved)
            # ``from app.modules import tasks`` imports the submodule itself
            # as a name without it appearing in ``node.module``; record the
            # fully qualified submodule path for each imported name too.
            for alias in node.names:
                if resolved:
                    names.add(f"{resolved}.{alias.name}")
    return names


def _is_task_module_import(module_name: str) -> bool:
    return module_name == "app.modules.tasks" or module_name.startswith(
        "app.modules.tasks."
    )


def test_relative_imports_in_package_init_resolve_within_their_own_package() -> None:
    """Meta-test for the AST helper itself, not production code.

    ``app/workflows/voice_brain_dump/__init__.py`` imports its own siblings
    with single-dot relative imports (``from .confirmation import ...``).
    Those must resolve to ``app.workflows.voice_brain_dump.confirmation``,
    not ``app.workflows.confirmation`` -- a package's ``__init__.py`` IS
    that package, so a one-dot relative import stays inside it rather than
    stepping out to the parent. Getting this wrong would make every
    import-boundary check silently under-resolve ``__init__.py`` imports
    everywhere it scans, masking a real Task-repository/second-engine
    violation if one were ever added there.
    """

    init_path = VOICE_BRAIN_DUMP_ROOT / "__init__.py"
    resolved = _imported_module_names(init_path)
    assert "app.workflows.voice_brain_dump.confirmation" in resolved
    assert "app.workflows.voice_brain_dump.providers" in resolved
    assert "app.workflows.voice_brain_dump.task_port" in resolved
    # The old (incorrect) one-too-many-strip resolution must not appear.
    assert "app.workflows.confirmation" not in resolved
    assert "app.workflows.providers" not in resolved


def test_voice_brain_dump_workflow_never_imports_task_repository_or_service() -> None:
    """ADR-0001: the workflow crosses the Tasks boundary only through TaskPort.

    No file under ``app/workflows/voice_brain_dump/`` (including provider
    adapters) may import ``app.modules.tasks`` or any of its submodules --
    that would let the workflow reach ``TaskRepository``/``TaskService``
    directly instead of through the injected ``TaskPort`` adapter.
    """

    assert VOICE_BRAIN_DUMP_ROOT.is_dir(), "voice_brain_dump package moved or renamed"
    violations: dict[str, set[str]] = {}
    for path in _iter_python_files(VOICE_BRAIN_DUMP_ROOT):
        offending = {
            name
            for name in _imported_module_names(path)
            if _is_task_module_import(name)
        }
        if offending:
            violations[str(path.relative_to(APP_ROOT.parent))] = offending

    assert not violations, (
        "voice_brain_dump must cross the Tasks module boundary only through "
        f"TaskPort, never by importing app.modules.tasks directly: {violations}"
    )


def _provider_role_method_names(class_node: ast.ClassDef) -> set[str]:
    return {
        member.name
        for member in class_node.body
        if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _class_attribute_names(class_node: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for member in class_node.body:
        if isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name):
            names.add(member.target.id)
        elif isinstance(member, ast.Assign):
            names.update(
                target.id for target in member.targets if isinstance(target, ast.Name)
            )
    return names


def _defines_a_provider_role_port(class_node: ast.ClassDef) -> bool:
    methods = _provider_role_method_names(class_node)
    if methods & _STANDALONE_PORT_METHOD_NAMES:
        return True
    if _RECONCILER_METHOD_NAME in methods:
        return _RECONCILER_ROLE_ATTRIBUTE in _class_attribute_names(class_node)
    return False


def test_no_module_outside_voice_brain_dump_defines_a_second_voice_engine() -> None:
    """ADR-0002: fast/accurate STT and text-reconciler roles are singular.

    A future voice-led Weekly Review must reuse
    ``app.workflows.voice_brain_dump``'s ``FastSttPort``/``AccurateSttPort``/
    ``TextReconcilerPort`` contracts rather than defining a second,
    independent voice engine. This scans every module outside
    ``voice_brain_dump`` for a class that structurally matches one of those
    port contracts (by the distinctive method/attribute shape the real ports
    and adapters use in ``providers.py``), which would indicate a duplicate
    engine no matter what it is named.
    """

    offending: dict[str, list[str]] = {}
    for path in _iter_python_files(APP_ROOT):
        if VOICE_BRAIN_DUMP_ROOT in path.parents:
            continue
        tree = _parse(path)
        matches = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and _defines_a_provider_role_port(node)
        ]
        if matches:
            offending[str(path.relative_to(APP_ROOT.parent))] = matches

    assert not offending, (
        "Only app.workflows.voice_brain_dump.providers may define "
        f"fast/accurate-STT or text-reconciler provider ports: {offending}"
    )


def test_weekly_review_modules_reuse_the_shared_voice_workflow_if_present() -> None:
    """Forward guard: if/when a Weekly Review voice module is added anywhere
    under ``app/``, it must import the shared
    ``app.workflows.voice_brain_dump`` package rather than defining its own
    operation/provider machinery. Vacuously satisfied today because no such
    module exists yet; it activates the moment one is added."""

    weekly_review_files = [
        path
        for path in _iter_python_files(APP_ROOT)
        if "weekly_review" in path.name.lower()
        or "weekly_review" in {part.lower() for part in path.parts}
    ]
    missing_reuse = [
        str(path.relative_to(APP_ROOT.parent))
        for path in weekly_review_files
        if not any(
            name == "app.workflows.voice_brain_dump"
            or name.startswith("app.workflows.voice_brain_dump.")
            for name in _imported_module_names(path)
        )
    ]
    assert not missing_reuse, (
        "Weekly Review module(s) must import app.workflows.voice_brain_dump "
        f"to reuse its shared AsyncOperation substrate: {missing_reuse}"
    )
