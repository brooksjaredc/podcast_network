# Legacy Conversion Notes

The application runtime is now database-backed:

- Explorer pages route through `web/explorer/db_views.py`.
- Path lookup uses `database_six_degrees_graph()`.
- Advanced prediction tables read `FutureLinkPredictionRun` and `FutureLinkWeeklyAuditRun`.
- The CLI `path` command initializes Django and reads the catalog database.

Remaining legacy code:

- Explicit migration/import utilities such as `import_legacy_feeds` remain for one-off data
  migration from the old projects. They are not part of the web runtime, CLI path lookup,
  weekly default pipeline, graph construction, prediction pages, or plot generation.
