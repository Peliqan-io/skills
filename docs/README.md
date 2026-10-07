# Documentation

One folder per product. The [root README](../README.md) is the front door and only links here.

| Product | Docs | Build skill |
|---|---|---|
| Syncs | [syncs/](syncs/README.md) | `peliqan-sync` |

## Adding a product

Adding a product (for example dashboards) takes four things:

1. **A build skill:** `skills/peliqan-<product>/`.
2. **A reference file in audit and in support:** `skills/peliqan-audit/references/<product>.md` and `skills/peliqan-support/references/<product>.md`, plus a row in the routing table of each `SKILL.md`.
3. **A docs folder:** `docs/<product>/README.md`, with images in `docs/<product>/images/`.
4. **One row** in the products table of the root README, one in the table above, and the new skill in `skills/peliqan-help/SKILL.md`.

## Page structure

Every `docs/<product>/README.md` uses the same sections, so readers who know one product find their way in the next:

1. **What it is**: one diagram plus the principles.
2. **When to use it**: good fit, better alternatives, before / after.
3. **How it works**: the mechanism, with one diagram.
4. **Using the skills**: what you need, then build, audit and support, plus product-specific safety rules.

Deeper material (requirements, risks, QA) goes in a separate page in the same folder.

Docs are for people; `SKILL.md` and `references/` are for Claude. The rules themselves live only in the skill. Docs explain them and link to them, but never copy them.

Keep pages system-neutral ("webshop", "ERP", "system A/B"). Name specific systems only in a "Supported systems" table.

## Diagram style

Diagrams are hand-written SVG, not Mermaid, so they look the same everywhere.

| Element | Style |
|---|---|
| Runs in Peliqan (data app, worker step, skill) | fill `#FCEFE3`, stroke `#ED7D2B` (Peliqan orange) |
| Configuration | fill `#E9EEF4`, stroke `#34516E` |
| Data in the warehouse | fill `#FFFFFF`, stroke `#383838` |
| External system | fill `#EEF0F3`, stroke `#C5CAD1` |
| Optional or a rule | fill `#FAFAFA`, dashed stroke `#BDBDBD` |
| Error or write-back path | stroke `#ED7D2B`; dashed for a replay path |
| Background | white card, `rx="10"`, stroke `#E3E3E3`, so it reads in dark mode too |

- Always end with a legend row.
- Use inline attributes, not a `<style>` block: some renderers ignore CSS in SVG.
- Text: `#383838`, secondary `#6B6B6B`, orange text `#C8631A`.
- Font: `Roboto, Helvetica, Arial, sans-serif`. Titles 12–14px bold, labels 10px.
- Put an `alt` text on every `<img>` that describes what the diagram shows.
