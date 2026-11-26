#!/usr/bin/env python3
# Assemble l'interface sans npm ni framework.
#
# Sources maintenables : web/pages/, web/js/ et web/css/ (ordre dans web/source_manifest.json).
# Fichiers générés : web/index.html, web/app.js et web/style.css (ceux que le serveur envoie). Ne pas les modifier à la main.
# À relancer après chaque modification d'une source ; les tests le relancent aussi eux-mêmes.

# ======================== IMPORTS ========================
import json
from pathlib import Path
# =================================================


# ======================== CONFIGURATION ========================
ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
# =================================================


# ======================== ASSEMBLAGE ========================

# Insère chaque page dans la disposition (layout.html) à son emplacement
def build_html(manifest):
    html = (WEB / "layout.html").read_text(encoding="utf-8")
    for name in manifest["pages"]:
        placeholder = f"<!-- GENTLESEED_PAGE:{name} -->"
        if html.count(placeholder) != 1:
            raise ValueError(f"Page placeholder missing or duplicated: {name}")
        body = (WEB / "pages" / name / "index.html").read_text(encoding="utf-8").rstrip("\n")
        html = html.replace(placeholder, body)
    (WEB / "index.html").write_text(html, encoding="utf-8")
    print(f"[build] web/index.html written ({len(manifest['pages'])} pages)")


# Concatène les sources JavaScript ou CSS dans un seul fichier
def build_bundle(manifest, key, target):
    sources = manifest[key]
    content = "".join((WEB / path).read_text(encoding="utf-8") for path in sources)
    (WEB / target).write_text(content, encoding="utf-8")
    print(f"[build] web/{target} written ({len(sources)} files)")


def build():
    print("[build] Assembling the interface…")
    manifest = json.loads((WEB / "source_manifest.json").read_text(encoding="utf-8"))
    build_html(manifest)
    build_bundle(manifest, "scripts", "app.js")
    build_bundle(manifest, "styles", "style.css")
    print("[build] Done: pages, JavaScript and CSS assembled")
# =================================================


if __name__ == "__main__":
    build()
