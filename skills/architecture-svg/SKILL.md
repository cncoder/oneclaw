---
name: architecture-svg
description: Generate professional SVG architecture diagrams for GitHub README. Use when the user asks for an architecture diagram, system diagram, infra diagram, or wants to visualize project structure in a README. Also triggers on "画个架构图", "架构图", "system diagram", "infra overview", or any request to create visual documentation for a repo. Outputs a dark-theme SVG that renders natively on GitHub (no image hosting needed, works in private repos).
---

# Architecture SVG Generator

Generate professional dark-theme SVG architecture diagrams optimized for GitHub README rendering.

## When to Use

- User says "架构图", "画个架构图", "architecture diagram", "system diagram"
- Creating or updating README documentation for a project
- Visualizing infrastructure, service topology, or data flow
- Any request to make a project's architecture visual

## Process

### 1. Analyze the Project

Before drawing anything, understand the system:

```
- Read README.md, CLAUDE.md, main config files
- Identify layers: frontend, backend, database, external services, infra
- Identify key components within each layer
- Identify data flow directions (user → frontend → backend → DB, etc.)
- Note the tech stack for labels
```

### 2. Plan the Layout

Architecture diagrams work best as **layered horizontal bands** flowing top-to-bottom:

```
Layer 1: Clients / Users / Entry Points
Layer 2: Edge / CDN / Load Balancer  
Layer 3: Application / API
Layer 4: Core Logic / Agents / Workers
Layer 5: Data / Storage
Layer 6: External Services / APIs
```

Not every project has all layers. Skip what doesn't apply. The key principle: **data flows downward, responses flow upward**.

For each layer, identify 2-6 components. More than 6 per row gets cramped — group related items.

### 3. Generate the SVG

Write the SVG to `docs/architecture.svg` in the project repo (create `docs/` if needed).

#### Design System (MUST follow exactly)

Read `references/serverless-litellm.svg` and `references/hermesbot.svg` for the canonical style. Key rules:

**Canvas & Background:**
- ViewBox: width 900-960, height varies by complexity (500-700 typical)
- Background: `linearGradient` from `#0d1117` to `#161b22` (GitHub dark theme)
- Corner radius: `rx="16"` on background rect

**Typography:**
- Font: `-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif`
- Default size: `font-size="13"`
- Headers/titles: 14-16px, `font-weight="700"`
- Labels: 11-12px, `font-weight="600"`  
- Sub-labels: 9-10px, normal weight, color `#8b949e`
- All text uses `fill` not CSS `color`

**Color Palette:**
- Text primary: `#e6edf3`
- Text secondary: `#8b949e`
- Borders: `#30363d` (subtle), `#4cc9f0` (accent)
- Card backgrounds: `#21262d`
- Dashed borders for region/cloud containers: `stroke-dasharray="8,4"`

**Component Colors (use linearGradient top-to-bottom):**
- AWS / Infrastructure: `#ff9900` → `#e68a00` (orange)
- AI / LLM: `#7c3aed` → `#5b21b6` (purple)
- API / Core: `#4361ee` → `#3a0ca3` (blue)
- Database: `#4895ef` → `#3b48cc` (light blue)
- Risk / Security: `#ef4444` → `#b91c1c` (red)
- Execution / Action: `#f59e0b` → `#d97706` (amber)
- Frontend / UI: `#0ea5e9` → `#06b6d4` (cyan)
- Success / Green: `#2dd4bf` → `#14b8a6` (teal)

**Arrows:**
- Define markers in `<defs>`: open arrowheads, stroke-width 1.5
- Color-code arrows to match the flow type (data=cyan, API=orange, etc.)
- Use `<path>` with curves (`Q` quadratic) for non-straight connections
- `stroke-width="1.5"` for arrows, `1` or `1.2` for borders

**Component Boxes:**
- Rounded: `rx="8"` for components, `rx="10"` for major sections, `rx="14"` for containers
- Border: 1-1.2px stroke matching the gradient accent color
- Use emoji as visual anchors in labels: ☁ ⚡ 🧠 📊 🔒 🗄 📈 etc.

**Layout Rules:**
- Center-align the overall composition
- Consistent horizontal spacing (130-140px per component in a row)
- Vertical spacing: 15-20px between layers
- Use `text-anchor="middle"` for centered labels
- Two-line labels: component name (bold) + tech detail (muted, smaller)

#### Template Structure

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 HEIGHT" 
     font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif" 
     font-size="13">
  <defs>
    <!-- Arrow markers -->
    <!-- Gradient definitions for each component type -->
  </defs>
  
  <!-- Background -->
  <rect width="960" height="HEIGHT" rx="16" fill="url(#bgGrad)"/>
  
  <!-- Title (optional) -->
  
  <!-- Layer 1: Top -->
  <!-- Layer 2... -->
  <!-- Layer N: Bottom -->
  
  <!-- Legend / Tech Stack summary (optional, bottom bar) -->
</svg>
```

### 4. Update README

Replace the existing Architecture section (or add one) with:

```markdown
## Architecture

<p align="center">
  <img src="docs/architecture.svg" alt="Architecture" width="100%"/>
</p>

> One-line summary of the architecture.
```

If there's a detailed `docs/architecture.md`, link it:
```markdown
> Detailed architecture → [docs/architecture.md](docs/architecture.md)
```

### 5. Commit

```bash
git add docs/architecture.svg README.md
git commit -m "docs: add SVG architecture diagram"
git push origin main
```

## Quality Checklist

Before committing, verify:
- [ ] SVG renders in browser (`open docs/architecture.svg`)
- [ ] All text is readable (no overlapping, proper spacing)
- [ ] Color contrast passes (light text on dark backgrounds)
- [ ] Arrows clearly show data flow direction
- [ ] Component count per row ≤ 6
- [ ] No hardcoded sensitive info (IPs, keys, ARNs)
- [ ] `width="100%"` in README img tag for responsiveness

## Why SVG?

- Renders natively on GitHub (no external hosting, no broken images in private repos)
- Scales perfectly at any zoom level
- Dark theme matches GitHub's dark mode
- Version-controlled alongside code
- No build step needed
