# ddc-automation

# A SKOS-Anchored, Multi-Round Workflow for Assigning Dewey Numbers with Annif and an LLM Mediator

## Abstract

I outline a practical workflow for assigning Dewey Decimal Classification (DDC) numbers that blends an Annif ensemble for high-recall candidate generation with a retrieval-centric LLM “mediator.” Congress data is used only to train Annif. The mediator then reads DDC 23—Schedules, Tables, Manual, and the Relative Index—through a SKOS database I built from page images. Each round narrows the search space and updates a compact memory of what has been ruled in or out. The result is a grounded, explainable path from text to a single DDC notation.

---

## 1. Introduction

Picking the right Dewey number from free text is hard: keyword overlap is noisy and the DDC rules are subtle. My solution splits the job. First, Annif proposes a strong top-10 list. Next, an LLM reasons over DDC evidence that I expose as linked SKOS concepts, so the model isn’t guessing—it’s reading the scheme. I keep the process iterative and stateful so the model doesn’t re-learn the same facts every round.

---

## 2. Materials and Knowledge Base

### 2.1 DDC 23 → SKOS

I converted DDC 23 pages to a SKOS-like graph using a schema-constrained extractor (Gemini 2.5 Flash). The extractor is resumable (one JSON per page), pretty-prints outputs, and records provenance (`page`, `source.fileName`). Two sentinels handle awkward page starts:

* `__CONT__` when a page begins mid-sentence; I merge its text into the previous concept’s `scope.notes`.
* `__PAGE__` for any non-DDC header at the top (e.g., “SUMMARY”); I store these in a sidecar for context.

I route common phrases into structured fields: *Class here*, *Including*, *See also*, *See Manual at*, *Use notation … from Table 1*, *Add to base …*, and relocation notes. I don’t invent hierarchy during extraction; broader/narrower can be derived later when there’s evidence.

### 2.2 Annif training

Congress data is used solely to train Annif. I rely on a small set of backends (TF-IDF, SVC, Omikuji, and a lightweight MLLM variant) and combine them with simple ensembles (average and PAV). In practice, I query one ensemble to get the **top 10** DDC candidates per document.

---

## 3. Method

### 3.1 Candidate generation

Given an input, I ask Annif for the top-10 notations. This step favors recall and keeps downstream reasoning fast.

### 3.2 Mediated retrieval

For each candidate, the mediator pulls the corresponding SKOS concept and any linked material: table rules, manual pointers, *see also* hops, variants, ranges, and examples. The LLM reads only what’s retrieved, not its own memory.

### 3.3 Round-based reasoning with memory

After each round, I shrink the model’s notes into a short “memory abstraction”: constraints that matter, branches eliminated (and why), relevant table modifiers, and any unresolved facets. The next round starts from that state, so progress accumulates instead of looping.

### 3.4 Decision policy

The loop ends when one candidate fits the text and the rules better than the rest, with explicit citations back to the SKOS entries that justified the choice.

---

## 4. Implementation Notes

* **Extractor**: schema-forced JSON; per-page checkpoints; dual-page calls when helpful; continuation and page-lead sentinels; pretty-printed files and terminal output.
* **Schema**: each concept includes `id`, `type="Concept"`, `notation`, `prefLabel.en`, `page`, `source.fileName`, plus structured `scope.*` fields when present.
* **Store**: concepts are indexed by notation and labels; all links are resolvable; provenance is preserved so I can surface exact page evidence to the LLM.

---

## 5. Evaluation Plan

I plan to score exact matches on a held-out set with expert Dewey assignments, report hierarchical distance for near-misses, and time-to-decision. Ablations will test the impact of memory abstraction, table/manual retrieval, and using Annif top-1 vs. top-10.


## 8. Conclusion

This workflow treats Dewey assignment as a conversation between strong retrieval and careful reading. Annif contributes breadth; the mediator and SKOS map contribute depth and traceability. With each round, the LLM refines its view, cites the rules it used, and lands on a number for reasons I can show, not just a score.
