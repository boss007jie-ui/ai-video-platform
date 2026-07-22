# Contract Change Request: Register Eighth Public Skill

Request ID: `CR-FT-06-001-A`
Owner requested: `codex-00`
Requester: `codex-06`
Status: `OPEN`

## Use case

Codex-06 must issue independent acceptance verdicts for all eight public Skills. The shared
`REGISTERED_SKILL_IDS` set currently contains seven IDs and omits
`viral-research-asset-collection`, so a `TaskSpec` requesting the approved eighth Skill is
rejected before an acceptance suite can exercise its public Interface.

## Requested shared change

Add only `viral-research-asset-collection` to the shared public Skill identity allowlist and
its producer/consumer permission projections where required. Do not add or rename a
Foundation payload Contract ID.

Foundation Registry must remain exactly:

- one Envelope schema identity;
- eleven payload Contract IDs.

## Compatibility

This is an additive public Skill identity registration. Existing seven-Skill TaskSpecs remain
valid. Unsupported names remain rejected. No payload schema version changes are requested.

## Required fixtures/tests

- positive TaskSpec fixture with `viral-research-asset-collection`;
- negative fixture with an unknown Skill ID;
- producer identity test for the eighth Skill runtime;
- registry test proving the Foundation 1+11 identity set is unchanged.

## Producer and consumers

Producer/consumer permissions must follow the approved Viral Research Interface and Shared
Contracts ownership rules. This request does not authorize a Provider, Apify, network,
download, Research Library, or business artifact schema.

## Alternative

Keeping a test-local identity would let synthetic Integration tests run but would diverge
from Shared Contract validation; Codex-06 therefore does not implement that workaround.
