import json
import re

from .effects import REGISTRY, make
from .gpu import DATA, ROOT

PRESETS = ROOT / "presets"
USER = DATA / "presets" / "user"


def builtin():
    return json.loads((PRESETS / "builtin.json").read_text(encoding="utf-8"))


def load_all():
    """Built-in presets first, then user presets (presets/user/*.json)."""
    out = builtin()
    for f in sorted(USER.glob("*.json")):
        out.append(json.loads(f.read_text(encoding="utf-8")))
    return out


def build(preset):
    return [make(s["type"], s.get("params"), s.get("enabled", True)) for s in preset["steps"]]


def to_preset(name, steps):
    return {"name": name, "steps": [e.to_json() for e in steps]}


def save(name, steps):
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "preset"
    path = USER / f"{slug}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_preset(name, steps), indent=1), encoding="utf-8")
    return path


def process(g, steps, tex):
    for e in steps:
        if e.enabled and not e.error:
            try:
                tex = e.apply(g, tex)
            except Exception as ex:  # a broken step is shown in the UI and skipped, not fatal
                e.error = str(ex)
                print(f"[{e.type}] {ex}")
    return tex


USER_STYLES = USER / "styles.json"


def styles(type):
    """Built-in styles for an effect type, then the user's saved ones."""
    user = json.loads(USER_STYLES.read_text(encoding="utf-8")) if USER_STYLES.exists() else {}
    return {**REGISTRY[type].styles, **user.get(type, {})}


def save_style(effect, name):
    user = json.loads(USER_STYLES.read_text(encoding="utf-8")) if USER_STYLES.exists() else {}
    user.setdefault(effect.type, {})[name] = effect.v
    USER_STYLES.parent.mkdir(parents=True, exist_ok=True)
    USER_STYLES.write_text(json.dumps(user, indent=1), encoding="utf-8")
