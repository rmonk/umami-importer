# umami.recipes — reverse-engineered notes and chosen approach

Umami.recipes has no published API. This documents what was reverse-engineered
from the Chrome extension and a HAR capture of real account activity, and why
the tool ended up using umami's own import pipeline (via a relay page) rather
than writing into umami's database directly.

## Chosen approach: relay through umami's own importer

The Chrome extension does no recipe parsing itself. It calls
`GET https://www.umami.recipes/api/can-import?url=<url>` for a preview, then
opens `https://www.umami.recipes/import?url=<url>`, which parses that URL's
HTML server-side (via schema.org/JSON-LD `Recipe` markup) and lets the user
confirm before saving. This is also exactly what the "official" import
feature does when a user pastes a URL directly — and it's the part that
"often fails," presumably because many recipe sites publish incomplete or
malformed structured data.

Rather than reverse-engineer umami's private database writes (see
"Investigated and not used" below), this tool extracts a recipe robustly
(schema.org first, Claude fallback for messy HTML or PDF text — see
`app/extract_url.py` / `app/extract_pdf.py`), **re-renders it as a clean,
minimal HTML page carrying complete, well-formed schema.org/JSON-LD**
(`app/render_recipe_html.py`), publishes that page to a public GitHub Pages
repo (`app/publish_recipe.py`), and hands the user
`https://www.umami.recipes/import?url=<relay page>` — the exact same URL
scheme the extension itself constructs. umami's own importer then does the
rest, using its own supported, app-store-approved pipeline.

This was verified empirically: a test page with clean JSON-LD published to
`https://rmonk.github.io/umami-recipe-relay/recipes/test-probe.html` was
correctly parsed by the real `/api/can-import` endpoint, matching umami's
internal rich-text schema field-for-field (ingredients/directions as
paragraph/text nodes, servings, activeTime/totalTime, image). No domain
allowlist or other restriction was encountered.

**Relay repo**: `github.com/rmonk/umami-recipe-relay`, public, GitHub Pages
serving from `main` branch root at `https://rmonk.github.io/umami-recipe-relay/`.
Pages are published via the GitHub Contents API (`PUT
/repos/{repo}/contents/{path}`) with a bearer token in `GITHUB_TOKEN` — not
git/SSH — so the container doesn't need any git tooling or credentials beyond
that one token. Recipe pages get a random unlisted slug
(`recipes/<random-slug>.html`); nothing links to them, so they aren't
discoverable even though the repo is public.

## Investigated and not used: writing directly into umami's Firestore

For reference, in case umami's importer ever fails on our clean relay pages
too and a more invasive approach is needed later. **Not implemented; no code
in this repo depends on this.**

Umami is built on Firebase project `umami-api` (storage bucket
`umami-api.appspot.com`; the project's web API key and app id are visible in
umami.recipes' own public JS bundle if this is ever picked back up — omitted
here since they trip secret scanners despite not being sensitive, and
nothing in this repo uses them). The app reads/writes most data **directly against
the Firestore REST API** (`https://firestore.googleapis.com/v1/projects/umami-api/databases/(default)/documents:*`),
authorized with a Firebase ID token (`Authorization: Bearer <idToken>`),
enforced by Firestore security rules scoped to the signed-in user. A separate
gRPC-Web service (`umami.AppService` at `POST /api/rpc`, `Content-Type:
application/grpc-web-text`, header `id-token: <idToken>`) handles
server-side-only operations: `ImportRecipeFromURL`/`CanImportRecipeFromURL`
(the importer above), photo processing (`AddRecipePhotos`,
`OptimizeRecipePhotos`), sharing/invitations, and account management.

Auth uses Google Sign-In, which isn't practical to script headlessly
(popup-based federation flow, no exposed OAuth client id). The viable path
would be a one-time interactive bootstrap (open a real browser, let the user
sign in with Google, capture the resulting Firebase `refreshToken` from the
`accounts:signInWithIdp` network response or IndexedDB), then headless
refresh via `POST https://securetoken.googleapis.com/v1/token?key=<apiKey>`
for every later run.

A real `umami.Recipe` document write (captured from the HAR) has this shape:

| field | type | notes |
|---|---|---|
| `id` | string | same as the document id |
| `recipeBookId` | string | target recipe book |
| `created`, `updated` | timestamp | RFC3339 |
| `name` | string | recipe title |
| `servings` | string | free text, e.g. `"1 cup"` |
| `activeTime`, `totalTime` | string | free text, often empty string |
| `ingredients`, `directions`, `notes` | rich-text tree | Lexical-style: `{root: {}, children: [{paragraph: {}, children: [{text: {text: "<line>"}, children: []}]}]}`, one paragraph per line |
| `nutritionInformation`, `tags`, `memberRatings` | map | empty `{}` in observed sample |
| `photos` | array of `{image: {path, width, height, mime, blurDataUrl}}` | `path` is a Storage path `recipes/<recipeId>/images/<imageId>`; served via `GET /api/image/recipes/<id>/images/<imageId>`, a proxy in front of Storage, not a public Storage URL |
| `photoCount` | integer | matches `len(photos)` |
| `importUrl` | string or null | source URL, or `null` for non-URL imports |
| `public` | bool | `false` for imports |

Whether Firebase Storage security rules would allow a client to write
directly to `recipes/<id>/images/<imageId>` with just an ID token was never
tested. If not, the only path would be reverse-engineering the minimal
protobuf encoding for `AddRecipePhotos`/`OptimizeRecipePhotos` — the field
descriptors are recoverable from the app's JS bundles if this is ever needed.
Listing the user's recipe books was also never confirmed: the app fetches
them over a realtime Firestore Listen stream a HAR export doesn't capture, so
the query shape (likely `collaboratorIds array-contains <uid>` or similar) is
unknown.
