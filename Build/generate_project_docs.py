from pathlib import Path
import inspect
import importlib
import os
import sys


# =====================================================
# CONFIG
# =====================================================

OUTPUT_DIR = Path(
    "Order_Orchestration_Documentation"
)

OUTPUT_DIR.mkdir(
    exist_ok=True
)

PROJECT_ROOT = Path(".")


# =====================================================
# HELPERS
# =====================================================

def write_md(
    filename: str,
    title: str,
    content: str,
):
    file_path = (
        OUTPUT_DIR / filename
    )

    with open(
        file_path,
        "w",
        encoding="utf-8",
    ) as file:
        file.write(
            f"# {title}\n\n"
        )
        file.write(content)

    print(
        f"Created: {file_path}"
    )


def safe_get_source(
    module_name: str,
    object_name: str,
):
    try:
        module = importlib.import_module(
            module_name
        )

        obj = getattr(
            module,
            object_name,
        )

        return inspect.getsource(
            obj
        )

    except Exception as exc:
        return (
            f"\nERROR:\n{exc}\n"
        )


# =====================================================
# 1. REPOSITORY STRUCTURE
# =====================================================

tree_lines = []

for root, dirs, files in os.walk(
    "src"
):
    level = root.count(
        os.sep
    )

    indent = "    " * level

    tree_lines.append(
        f"{indent}{os.path.basename(root)}/"
    )

    for file in files:
        if file.endswith(
            (
                ".py",
                ".yaml",
                ".yml",
            )
        ):
            tree_lines.append(
                f"{indent}    {file}"
            )

write_md(
    "01_Repository_Structure.md",
    "Repository Structure",
    "```text\n"
    + "\n".join(tree_lines)
    + "\n```",
)


# =====================================================
# 2. DOMAIN MODELS
# =====================================================

domain_content = []

models = [
    (
        "order_orchestration.domain.candidate",
        "CandidateSource",
    ),
    (
        "order_orchestration.domain.order",
        "OrderLine",
    ),
    (
        "order_orchestration.domain.decision",
        "SourceSelectionResult",
    ),
]

for (
    module_name,
    class_name,
) in models:

    domain_content.append(
        f"\n# {class_name}\n"
    )

    domain_content.append(
        "```python\n"
        + safe_get_source(
            module_name,
            class_name,
        )
        + "\n```"
    )

write_md(
    "02_Domain_Models.md",
    "Domain Models",
    "\n".join(
        domain_content
    ),
)


# =====================================================
# 3. EXECUTION RUNNER
# =====================================================

runner_source = safe_get_source(
    "scripts.run_unified_order_execution",
    "run_unified_order_execution",
)

write_md(
    "03_Execution_Runner.md",
    "Execution Runner",
    "```python\n"
    + runner_source
    + "\n```",
)


# =====================================================
# 4. REPLENISHMENT
# =====================================================

replenishment_source = (
    safe_get_source(
        "order_orchestration.workflows.replenishment",
        "process_replenishment_order",
    )
)

write_md(
    "04_Replenishment_Workflow.md",
    "Replenishment Workflow",
    "```python\n"
    + replenishment_source
    + "\n```",
)


# =====================================================
# 5. VOR
# =====================================================

vor_source = safe_get_source(
    "order_orchestration.workflows.vor",
    "process_vor_order",
)

write_md(
    "05_VOR_Workflow.md",
    "VOR Workflow",
    "```python\n"
    + vor_source
    + "\n```",
)


# =====================================================
# 6. PUSH
# =====================================================

push_source = safe_get_source(
    "order_orchestration.workflows.push",
    "process_push_order",
)

write_md(
    "06_Push_Workflow.md",
    "Push Workflow",
    "```python\n"
    + push_source
    + "\n```",
)


# =====================================================
# 7. TRANSPORT
# =====================================================

transport_content = []

for function_name in [
    "enrich_candidates_with_route_policy",
    "apply_route_and_sla_defaults",
]:
    transport_content.append(
        f"\n# {function_name}\n"
    )

    transport_content.append(
        "```python\n"
        + safe_get_source(
            "order_orchestration.transport.route_policy",
            function_name,
        )
        + "\n```"
    )

write_md(
    "07_Transport_Framework.md",
    "Transport Framework",
    "\n".join(
        transport_content
    ),
)


# =====================================================
# 8. RLT
# =====================================================

rlt_content = []

for function_name in [
    "enrich_candidates_with_rlt",
    "apply_rlt_defaults",
]:
    rlt_content.append(
        f"\n# {function_name}\n"
    )

    rlt_content.append(
        "```python\n"
        + safe_get_source(
            "order_orchestration.data.rlt_resolver",
            function_name,
        )
        + "\n```"
    )

write_md(
    "08_RLT_Framework.md",
    "RLT Framework",
    "\n".join(
        rlt_content
    ),
)


# =====================================================
# 9. YAML CONFIG
# =====================================================

yaml_sections = []

for yaml_file in (
    PROJECT_ROOT.rglob(
        "*.yaml"
    )
):
    yaml_sections.append(
        f"\n# {yaml_file}\n"
    )

    try:
        yaml_sections.append(
            "```yaml\n"
            + yaml_file.read_text(
                encoding="utf-8"
            )
            + "\n```"
        )

    except Exception as exc:

        yaml_sections.append(
            f"\nERROR: {exc}\n"
        )

write_md(
    "09_Configuration_Guide.md",
    "Business Rules Configuration",
    "\n".join(
        yaml_sections
    ),
)


# =====================================================
# 10. PROJECT CONTEXT TEMPLATE
# =====================================================

project_context = """
# Project Objective

Automated VECV Order Orchestration.

Execution Priority:

1. VOR
2. Replenishment
3. Push

# Current Enhancements

- Two-pass Replenishment execution
- Colour 16–20 logic
- ZFMO vs ZMSO handling
- Route/SLA/RLT defaulting
- MOQ aligned allocation
- Safety stock logic

# KPI Targets

- First Fill Rate
- Execution %
- Reduction in Black / Red / VOR
- Freight Impact
- Automation
"""

write_md(
    "10_Project_Context.md",
    "Project Context",
    project_context,
)

print()
print("=" * 50)
print(
    "Documentation generated successfully."
)
print(
    f"Location: {OUTPUT_DIR.resolve()}"
)
print("=" * 50)