# Synthesis v1.2 — model proposal audit

**UNVALIDATED MODEL PROPOSAL — NOT A COMPILED DICTIONARY.**
Software checks assess formatting, evidence and references, not biological correctness.

Completion: success; JSON valid: True; schema valid: True; proposal checks passed: True.

## Primary anatomical terms

### anal — p1

[proposed; scientifically unvalidated] primary

Rationale: Synthetic proposed anatomical organization; requires review\.

- Evidence o1: match "anal"; source "anal"; resolved [0:4 in 0:4]; extractor ollama:fixture; source src1.

Local contextual expressions:
- **anal entire** — Observed descriptive expression attached provisionally for this fixture\.
- Evidence o2: match "anal entire"; source "anal entire"; resolved [0:11 in 0:11]; extractor ollama:fixture; source src1.

Associated indexed compounds: none.

### spine — p3

[proposed; scientifically unvalidated] primary

Rationale: Synthetic proposed anatomical organization; requires review\.

- Evidence o5: match "spine"; source "spine"; ambiguous [28:33 in 28:33; 64:69 in 64:69]; extractor ollama:fixture; source src1.

Local contextual expressions: none.

#### tail spine — c2

[proposed; scientifically unvalidated] compound

Rationale: Synthetic proposed anatomical organization; requires review\.

Associated primaries: \['p2', 'p3'\]

- Evidence o6: match "tail spine"; source "tail spine"; ambiguous [23:33 in 23:33; 59:69 in 59:69]; extractor ollama:fixture; source src1.

Local contextual expressions:
- **curved tail spine** — Observed descriptive expression attached provisionally for this fixture\.
- Evidence o8: match "curved tail spine"; source "curved tail spine"; resolved [52:69 in 52:69]; extractor ollama:fixture; source src1.

### Tail — p4

[proposed; scientifically unvalidated] primary

Rationale: Synthetic proposed anatomical organization; requires review\.

- Evidence o9: match "Tail"; source "Tail"; resolved [71:75 in 71:75]; extractor ollama:fixture; source src1.

Local contextual expressions: none.

Associated indexed compounds: none.

### tail — p2

[proposed; scientifically unvalidated] primary

Rationale: Synthetic proposed anatomical organization; requires review\.

- Evidence o3: match "tail"; source "tail"; ambiguous [13:17 in 13:17; 23:27 in 23:27; 42:46 in 42:46; 59:63 in 59:63]; extractor ollama:fixture; source src1.

Local contextual expressions: none.

#### tail spine — c2

[proposed; scientifically unvalidated] compound

Rationale: Synthetic proposed anatomical organization; requires review\.

Associated primaries: \['p2', 'p3'\]

- Evidence o6: match "tail spine"; source "tail spine"; ambiguous [23:33 in 23:33; 59:69 in 59:69]; extractor ollama:fixture; source src1.

Local contextual expressions:
- **curved tail spine** — Observed descriptive expression attached provisionally for this fixture\.
- Evidence o8: match "curved tail spine"; source "curved tail spine"; resolved [52:69 in 52:69]; extractor ollama:fixture; source src1.

#### tail tip — c1

[proposed; scientifically unvalidated] compound

Rationale: Synthetic proposed anatomical organization; requires review\.

Associated primaries: \['p2'\]

- Evidence o4: match "tail tip"; source "tail tip"; ambiguous [13:21 in 13:21; 42:50 in 42:50]; extractor ollama:fixture; source src1.

Local contextual expressions:
- **curved tail tip** — Observed descriptive expression attached provisionally for this fixture\.
- Evidence o7: match "curved tail tip"; source "curved tail tip"; resolved [35:50 in 35:50]; extractor ollama:fixture; source src1.

## Orphan or unlinked indexed compounds

None.

## Invalid or unclassified records

## Exclusions

- o10: Property, not an anatomical structure\.
- Evidence o10: match "Total length"; source "Total length"; resolved [77:89 in 77:89]; extractor ollama:fixture; source src1.

## Unresolved observations

- o11: Insufficient anatomical meaning or attachment context\.
- Evidence o11: match "uncertain"; source "uncertain"; resolved [91:100 in 91:100]; extractor ollama:fixture; source src1.

## Review notes and nonauthoritative equivalence proposals

\{"review\_notes": \["Synthetic fixture; all anatomical interpretations are nonauthoritative\.", "Tail and tail remain separate observed forms; no normalization applied\."\], "equivalence\_proposals": \[\]\}

## Model metadata and audit counts

- Model: offline:fixture
- Input SHA-256: f74ea6498ab679051fc5e367ce444dbbf083e620db2183502445b3765bdea1d6
- Prompt SHA-256: a89a6fba0f8a8b2e9c453b3f6f1afb3e6249ee9280e8c2b8ba0cadfed22c5ab4
- Completion reason: fixture
- Token/timing metrics: null
- Observations: 11; stored primaries: 4; stored compounds: 2; raw term records: 6.
- Local expressions: 3; exclusions: 1; unresolved (including missing decisions): 1.
- Compounds displayed beneath several primaries are counted once as stored records, not biological frequency counts.

## Validation issues

- [warning] AMBIGUOUS\_LOCATION /sources/0/document/entries/2: All possible locations retained; none selected\.
- [warning] AMBIGUOUS\_LOCATION /sources/0/document/entries/3: All possible locations retained; none selected\.
- [warning] AMBIGUOUS\_LOCATION /sources/0/document/entries/4: All possible locations retained; none selected\.
- [warning] AMBIGUOUS\_LOCATION /sources/0/document/entries/5: All possible locations retained; none selected\.

## Complete raw proposal appendix

<pre>{
  "format_version": "synthesis-1.2",
  "proposal_id": "fixture-v12",
  "input_sha256": "f74ea6498ab679051fc5e367ce444dbbf083e620db2183502445b3765bdea1d6",
  "provider": "offline",
  "model": "fixture",
  "prompt_sha256": "a89a6fba0f8a8b2e9c453b3f6f1afb3e6249ee9280e8c2b8ba0cadfed22c5ab4",
  "terms": [
    {
      "ref": "p1",
      "type": "primary",
      "text": "anal",
      "observation_ids": [
        "o1"
      ],
      "primary_refs": [],
      "expressions": [
        {
          "text": "anal entire",
          "observation_ids": [
            "o2"
          ],
          "rationale": "Observed descriptive expression attached provisionally for this fixture."
        }
      ],
      "rationale": "Synthetic proposed anatomical organization; requires review."
    },
    {
      "ref": "p2",
      "type": "primary",
      "text": "tail",
      "observation_ids": [
        "o3"
      ],
      "primary_refs": [],
      "expressions": [],
      "rationale": "Synthetic proposed anatomical organization; requires review."
    },
    {
      "ref": "p3",
      "type": "primary",
      "text": "spine",
      "observation_ids": [
        "o5"
      ],
      "primary_refs": [],
      "expressions": [],
      "rationale": "Synthetic proposed anatomical organization; requires review."
    },
    {
      "ref": "p4",
      "type": "primary",
      "text": "Tail",
      "observation_ids": [
        "o9"
      ],
      "primary_refs": [],
      "expressions": [],
      "rationale": "Synthetic proposed anatomical organization; requires review."
    },
    {
      "ref": "c1",
      "type": "compound",
      "text": "tail tip",
      "observation_ids": [
        "o4"
      ],
      "primary_refs": [
        "p2"
      ],
      "expressions": [
        {
          "text": "curved tail tip",
          "observation_ids": [
            "o7"
          ],
          "rationale": "Observed descriptive expression attached provisionally for this fixture."
        }
      ],
      "rationale": "Synthetic proposed anatomical organization; requires review."
    },
    {
      "ref": "c2",
      "type": "compound",
      "text": "tail spine",
      "observation_ids": [
        "o6"
      ],
      "primary_refs": [
        "p2",
        "p3"
      ],
      "expressions": [
        {
          "text": "curved tail spine",
          "observation_ids": [
            "o8"
          ],
          "rationale": "Observed descriptive expression attached provisionally for this fixture."
        }
      ],
      "rationale": "Synthetic proposed anatomical organization; requires review."
    }
  ],
  "observation_dispositions": [
    {
      "observation_id": "o1",
      "status": "mapped",
      "term_refs": [
        "p1"
      ],
      "reason": null
    },
    {
      "observation_id": "o2",
      "status": "mapped",
      "term_refs": [
        "p1"
      ],
      "reason": null
    },
    {
      "observation_id": "o3",
      "status": "mapped",
      "term_refs": [
        "p2"
      ],
      "reason": null
    },
    {
      "observation_id": "o4",
      "status": "mapped",
      "term_refs": [
        "c1"
      ],
      "reason": null
    },
    {
      "observation_id": "o5",
      "status": "mapped",
      "term_refs": [
        "p3"
      ],
      "reason": null
    },
    {
      "observation_id": "o6",
      "status": "mapped",
      "term_refs": [
        "c2"
      ],
      "reason": null
    },
    {
      "observation_id": "o7",
      "status": "mapped",
      "term_refs": [
        "c1"
      ],
      "reason": null
    },
    {
      "observation_id": "o8",
      "status": "mapped",
      "term_refs": [
        "c2"
      ],
      "reason": null
    },
    {
      "observation_id": "o9",
      "status": "mapped",
      "term_refs": [
        "p4"
      ],
      "reason": null
    },
    {
      "observation_id": "o10",
      "status": "excluded",
      "term_refs": [],
      "reason": "Property, not an anatomical structure."
    },
    {
      "observation_id": "o11",
      "status": "unresolved",
      "term_refs": [],
      "reason": "Insufficient anatomical meaning or attachment context."
    }
  ],
  "equivalence_proposals": [],
  "review_notes": [
    "Synthetic fixture; all anatomical interpretations are nonauthoritative.",
    "Tail and tail remain separate observed forms; no normalization applied."
  ]
}</pre>
