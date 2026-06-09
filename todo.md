
## Recommended Medusa API changes for later

These changes belong in Medusa itself, not the MCP wrapper. They are intended to reduce MCP response sizes, reduce N+1 detail calls, and make OpenClaw/agent workflows more reliable.

### 1. Enriched anime search response

- [x] Add enriched anime search support to avoid calling `/anime/details` for every search candidate.

Current MCP/OpenClaw problem:

- Existing resolver calls `GET /api/v2/anime/search?q=<title>&indexer=myanimelist`.
- Search results may omit fields needed for reliable title matching and user-facing disambiguation.
- Resolver then performs one `GET /api/v2/anime/details?id=<MAL_ID>&source=myanimelist` call per candidate.
- This creates N+1 API calls and makes title resolution slower and more fragile.

Proposed API option A:

```http
GET /api/v2/anime/search?q=<title>&indexer=myanimelist&includeDetails=true&limit=10
```

Proposed API option B:

```http
GET /api/v2/anime/search?q=<title>&indexer=myanimelist&fields=animeId,malId,displayTitle,titleRomanji,titleEnglish,titleJapanese,titleSynonyms,directoryName,animeType,status,year,season,episodes,score,numListUsers,genres,studios,synopsis,imageUrl,url,matched
```

Response should be a JSON list or paginated object containing enough fields to resolve titles without additional detail calls:

```json
[
  {
    "animeId": 62076,
    "malId": 62076,
    "source": "myanimelist",
    "displayTitle": "Example Title",
    "titleRomanji": "Example Title",
    "titleEnglish": "Example English Title",
    "titleJapanese": "例のタイトル",
    "titleSynonyms": ["Alternate Title"],
    "directoryName": "Example Title",
    "animeType": "TV",
    "status": "Currently Airing",
    "year": 2026,
    "season": "SUMMER",
    "episodes": 12,
    "score": 7.82,
    "numListUsers": 12345,
    "genres": ["Action", "Fantasy"],
    "studios": ["Example Studio"],
    "synopsis": "Short or full synopsis...",
    "imageUrl": "https://...jpg",
    "url": "https://myanimelist.net/anime/62076/...",
    "matched": false
  }
]
```

Acceptance criteria:

- `includeDetails=true` or equivalent returns `titleEnglish`, `titleJapanese`, `titleSynonyms`, and `matched` when available.
- `limit` is supported so agents can request only the top N candidates.
- Missing fields should be `null` or empty arrays, not omitted inconsistently.
- Search remains backward-compatible when `includeDetails`/`fields` is omitted.
- `source`/`indexer` naming should be documented; ideally accept both or standardize one.

### 2. Server-side seasonal filtering

- [x] Add server-side filters to `GET /api/v2/anime/seasonal` so clients can request smaller, more relevant pages.

Current MCP/OpenClaw problem:

- Seasonal anime responses can be large enough to be truncated by MCP/OpenClaw clients.
- Current MCP tool fetches pages and applies filters locally.
- Many skipped entries could be filtered before crossing the API/MCP boundary.

Proposed endpoint shape:

```http
GET /api/v2/anime/seasonal?year=2026&season=SUMMER&source=myanimelist&sourceSort=anime_num_list_users&page=1&limit=25&animeType=TV&minNumListUsers=3000&excludeGenres=Kids,Boys%20Love&matched=false
```

Recommended query params:

| Param | Type | Notes |
| --- | --- | --- |
| `page` | int | 1-based page number. |
| `limit` | int | Results per page; document max. |
| `animeType` | string or CSV | Example: `TV`; compare case-insensitively. |
| `minNumListUsers` | int | Exclude low-popularity entries. |
| `includeGenres` | CSV/list | Optional include filter. |
| `excludeGenres` | CSV/list | Example: `Kids,Boys Love`; compare case-insensitively. |
| `matched` | bool | `false` returns anime not already present in Medusa. |
| `fields` | CSV/list | Optional response field projection to reduce payload size. |
| `firstSeasonOnly` | bool | Optional heuristic; see below. |

Optional `firstSeasonOnly=true` heuristic:

- Exclude synopsis/title patterns like `second season`, `third season`, `season 2`, `part 2`, `sequel to`, `continuation of`, `final part of`.
- This does not need to be perfect; if implemented, response should include filter metadata/reasons when possible.

Recommended response shape:

```json
{
  "items": [
    {
      "animeId": 62076,
      "displayTitle": "Example Title",
      "animeType": "TV",
      "numListUsers": 12345,
      "genres": ["Action", "Fantasy"],
      "matched": false
    }
  ],
  "page": 1,
  "limit": 25,
  "total": 80,
  "hasNextPage": true
}
```

Acceptance criteria:

- Filtering happens before pagination when possible.
- Response includes pagination metadata: `page`, `limit`, `total` if cheap/available, and `hasNextPage`.
- `fields` projection works with seasonal responses to reduce payload size.
- Filters are documented and case-insensitive where practical.
- Existing seasonal endpoint behavior remains backward-compatible when filters are omitted.

### 3. True bulk add endpoint

- [x] Add true bulk add endpoint to Medusa, returning per-item results instead of requiring one add call per anime.

Current MCP/OpenClaw problem:

- Seasonal bulk add currently loops over selected candidates and calls `POST /api/v2/anime/add` once per anime.
- Verification requires repeated detail checks.
- If one item fails, the client must manage partial failure behavior.

Proposed endpoint:

```http
POST /api/v2/anime/bulk-add
Content-Type: application/json
```

Request body:

```json
{
  "defaults": {
    "source": "myanimelist",
    "root_dir": "/media/videos/Anime",
    "anime": true,
    "scene": false,
    "status": "wanted",
    "initial_release_group": "SubsPlease",
    "release_group_fallback_days": 7,
    "fallback_release_groups": ["SubsPlease", "Erai-raws"]
  },
  "items": [
    {
      "anime_id": 62076
    },
    {
      "anime_id": 12345,
      "directory_name": "Custom Directory Name",
      "initial_release_group": "Erai-raws"
    }
  ],
  "dry_run": true,
  "verify": true
}
```

Response body:

```json
{
  "dryRun": true,
  "requested": 2,
  "successes": 1,
  "failures": 1,
  "results": [
    {
      "animeId": 62076,
      "success": true,
      "action": "would_add",
      "matched": false,
      "message": "Dry-run validation passed."
    },
    {
      "animeId": 12345,
      "success": false,
      "action": "skip",
      "matched": true,
      "error": "Series already exists in Medusa."
    }
  ]
}
```

Behavior/acceptance criteria:

- `dry_run=true` must perform validation without modifying Medusa.
- Each item can override defaults such as `directory_name`, `initial_release_group`, and `fallback_release_groups`.
- Endpoint must return per-item success/failure; one failure must not hide other item results.
- Duplicate/already-present anime should be reported explicitly, ideally as `matched=true` with `action=skip` or `already_exists`.
- `verify=true` should return post-add presence/matched status when feasible.
- Existing single-add endpoint remains unchanged and backward-compatible.
