from jinja2 import Environment, FileSystemLoader
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent / "terraform/templates"
OUTPUT_DIR   = Path(__file__).parent / "terraform/generated"

def generate_template(
    provider: str,       # "aws" | "openstack"
    resource_type: str,  # "object_storage" | "database" | ...
    context: dict,       # tenant_id, region, etc.
) -> Path:
    """
    Render Jinja2 template → trả về path của file .tf đã generate.
    """
    template_path = TEMPLATE_DIR / provider / f"{resource_type}.tf.j2"
    
    if not template_path.exists():
        raise FileNotFoundError(
            f"No template for provider={provider}, resource={resource_type}"
        )

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR / provider)))
    tmpl = env.get_template(f"{resource_type}.tf.j2")
    rendered = tmpl.render(**context)

    # Output vào thư mục riêng theo tenant
    out_dir = OUTPUT_DIR / provider / context["tenant_id"]
    out_dir.mkdir(parents=True, exist_ok=True)

    out_file = out_dir / "main.tf"
    out_file.write_text(rendered)

    return out_file