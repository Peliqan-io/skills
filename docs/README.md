# Documentation

One folder per pattern. The [root README](../README.md) is the front door and only links here.

| Pattern | Docs | Build skill |
|---|---|---|
| Syncs | [syncs/](syncs/README.md) | `peliqan-sync` |
| Dashboards | [dashboards/](dashboards/README.md) | `peliqan-dashboard` |

## Adding a pattern

Adding a pattern takes four things:

1. **A build skill:** `skills/peliqan-<pattern>/`.
2. **A reference file in audit and in support:** `skills/peliqan-audit/references/<pattern>.md` and `skills/peliqan-support/references/<pattern>.md`, plus a row in the routing table of each `SKILL.md`.
3. **A docs folder:** `docs/<pattern>/README.md`, with images in `docs/<pattern>/images/`.
4. **One row** in the patterns table of the root README, one in the table above, and the new skill in `skills/peliqan-help/SKILL.md`.

## Page structure

Every `docs/<pattern>/README.md` uses the same sections, so readers who know one pattern find their way in the next:

1. **What it is**: one diagram plus the principles.
2. **When to use it**: good fit, better alternatives, before / after.
3. **How it works**: the mechanism, with one diagram.
4. **Using the skills**: what you need, then build, audit and support, plus pattern-specific safety rules.

Deeper material (requirements, risks, QA) goes in a separate page in the same folder.

Docs are for people; `SKILL.md` and `references/` are for Claude. The rules themselves live only in the skill. Docs explain them and link to them, but never copy them.

Keep pages system-neutral ("webshop", "ERP", "system A/B"). Name specific systems only in a "Supported systems" table.

## Diagram style

Diagrams are hand-written SVG, not Mermaid, so they look the same everywhere.

| Element | Style |
|---|---|
| Runs in Peliqan (data app, worker step, skill) | fill `#FDEEE2`, stroke `#E07B39` |
| Configuration | fill `#E9EEF4`, stroke `#5B6B80` |
| Data in the warehouse | fill `#FFFFFF`, stroke `#333` |
| External system | fill `#EEF0F3`, stroke `#C5CAD1` |
| Optional or a rule | fill `#FAFAFA`, dashed stroke `#BDBDBD` |
| Error or write-back path | stroke `#E07B39`; dashed for retries |
| Background | white card, `rx="10"`, stroke `#E3E3E3`, so it reads in dark mode too |

- Always end with a legend row.
- Use inline attributes, not a `<style>` block: some renderers ignore CSS in SVG.
- Font: `DejaVu Sans, Verdana, Segoe UI, Helvetica, Arial, sans-serif`. Titles 12–14px bold, labels 10px.
- Put an `alt` text on every `<img>` that describes what the diagram shows.
