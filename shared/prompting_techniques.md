# Agentic Coding Prompting Guide

**1. The Core Rule: Inspect First, Plan Second, Edit Third**
Never ask an agent to implement a complex feature or bugfix in a single prompt. Force it to inspect the codebase and present a plan before writing any code.

* **Bad Prompt:** "Fix the vector store connection error in the project."
* **Good Prompt:** "Inspect `projects/1-Feature_Dictionary/src/db.py`. Diagnose why ChromaDB is failing on startup, list the root causes, and propose a fix without modifying any files yet."

---

**2. Anatomy of an Effective Prompt**

Use this 4-part framework whenever requesting multi-file changes:

| Component         | What to Include | Example |
| --- | --- | --- |
| **Context**       | Exact sub-project & file paths        | `Targeting: projects/1-feature_dictionary/extractors.py`       |
| **Objective**     | Single, measurable goal               | `Add multi-extractor support to the file.`         |
| **Constraints**   | Hard limits on what **not** to touch  | `Do not upgrade PyTorch or modify files in shared/.`              |
| **Validation**    | Explicit test command for completion  | `Verify by running pytests`    |

---

**3. Three Essential Prompting Patterns**

**The File Anchor Pattern**
*Explicitly list input files so the agent doesn't waste tokens searching the whole repo.*

> "Refactor the prompt parser. Read `projects/1-feature_dictionary/src/parser.py` as your input reference and output the updated version to `projects/1-feature_dictionary/src/parser_v2.py`."

**The Circuit Breaker Pattern**
*Prevent the agent from burning tokens or making bad edits when stuck in a failure loop.*

> "Paste the exact terminal error output, give me 2 potential root causes, and wait for my decision before making further changes."

**The Single-Variable Change**
*Avoid asking for multiple features at once. Isolate edits to keep git diffs reviewable.*

> "First, update the API client to handle rate-limit retries. Once we test and confirm that works, we will update the UI log display in the next turn."