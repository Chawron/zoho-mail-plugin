"""Validate plugin.json and mcp.json: schema conformance plus Rakazo's semantic rules.

    uv run --with jsonschema --with httpx python check_manifests.py

Semantic rules checked here (from https://rakazo.com/docs/build-a-plugin/):
  - manifest $schema versions match between the two files
  - name: 1-64 lowercase letters/digits/dots/hyphens, starts and ends alphanumeric,
    no "--" or ".."
  - MCP entries carry only type, url and headers
  - no ${VAR} placeholders and no credential-shaped values in url or headers
"""

import json
import pathlib
import re
import sys

import httpx
from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parent
NAME_RE = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
SECRET_HEADER_RE = re.compile(r"authorization|api[-_]?key|token|secret|password", re.I)
PLACEHOLDER_RE = re.compile(r"\$\{[A-Za-z0-9_]+\}")


def schema_errors(filename: str) -> list[str]:
    document = json.loads((ROOT / filename).read_text())
    url = document["$schema"]
    schema = httpx.get(url, timeout=30.0, follow_redirects=True)
    schema.raise_for_status()
    validator = Draft202012Validator(schema.json())
    return [
        f"{filename}: {'/'.join(map(str, error.path)) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(document), key=str)
    ]


def semantic_checks() -> list[str]:
    problems: list[str] = []
    plugin = json.loads((ROOT / "plugin.json").read_text())
    mcp = json.loads((ROOT / "mcp.json").read_text())

    def spec_version(url):
        parts = url.split("/")
        return parts[-2] if len(parts) > 2 else url

    if spec_version(plugin["$schema"]) != spec_version(mcp["$schema"]):
        problems.append(
            "plugin.json and mcp.json declare different Agent Plugins versions: "
            + spec_version(plugin["$schema"]) + " vs " + spec_version(mcp["$schema"])
        )

    name = plugin.get("name", "")
    if not NAME_RE.match(name) or len(name) > 64:
        problems.append(f"plugin name is not a valid slug: {name!r}")

    for server_name, entry in mcp.get("mcpServers", {}).items():
        extra = set(entry) - {"type", "url", "headers"}
        if extra:
            problems.append(f"server {server_name!r} has unsupported keys: {sorted(extra)}")
        if entry.get("type") not in ("streamable-http", "sse"):
            problems.append(f"server {server_name!r} type must be streamable-http or sse")
        url = entry.get("url", "")
        if PLACEHOLDER_RE.search(url):
            problems.append(f"server {server_name!r} url contains a ${{VAR}} placeholder")
        if not url.startswith("https://"):
            problems.append(f"server {server_name!r} url must be HTTPS: {url!r}")
        if "key=" in url.lower() or "token=" in url.lower():
            problems.append(f"server {server_name!r} url looks like it carries a credential")
        for header, value in (entry.get("headers") or {}).items():
            if SECRET_HEADER_RE.search(header) or SECRET_HEADER_RE.search(str(value)):
                problems.append(
                    f"server {server_name!r} header {header!r} looks like a credential; "
                    "credentials belong in Rakazo > Manage MCP servers > Advanced"
                )
            if PLACEHOLDER_RE.search(str(value)):
                problems.append(f"server {server_name!r} header {header!r} uses a placeholder")

    skill = ROOT / "skills" / "zoho-mail" / "SKILL.md"
    if not skill.exists():
        problems.append("skills/zoho-mail/SKILL.md is missing")
    else:
        front = skill.read_text().split("---")[1] if skill.read_text().startswith("---") else ""
        if "name:" not in front or "description:" not in front:
            problems.append("SKILL.md frontmatter needs both name and description")
    return problems


def main() -> int:
    errors = []
    for filename in ("plugin.json", "mcp.json"):
        try:
            found = schema_errors(filename)
        except httpx.HTTPStatusError as exc:
            found = [f"{filename}: schema not fetchable ({exc.response.status_code})"]
        errors.extend(found)
        if not found:
            print(f"OK   {filename} matches its published schema")
    errors.extend(semantic_checks())

    if errors:
        print("\n".join(f"FAIL {e}" for e in errors))
        return 1
    print("OK   names, server entries, headers and skill files follow the plugin rules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
