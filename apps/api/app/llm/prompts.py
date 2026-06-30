from functools import lru_cache
from pathlib import Path

_PROMPT_DIR = Path(__file__).resolve().parents[1] / "resources" / "prompts"


@lru_cache
def load_prompt_template(name: str) -> str:
    path = _PROMPT_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, values: dict[str, object]) -> str:
    prompt = load_prompt_template(name)
    for key, value in values.items():
        prompt = prompt.replace(f"{{{{ {key} }}}}", str(value))
    return prompt
