# ADR-002: Relational Metadata and Junction Tables (Authors, Categories, Genres, Story_Genres)

## Status
Accepted

## Date
2026-08-18

## Context
Comics crawled from multiple sites have varied metadata:
- Authors (often single or unknown).
- Categories / Genres (often comma-delimited list like "Action, Adventure, Shounen").
- Descriptions.
- Source URLs & Crawler run performance logs.

Supabase database contains normalized tables: `authors`, `categories`, `genres`, `tags`, `stories`, `crawler_sources`, `crawler_runs`.

## Decision
1. **Metadata Scraping**: Scrape author, category string, and description using site-specific selectors, stripping prefixes and colons.
2. **Intermediate Persistence**: Persist metadata into `meta.json` within each comic download directory.
3. **Lookup & FK Population**:
   - `authors`: Insert if missing, link `author_id` on `stories`.
   - `categories`: Insert primary category if missing, link `category_id` on `stories`.
   - `genres`: Parse all comma-separated genres, insert into `genres` table if missing.
   - `story_genres`: Maintain many-to-many links between `stories(id)` and `genres(id)`.
4. **Audit & Runs**: Log crawler run metrics (items seen, items created, duration) to `crawler_runs`.

## Alternatives Considered

### 1. Store Genres as Raw Text Column Only
- **Pros**: Zero join tables.
- **Cons**: Cannot filter/query comics by genre efficiently, no relational constraints.
- **Rejected**: Multi-genre discovery is a core requirement for frontend reader apps.

## Consequences
- Clean normalized relational model.
- Backward-compatible: Legacy text `category` column remains populated alongside `story_genres`.
- RLS enabled with public select policies on all metadata tables.
