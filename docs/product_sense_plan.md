# Product Sense Plan

This plan captures the product review from May 25, 2026, so the strongest ideas do
not get lost while implementation continues.

## Product Thesis

The product is strongest when it helps people explore cultural proximity through
podcast appearances. The core loop should be: find paths, see the network, compare
shows or people, discover adjacent podcasts, then inspect the methodology only when
needed.

## Priority To-Dos

1. [Done] Promote the network plots into a first-class Network Map feature.
   - Add a top-level Map entry point.
   - Put the podcast graph and people graph together with clearer framing.
   - Keep the existing advanced plot asset URLs working.

2. [Done] Replace "Advanced" as a user-facing concept.
   - Rename the analysis hub around user intentions: Map, Rankings/metrics, Trends,
     Categories, Methods, Experimental Predictions.
   - Avoid making it feel like a miscellaneous implementation folder.

3. [Done] Reorder navigation around user jobs.
   - Lead with Six Degrees, Map, Recommendations, and Rankings.
   - Keep Podcasts and People as browse/reference tools.
   - Move Common Guests out of top-level prominence over time.

4. [In progress] Improve first-time empty states.
   - Recommendations should suggest starter searches or example podcasts.
   - Common Guests should explain the comparison job and ideally be reachable from
     podcast detail pages.

5. [Done] Make predictions feel appropriately experimental.
   - Rename "Predicted Guests" and "Podcast Predictions" to network-based fits.
   - Keep caveats close to prediction surfaces.
   - Add "why" explanations when prediction features support it.

6. [Done] Remove internal/database language from user-facing detail pages.
   - Hide or de-emphasize database status unless viewing a developer/admin mode.
   - Use that screen real estate for network value: rankings, paths, fits, or related
     shows.

7. [Done] Tighten rankings and metric comprehension.
   - Keep the ranking table prominent.
   - Move definitions and distributions closer to the metrics they explain.
   - Use concise labels and tooltips/help text instead of long up-front explanation.

8. [Done] Add filters to browse pages.
   - Podcasts should support search, category, active-only, and sort controls.
   - People should support better search and ranking pivots.

## Suggested Information Architecture

- Six Degrees
- Map
- Recommendations
- Rankings
- Podcasts
- People
- Analysis

Secondary or contextual surfaces:

- Compare podcasts/Common Guests, preferably launched from podcast pages.
- Trends, Categories, Methods, and Experimental Predictions inside the Analysis area.

## Completed Implementation Notes

- Added `/map/` as a first-class map entry point.
- Replaced the old Advanced landing page with an Analysis Guide.
- Moved Methods into the Analysis area instead of making it the top-level destination.
- Reordered top navigation around user jobs.
- Added starter searches and global genre filters to Recommendations.
- Added search, sort, genre, and activity controls to browse pages.
- Renamed prediction surfaces to network-based fits and added tabbed explanation views.
- Added compact "why" explanations to prediction tables on person and podcast detail pages.
- Linked Rankings to metric distribution charts and added recovery copy for empty searches.
- Moved Six Degrees date filters behind an advanced disclosure.

## Implementation Notes

- Preserve `/advanced/plots/...` because generated Plotly artifacts and tests already
  depend on that route.
- Prefer incremental improvements that make the current Django templates clearer before
  investing in a larger frontend rewrite.
- Keep anything that already works: the path result, recommendation explanations, entity
  detail links, and generated plot assets are all useful foundations.
