# Phase 2H -- GitHub REST Provider Contract

**Status:** `IMPLEMENTED_DOCUMENTED_ONLY`. Verified on 2026-10-01 against the
official documentation. No live request has been observed; the live test is
gated behind `RUN_GITHUB_PRIOR_ART_TESTS=1`.

**Sources (official only):**

- https://docs.github.com/en/rest/search/search
- https://docs.github.com/en/rest/repos/repos#get-a-repository
- https://docs.github.com/en/rest/repos/contents#get-a-repository-readme
- https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api

Connector: `src/research/open_source/github.py` (`GitHubRestProvider`).
Constants: `src/research/discovery/capabilities.py`. Request contract tests:
`tests/test_product_oss_provider_contracts.py`.

## Headers

| header | value |
|---|---|
| `Accept` | `application/vnd.github+json`, or `application/vnd.github.text-match+json` for code search fragments |
| `X-GitHub-Api-Version` | `2026-03-10` |
| `Authorization` | `Bearer <token>`, only when a token is configured |

## Operations

| operation | endpoint | auth | fields used |
|---|---|---|---|
| repository search | `GET /search/repositories?q&per_page(<=100)&page` | optional | `total_count`, `incomplete_results`, `items[].id/node_id/full_name/html_url` |
| code search | `GET /search/code?q&per_page&page` | **required** | `items[].path/sha`, `items[].repository.id/node_id/full_name`, `text_matches[].fragment` |
| repository metadata | `GET /repos/{owner}/{repo}` | optional | `id`, `node_id`, `full_name`, `fork`, `parent`, `source`, `mirror_url`, `template_repository`, `archived`, `disabled`, `visibility`, `default_branch`, `license.spdx_id/key/name`, `topics`, `language`, `description`, `created_at`, `updated_at`, `pushed_at`, `stargazers_count`, `forks_count`, `watchers_count` |
| README | `GET /repos/{o}/{r}/readme[?ref]` | optional | `path`, `sha`, `size`, `encoding=base64`, `content` |
| manifest | `GET /repos/{o}/{r}/contents/{path}[?ref]` | optional | as README (inline content is empty above 1 MB) |
| releases | `GET /repos/{o}/{r}/releases?per_page` | optional | `id`, `tag_name`, `created_at`, `published_at`, `draft`, `prerelease` |
| head commit | `GET /repos/{o}/{r}/commits?sha&per_page=1` | optional | `sha`, `commit.author.date`, `commit.committer.date` |

Renamed or transferred repositories redirect (301). A redirect is followed only
to another `https://api.github.com/` URL. Any other target is `FETCH_UNSAFE`.
Identity is always the returned numeric `id`.

## Pagination and limits

- `per_page` is at most 100.
- At most 1,000 results per search. A `total_count` above what was fetched
  (including above the cap) is recorded as a provider remainder, so the search
  reads `PARTIAL_PROVIDER_LIMIT`.
- `incomplete_results: true` (provider timeout) also reads partial.
- Primary limits are 60 requests/hour unauthenticated and 5,000/hour
  authenticated.
- Search limits are 10/min unauthenticated and 30/min authenticated; code
  search is 10/min.
- Code search covers the default branch only, for files under 384 KB.

## Error classification

| response | kind | retried |
|---|---|---|
| 401 | `AUTHENTICATION_ERROR` | no |
| 403 with `retry-after` or `x-ratelimit-remaining: 0` | `RATE_LIMITED` | yes (bounded, honours `retry-after`) |
| 403 otherwise | `AUTHENTICATION_ERROR` | no |
| 429 | `RATE_LIMITED` | yes |
| 400 / 422 | `INVALID_QUERY` | no |
| 404 | `UNSUPPORTED_OPERATION` | no |
| 5xx | `PROVIDER_ERROR` | yes |
| timeout / connection | `TIMEOUT` / `CONNECTION_ERROR` | yes |
| malformed JSON | `PARSE_ERROR` | no |

A response body is never echoed into an error, and the token never appears in
a URL, a `repr` or the run.
