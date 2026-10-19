"""Runtime translations loaded from the bundled offline JSON catalogs."""
import json
from importlib.resources import files


def _load(name):
    return json.loads(files("gaussianreadpro.resources.locales").joinpath(name).read_text(encoding="utf-8"))


CATALOGS = {"zh_CN": _load("zh_CN.json"), "en": _load("en_US.json")}


def translate(text, language):
    catalog = CATALOGS.get(language, CATALOGS["zh_CN"])
    return catalog.get(text, "\n".join(catalog.get(line, line) for line in text.split("\n")))


def source_text(text, language):
    """Return the catalog's source-language form for a displayed translation."""
    if language != "en":
        return text
    reverse = {}
    for source, translated in CATALOGS["en"].items():
        if isinstance(translated, str):
            reverse.setdefault(translated, source)
    return "\n".join(reverse.get(line, line) for line in text.split("\n"))


def diagnostic_text(code, language):
    return CATALOGS.get(language, CATALOGS["en"]).get("errors." + code, code)
