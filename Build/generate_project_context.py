"""
Generate project documentation from the Order Orchestration codebase.

Outputs:

docs/PROJECT_CONTEXT.md
docs/AI_CONTEXT.md
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import yaml


# ROOT = Path(__file__).resolve().parent.parent
ROOT = Path(".")

SRC_DIR = ROOT / "src" / "order_orchestration"
DOCS_DIR = ROOT / "docs"

BUSINESS_RULES_FILE = (
    ROOT
    / "config"
    / "business_rules.yaml"
)


DOCS_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ==========================================================
# UTILITIES
# ==========================================================

def read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:
        return yaml.safe_load(file) or {}


def get_python_files() -> list[Path]:
    return sorted(
        SRC_DIR.rglob("*.py")
    )


# ==========================================================
# ENUM EXTRACTION
# ==========================================================

def extract_enums() -> dict:
    enums = {}

    for file in get_python_files():
        try:
            tree = ast.parse(
                file.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            continue

        for node in tree.body:
            if (
                isinstance(
                    node,
                    ast.ClassDef,
                )
            ):
                for base in node.bases:
                    if (
                        isinstance(
                            base,
                            ast.Name,
                        )
                        and base.id == "Enum"
                    ):
                        values = []

                        for child in node.body:
                            if isinstance(
                                child,
                                ast.Assign,
                            ):
                                for target in (
                                    child.targets
                                ):
                                    if isinstance(
                                        target,
                                        ast.Name,
                                    ):
                                        values.append(
                                            target.id
                                        )

                        enums[
                            node.name
                        ] = values

    return enums


# ==========================================================
# DATACLASSES
# ==========================================================

def extract_dataclasses() -> dict:
    dataclasses = {}

    for file in get_python_files():
        try:
            tree = ast.parse(
                file.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            continue

        for node in tree.body:
            if not isinstance(
                node,
                ast.ClassDef,
            ):
                continue

            is_dataclass = False

            for decorator in (
                node.decorator_list
            ):
                if isinstance(
                    decorator,
                    ast.Name,
                ):
                    if (
                        decorator.id
                        == "dataclass"
                    ):
                        is_dataclass = (
                            True
                        )

                if isinstance(
                    decorator,
                    ast.Call,
                ):
                    if (
                        isinstance(
                            decorator.func,
                            ast.Name,
                        )
                        and decorator.func.id
                        == "dataclass"
                    ):
                        is_dataclass = (
                            True
                        )

            if not is_dataclass:
                continue

            fields = []

            for child in node.body:
                if isinstance(
                    child,
                    ast.AnnAssign,
                ):
                    if isinstance(
                        child.target,
                        ast.Name,
                    ):
                        fields.append(
                            child.target.id
                        )

            dataclasses[
                node.name
            ] = fields

    return dataclasses


# ==========================================================
# WORKFLOWS
# ==========================================================

def extract_workflows() -> dict:

    workflow_dir = (
        SRC_DIR
        / "workflows"
    )

    workflows = {}

    if not workflow_dir.exists():
        return workflows

    for file in sorted(
        workflow_dir.glob("*.py")
    ):
        try:
            tree = ast.parse(
                file.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            continue

        funcs = []

        for node in tree.body:
            if isinstance(
                node,
                ast.FunctionDef,
            ):
                funcs.append(
                    node.name
                )

        workflows[
            file.name
        ] = funcs

    return workflows


# ==========================================================
# SCORING CONFIGS
# ==========================================================

def build_scoring_markdown(
    rules: dict,
) -> str:

    sections = []

    scoring_names = [
        "replenishment_moq_scoring",
        "zfmo_replenishment_moq_scoring",
        "zmso_colour_16_moq_scoring",
        "push_selection",
    ]

    for name in scoring_names:

        if (
            name
            not in rules
        ):
            continue

        section = [
            f"## {name}",
            "",
            "```yaml",
            yaml.dump(
                rules[name],
                sort_keys=False,
            ).strip(),
            "```",
            "",
        ]

        sections.extend(
            section
        )

    return "\n".join(
        sections
    )


# ==========================================================
# PROJECT CONTEXT
# ==========================================================

def build_project_context():

    rules = read_yaml(
        BUSINESS_RULES_FILE
    )

    enums = extract_enums()

    dataclasses = (
        extract_dataclasses()
    )

    workflows = (
        extract_workflows()
    )

    output = []

    output.append(
        "# ORDER ORCHESTRATION PROJECT CONTEXT\n"
    )

    output.append(
        "## Purpose\n"
    )

    output.append(
        """
Inventory allocation engine that executes:

- VOR
- ACC
- PUSH
- REPLENISHMENT

Sources:

- Parent RDC
- Cluster RDC
- PAN India RDC
- VEPDC
- GIT
"""
    )

    output.append(
        "\n## Current Replenishment Logic\n"
    )

    output.append(
        """
Colour codes 16-20 use two-pass execution.

PASS 1:

Parent-only allocation.

PASS 2:

GIT and alternatives.

ZFMO 16:
- Credit block ignored
- No safety stock deduction anywhere
- ZFMO colour-16 scoring

ZMSO 16:
- Credit block enforced
- Parent no safety stock deduction
- Alternative safety stock deducted
- ZMSO colour-16 scoring

ZFMO 17-20:
- Credit block ignored
- Parent no safety stock deduction
- Alternative safety stock deducted
- Standard scoring

ZMSO 17-20:
- Credit block enforced
- Parent no safety stock deduction
- Alternative safety stock deducted
- Standard scoring
"""
    )

    output.append(
        "\n## Enums\n"
    )

    for (
        enum_name,
        values,
    ) in enums.items():

        output.append(
            f"### {enum_name}"
        )

        output.append("")

        for value in values:
            output.append(
                f"- {value}"
            )

        output.append(
            "\n## Domain Models\n"
        )

    for (
        class_name,
        fields,
    ) in dataclasses.items():

        output.append(
            f"### {class_name}"
        )
        output.append("")

        for field in fields:
            output.append(
                f"- {field}"
            )

        output.append("")

    output.append(
        "\n## Workflows\n"
    )

    for (
        file_name,
        funcs,
    ) in workflows.items():

        output.append(
            f"### {file_name}"
        )

        output.append("")

        for func in funcs:
            output.append(
                f"- {func}()"
            )

        output.append("")

    output.append(
        "\n## Scoring Configuration\n"
    )

    output.append(
        build_scoring_markdown(
            rules
        )
    )

    output.append(
        "\n## Execution Defaults\n"
    )

    execution_defaults = (
        rules.get(
            "execution_defaults",
            {},
        )
    )

    output.append(
        "```yaml"
    )

    output.append(
        yaml.dump(
            execution_defaults,
            sort_keys=False,
        ).strip()
    )

    output.append(
        "```"
    )

    project_doc = (
        "\n".join(output)
    )

    (
        DOCS_DIR
        / "PROJECT_CONTEXT.md"
    ).write_text(
        project_doc,
        encoding="utf-8",
    )

    return project_doc


# ==========================================================
# AI CONTEXT
# ==========================================================

def build_ai_context():

    ai_context = """
# AI CONTEXT

Read this entire document before proposing
code changes.

Current replenishment logic:

- Colour 16-20 uses two-pass execution.

PASS 1:
Parent allocation only.

PASS 2:
GIT and alternatives.

ZFMO 16:
- Credit block ignored
- No safety stock deduction anywhere
- ZFMO scoring

ZMSO 16:
- Credit block enforced
- Parent no safety stock deduction
- Alternative safety stock deducted
- ZMSO colour-16 scoring

ZFMO 17-20:
- Credit block ignored
- Parent no safety stock deduction
- Alternative safety stock deducted

ZMSO 17-20:
- Credit block enforced
- Parent no safety stock deduction
- Alternative safety stock deducted

Missing Route:
- TransportMode.SURFACE
- SLA = 5

Missing SLA:
- SLA = 5

Missing RLT:
- RLT = 5

Current focus:
Replenishment execution,
two-pass orchestration,
MOQ allocation,
GIT allocation,
safety-stock handling,
and KPI reporting.
"""

    (
        DOCS_DIR
        / "AI_CONTEXT.md"
    ).write_text(
        ai_context,
        encoding="utf-8",
    )


# ==========================================================
# MAIN
# ==========================================================

if __name__ == "__main__":

    build_project_context()

    build_ai_context()

    print(
        "Generated:"
    )

    print(
        DOCS_DIR
        / "PROJECT_CONTEXT.md"
    )

    print(
        DOCS_DIR
        / "AI_CONTEXT.md"
    )