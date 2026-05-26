# Visual Design Progress

This tracker captures the design review and implementation plan for the public web
experience. The goal is to keep the app credible as a network analysis tool while
making the core idea feel more distinctive: cultural proximity through podcast
appearances.

## Design Thesis

The site should feel like a cultural cartography tool, not a generic analytics
dashboard. Browse and ranking pages can stay quiet and utilitarian, but the core
surfaces, especially Six Degrees, Map, and Recommendations, should make paths,
clusters, and surprising adjacency feel alive.

## Current Strengths

- The information architecture matches the product loop: find paths, see the map,
  discover adjacent shows, browse people or podcasts, and inspect methods later.
- The light UI is readable and credible.
- The person/podcast color distinction gives graph data a useful semantic language.
- The homepage puts the path-finding action close to the top.
- Existing detail links, recommendations explanations, generated plots, and path
  results are strong foundations.

## Design Gaps To Track

1. [In progress] Reframe the visual identity around cultural cartography.
   - Use warmer page surfaces and clearer editorial hierarchy.
   - Keep dense data pages efficient, but make core network pages more memorable.
   - Avoid a generic sci-fi analytics look.
   - Keep interactive tools honest as data experiments, with polished workflow
     surfaces rather than marketing-style decoration.
   - Add a small network-style favicon so the browser tab carries the site identity.
   - Reuse the network mark in the global header so the brand is visual, not just
     text.
   - Add active navigation states so the current tool/section is always visible.
   - Add a restrained footer so pages end with project context and useful routes.
   - Use `/analysis/` for user-facing Analysis pages while preserving legacy
     `/advanced/` routes for compatibility.
   - Add cohesive focus states so keyboard interaction feels intentionally
     designed, not browser-default.

2. [Done] Replace or restyle the homepage hero experience.
   - Removed the dark generated hero image from the homepage background.
   - Removed the custom path-node scene after review because it felt too literal
     and last-minute.
   - Added a new generated hero image with realistic podcast equipment, a printed
     network map, and useful left-side negative space.
   - Let the path search, visual asset, and experiment positioning work together.

3. [Done] Make the path search feel like the primary command surface.
   - Stronger input grouping, labels, and example paths.
   - Make example paths read like stories to try.
   - Keep the first action fast and obvious.
   - Extend the same command-surface pattern to the podcast comparison workflow.

4. [Done] Give person and podcast detail pages stronger identity.
   - Add a compact summary band before dense tables.
   - Highlight network role, stats, hosts/guest context, and path actions.
   - Make detail pages feel like dossiers rather than raw database records.

5. [Done] Improve data-table scanning.
   - Align numeric columns and strengthen row hover/focus states.
   - Use badges for genres, roles, and entity types.
   - Preserve density while improving hierarchy.
   - Add table context and filter-bar surfaces to browse/ranking pages.

6. [In progress] Make Map and Six Degrees more immersive than browse pages.
   - Treat graph/path visuals and command surfaces as first-class experiment areas.
   - Keep the surrounding UI light enough that the visualizations stand out.
   - Align the Six Degrees path graphic palette with the warm site system instead
     of the old dark neon graph style.
   - Give Analysis/Map pages a stronger header, section navigation, and framed
     visualization blocks.

7. [In progress] Reduce visual sameness across cards, panels, pills, and tables.
   - Reserve panels for actual tools or grouped controls.
   - Use flatter page sections where possible.
   - Introduce a small set of reusable hero, command, dossier, and table patterns.
   - Move person/podcast detail pages toward dossier headers, stat bands, and
     flatter link lists instead of stacking panels everywhere.
   - Make Analysis cards and plot sections feel like distinct navigation and
     visualization surfaces.
   - Give Recommendations a distinct workflow header, summary strip, and clearer
     result-card metrics/actions.
   - Bring Compare Podcasts into the experiment-tool pattern with a command panel
     and result surface.
   - Add a shared footer pattern distinct from cards, panels, and data tables.
   - Replace clipped tab shapes with rounded segmented tab buttons.
   - Scope broad navigation styling to the global header and add component-level
     focus states to avoid future CSS leakage.

## Implementation Notes

- Prefer incremental Django template and CSS improvements before a frontend rewrite.
- Keep generated plot URLs and existing routes stable.
- Keep the UI accessible and readable on mobile.
- Use the current semantic colors as a starting point, but do not let the interface
  become a one-color teal theme.

## Hero Image Direction

The homepage needs a real visual asset, but it should not look like a generic neon AI
network dashboard or a last-minute diagram. It should make the project feel like a
polished, fun data experiment about podcast guest connections.

### Recommended Generation Prompt

Create a wide hero image for a website called "Six Degrees to Joe Rogan", an
interactive data experiment that maps how public figures connect through interview
podcast appearances. The image should feel like a sophisticated editorial data
visualization, not a sci-fi dashboard.

Composition: a warm, light-background studio desk viewed from slightly above, with a
few realistic podcast microphones, headphones, note cards, and a subtle printed
network map spread across the desk. The network map should show dots and connecting
lines between names and podcast titles, but the text should be mostly abstract or
unreadable except for a few short labels like "guest", "host", and "show". Include
soft shadows, tactile paper texture, and a calm sense of discovery.

Style: premium editorial illustration with realistic materials, clean data-design
details, restrained color palette, warm off-white background, teal and amber accents,
high-end magazine feature aesthetic, crisp but not sterile, inviting and intelligent.

Format: 16:9 landscape, lots of usable negative space on the left side for headline
text, visual interest concentrated on the right and lower-right. No dark neon
background, no cyberpunk, no glowing holograms, no futuristic HUD, no celebrity
portraits, no Joe Rogan likeness, no fake app screenshots, no messy tiny readable
text, no distorted microphones, no hands, no people.

### Short Variant

Wide 16:9 editorial hero image for an interactive podcast network data experiment:
realistic podcast microphones and headphones on a warm light desk, a subtle printed
network map with dots and connecting lines between guests, hosts, and shows, teal and
amber accents, premium magazine-style data visualization, negative space on the left
for headline text, no people, no celebrity likenesses, no neon sci-fi dashboard, no
futuristic HUD, no readable tiny text.

## Changelog

- 2026-05-25: Initial design critique captured.
- 2026-05-25: Replaced generated homepage art with a quieter custom path scene.
- 2026-05-25: Removed custom path scene and rewrote homepage around a stronger
  editorial promise.
- 2026-05-25: Added the new generated hero image and refreshed the Six Degrees
  page with an experiment-style command surface.
- 2026-05-25: Tightened homepage hero spacing and added filter/table context
  polish to browse and ranking pages.
- 2026-05-25: Retuned the Six Degrees path graphic from dark neon to warm paper,
  teal, and amber site colors.
- 2026-05-26: Strengthened person and podcast detail pages with dossier stat
  bands, clearer actions, and flatter contextual lists.
- 2026-05-26: Polished Analysis and Map pages with stronger headers, navigation,
  cards, and framed plot sections.
- 2026-05-26: Polished Recommendations as a workflow tool with summary counts,
  clearer result cards, and better control surfaces.
- 2026-05-26: Added a custom SVG favicon using the site network palette.
- 2026-05-26: Improved browse/ranking table scanning with explicit numeric
  alignment and semantic host/genre badges.
- 2026-05-26: Added active top-navigation states across tools, browse pages, and
  analysis sections.
- 2026-05-26: Polished Compare Podcasts with an experiment header, command panel,
  result panel, and numeric table alignment.
- 2026-05-26: Added a restrained shared footer with project context and links to
  core workflows and methods.
- 2026-05-26: Added `/analysis/` routes for user-facing Analysis pages and
  refreshed tab styling so selected tabs are not clipped.
- 2026-05-26: Reused the network favicon as a header brand mark and added a
  matching browser theme color.
- 2026-05-26: Scoped global navigation CSS to the header and added cohesive
  focus states for links, controls, cards, pills, and form fields.
