# SDK contract metadata

`sdk.json` contains the checked-in operation metadata and error-family mapping
used by this client. The runtime contract module is generated from this file
without network access or a checkout of another repository.

This is SDK compatibility metadata, not a copy of the server implementation or
a complete OpenAPI specification. Historical error mappings remain so older
responses keep their exception families. They do not grant access to endpoints.

Review changes against the public client contract at
https://test-api.spavik.co/openapi.json, then regenerate and run the contract
check. Do not edit the generated runtime module directly. Tests use the local
simulated API and never need a production key or a private repository.
