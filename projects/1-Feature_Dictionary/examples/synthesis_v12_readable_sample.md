# Synthesis v1.2 — model proposal audit

**UNVALIDATED MODEL PROPOSAL — NOT A COMPILED DICTIONARY.**
Software checks assess formatting, evidence and references, not biological correctness.

Completion: success; JSON valid: True; schema valid: True; proposal checks passed: True.

## Primary anatomical terms

### anal — p1

[proposed; scientifically unvalidated] primary

Rationale: Synthetic proposed anatomical organization; requires review.

- Evidence o1: "anal"

Local contextual expressions:

- **anal entire** — Observed descriptive expression attached provisionally for this fixture.
  - Evidence o2: "anal entire"

Associated indexed compounds: none.

### spine — p3

[proposed; scientifically unvalidated] primary

Rationale: Synthetic proposed anatomical organization; requires review.

- Evidence o5: "spine" **[ambiguous location]**

Local contextual expressions: none.

#### tail spine — c2

[proposed; scientifically unvalidated] compound

Rationale: Synthetic proposed anatomical organization; requires review.

Associated primaries: tail (p2), spine (p3)

**Shared indexed compound:** stored once; displayed under each associated primary.

- Evidence o6: "tail spine" **[ambiguous location]**

Local contextual expressions:

- **curved tail spine** — Observed descriptive expression attached provisionally for this fixture.
  - Evidence o8: "curved tail spine"

### Tail — p4

[proposed; scientifically unvalidated] primary

Rationale: Synthetic proposed anatomical organization; requires review.

- Evidence o9: "Tail"

Local contextual expressions: none.

Associated indexed compounds: none.

### tail — p2

[proposed; scientifically unvalidated] primary

Rationale: Synthetic proposed anatomical organization; requires review.

- Evidence o3: "tail" **[ambiguous location]**

Local contextual expressions: none.

#### tail spine — c2

[proposed; scientifically unvalidated] compound

Rationale: Synthetic proposed anatomical organization; requires review.

Associated primaries: tail (p2), spine (p3)

**Shared indexed compound:** stored once; displayed under each associated primary.

- Evidence o6: "tail spine" **[ambiguous location]**

Local contextual expressions:

- **curved tail spine** — Observed descriptive expression attached provisionally for this fixture.
  - Evidence o8: "curved tail spine"

#### tail tip — c1

[proposed; scientifically unvalidated] compound

Rationale: Synthetic proposed anatomical organization; requires review.

Associated primaries: tail (p2)

- Evidence o4: "tail tip" **[ambiguous location]**

Local contextual expressions:

- **curved tail tip** — Observed descriptive expression attached provisionally for this fixture.
  - Evidence o7: "curved tail tip"

## Orphan or unlinked indexed compounds

None.

## Invalid or unclassified records

## Exclusions

- o10: Property, not an anatomical structure.
- Evidence o10: "Total length"

## Unresolved observations

- o11: Insufficient anatomical meaning or attachment context.
- Evidence o11: "uncertain"

## Evidence details

Exact quotations and source locations are preserved below. Offsets are zero-based, end-exclusive Python character positions.

### o1

- Extracted phrase: "anal"
- Source phrase: "anal"
- Location status: **resolved**
- Match offsets: 0:4; source-phrase offsets: 0:4
- Source: src1; entry index: 0
- Extractor: ollama:fixture
- Extraction run: offline-v12-fixture; prompt: fixture
- Original source path: synthetic-v12.txt

### o2

- Extracted phrase: "anal entire"
- Source phrase: "anal entire"
- Location status: **resolved**
- Match offsets: 0:11; source-phrase offsets: 0:11
- Source: src1; entry index: 1
- Extractor: ollama:fixture
- Extraction run: offline-v12-fixture; prompt: fixture
- Original source path: synthetic-v12.txt

### o3

- Extracted phrase: "tail"
- Source phrase: "tail"
- Location status: **ambiguous**
- Match offsets: 13:17; source-phrase offsets: 13:17
- Match offsets: 23:27; source-phrase offsets: 23:27
- Match offsets: 42:46; source-phrase offsets: 42:46
- Match offsets: 59:63; source-phrase offsets: 59:63
- Source: src1; entry index: 2
- Extractor: ollama:fixture
- Extraction run: offline-v12-fixture; prompt: fixture
- Original source path: synthetic-v12.txt

### o4

- Extracted phrase: "tail tip"
- Source phrase: "tail tip"
- Location status: **ambiguous**
- Match offsets: 13:21; source-phrase offsets: 13:21
- Match offsets: 42:50; source-phrase offsets: 42:50
- Source: src1; entry index: 3
- Extractor: ollama:fixture
- Extraction run: offline-v12-fixture; prompt: fixture
- Original source path: synthetic-v12.txt

### o5

- Extracted phrase: "spine"
- Source phrase: "spine"
- Location status: **ambiguous**
- Match offsets: 28:33; source-phrase offsets: 28:33
- Match offsets: 64:69; source-phrase offsets: 64:69
- Source: src1; entry index: 4
- Extractor: ollama:fixture
- Extraction run: offline-v12-fixture; prompt: fixture
- Original source path: synthetic-v12.txt

### o6

- Extracted phrase: "tail spine"
- Source phrase: "tail spine"
- Location status: **ambiguous**
- Match offsets: 23:33; source-phrase offsets: 23:33
- Match offsets: 59:69; source-phrase offsets: 59:69
- Source: src1; entry index: 5
- Extractor: ollama:fixture
- Extraction run: offline-v12-fixture; prompt: fixture
- Original source path: synthetic-v12.txt

### o7

- Extracted phrase: "curved tail tip"
- Source phrase: "curved tail tip"
- Location status: **resolved**
- Match offsets: 35:50; source-phrase offsets: 35:50
- Source: src1; entry index: 6
- Extractor: ollama:fixture
- Extraction run: offline-v12-fixture; prompt: fixture
- Original source path: synthetic-v12.txt

### o8

- Extracted phrase: "curved tail spine"
- Source phrase: "curved tail spine"
- Location status: **resolved**
- Match offsets: 52:69; source-phrase offsets: 52:69
- Source: src1; entry index: 7
- Extractor: ollama:fixture
- Extraction run: offline-v12-fixture; prompt: fixture
- Original source path: synthetic-v12.txt

### o9

- Extracted phrase: "Tail"
- Source phrase: "Tail"
- Location status: **resolved**
- Match offsets: 71:75; source-phrase offsets: 71:75
- Source: src1; entry index: 8
- Extractor: ollama:fixture
- Extraction run: offline-v12-fixture; prompt: fixture
- Original source path: synthetic-v12.txt

### o10

- Extracted phrase: "Total length"
- Source phrase: "Total length"
- Location status: **resolved**
- Match offsets: 77:89; source-phrase offsets: 77:89
- Source: src1; entry index: 9
- Extractor: ollama:fixture
- Extraction run: offline-v12-fixture; prompt: fixture
- Original source path: synthetic-v12.txt

### o11

- Extracted phrase: "uncertain"
- Source phrase: "uncertain"
- Location status: **resolved**
- Match offsets: 91:100; source-phrase offsets: 91:100
- Source: src1; entry index: 10
- Extractor: ollama:fixture
- Extraction run: offline-v12-fixture; prompt: fixture
- Original source path: synthetic-v12.txt

## Review notes and nonauthoritative equivalence proposals

- Synthetic fixture; all anatomical interpretations are nonauthoritative.
- Tail and tail remain separate observed forms; no normalization applied.

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

- [warning] AMBIGUOUS_LOCATION /sources/0/document/entries/2: All possible locations retained; none selected.
- [warning] AMBIGUOUS_LOCATION /sources/0/document/entries/3: All possible locations retained; none selected.
- [warning] AMBIGUOUS_LOCATION /sources/0/document/entries/4: All possible locations retained; none selected.
- [warning] AMBIGUOUS_LOCATION /sources/0/document/entries/5: All possible locations retained; none selected.
