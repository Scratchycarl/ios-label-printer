from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from ios_label_printer.models import LabelTemplate

APP_DIR_NAME = "ios-label-printer"
DEFAULT_TEMPLATE_NAME = "default.json"


def package_data_text(name: str) -> str:
    return files("ios_label_printer").joinpath("data", name).read_text(encoding="utf-8")


def user_data_dir() -> Path:
    from os import getenv

    root = Path(getenv("APPDATA") or Path.home() / "AppData" / "Roaming")
    path = root / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_templates_dir() -> Path:
    path = user_data_dir() / "templates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_template(path: Path) -> LabelTemplate:
    return LabelTemplate.from_dict(load_json(path))


def save_template(path: Path, template: LabelTemplate) -> None:
    save_json(path, template.to_dict())


def bundled_default_template() -> LabelTemplate:
    return LabelTemplate.from_dict(json.loads(package_data_text("default_template.json")))


def ensure_user_default_template() -> Path:
    destination = user_templates_dir() / DEFAULT_TEMPLATE_NAME
    if not destination.exists():
        save_template(destination, bundled_default_template())
    return destination


def load_device_model_map() -> dict[str, str]:
    data = json.loads(package_data_text("device_models.json"))
    return {str(key): str(value) for key, value in data.items()}


def load_device_color_maps() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    data = json.loads(package_data_text("device_colors.json"))
    model_numbers = {
        str(key).upper(): str(value)
        for key, value in (data.get("model_numbers") or {}).items()
    }
    product_enclosure: dict[str, dict[str, str]] = {}
    for product, mapping in (data.get("product_enclosure") or {}).items():
        product_enclosure[str(product)] = {
            str(code): str(name) for code, name in (mapping or {}).items()
        }
    return model_numbers, product_enclosure
