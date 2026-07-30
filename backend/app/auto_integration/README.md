# Auto-integration backend

This package researches, reviews, and executes goal-tracking connectors.
Anthropic web search produces a constrained `DiscoveryDraft`; deterministic
server code compiles it into a `ConnectorManifest`. Research never installs or
executes a connector.

## Proposal lifecycle

1. `POST /api/integrations/proposals` starts a current-web research request.
2. The research draft, actual web-search result URLs, compiled manifest, model
   ID, and validation outcome are stored in PostgreSQL.
3. Safe drafts enter `ready_for_review`. Unsupported or unsafe output is kept
   as `invalid`, `no_match`, or `failed` for inspection.
4. A separate approve call revalidates and atomically installs the connector.
   Rejecting a proposal never installs anything.
5. A reviewer can replace a draft manifest before approval. Reviewed proposals
   are immutable.
6. An installed operation can be bound to one numeric goal. Executions append
   normalized measurements; goal progress is calculated from the current goal
   period using `sum`, `latest`, `average`, or `count`.

Audel exposes this lifecycle through Copilot tools. Research remains a proposal
until the user's current message explicitly approves installation. Approval can
install and bind a proposal in one turn; later manual, barcode, or image-driven
runs execute the binding and add a measurement. `scheduled` is stored as a
trigger preference, but no background scheduler is included yet.

## Phase-one safety contract

- HTTPS `GET` operations only.
- No authentication or secrets in manifests, parameters, or run payloads.
- Connector hosts are fixed at installation time and rechecked before requests.
- Private, loopback, link-local, and otherwise non-public IP addresses are denied.
- Redirects are never followed.
- Inputs and optional responses are validated with JSON Schema 2020-12.
- Responses must be JSON and are subject to time and decoded-size limits.
- External APIs are mocked in every test.
- Installing a connector and executing it are separate actions.
- Agent research is limited to five web searches per proposal.
- A proposed API must have web-search-backed documentation and source evidence,
  an identifiable open-source license, and no authentication.
- The model emits typed endpoint facts; server code creates JSON Schema and
  executable request definitions.

## API

- `GET /api/integrations/connectors`
- `GET /api/integrations/connectors/{slug}`
- `POST /api/integrations/connectors`
- `GET /api/integrations/proposals`
- `POST /api/integrations/proposals`
- `GET /api/integrations/proposals/{proposal_id}`
- `PUT /api/integrations/proposals/{proposal_id}/manifest`
- `POST /api/integrations/proposals/{proposal_id}/approve`
- `POST /api/integrations/proposals/{proposal_id}/reject`
- `GET /api/integrations/bindings`
- `POST /api/integrations/bindings`
- `POST /api/integrations/proposals/{proposal_id}/binding`
- `POST /api/integrations/bindings/{binding_id}/execute`
- `POST /api/integrations/execute`
- `GET /api/integrations/runs/{run_id}`
- `POST /api/integrations/measurements`
- `GET /api/integrations/goals/{goal_id}/measurements`

Research drafts and sources, manifests, JSON Schemas, request parameters, raw
responses, mapped responses, and measurement source data use PostgreSQL JSONB.
Stable identity, review status, timestamps, numeric measurements, units, and
foreign keys stay relational.
