# BluePace ATS — AI Model Strategy

Updated: 2026-10-06

## Principle
Do not choose a model because it is the newest or largest. Choose the smallest reliable system that solves the task, and keep deterministic logic in control of decisions.

ATS flow: Document extraction → structured evidence → deterministic validation → model only when language/reasoning is needed → schema validation → evidence → recruiter decision.

## Model classes and ATS use cases

| Use case | Preferred system | Why |
|---|---|---|
| PDF/DOCX text extraction | Docling/PyMuPDF/python-docx or equivalent deterministic parser | Faster, reproducible, no hallucination |
| Resume field normalization | Small/fast instruct model | Repeated structured transformation |
| JD requirement extraction | Small/fast structured-output model | Predictable JSON; low latency/cost |
| Resume ↔ JD skill matching | Deterministic matching + embeddings when needed | Skills and thresholds should remain explainable |
| Semantic candidate search | Embedding model + vector DB | Search is a retrieval problem, not generation |
| Recruiter assistant | Fast capable general model | Summaries, questions, drafts, evidence explanations |
| Ambiguous/complex analysis | Strong reasoning model | Use only when the task actually needs deeper reasoning |
| RAG | Embeddings + vector DB + generation model | Retrieve relevant evidence before generation |
| Tool/agent workflows | Capable tool-calling model + strict permissions | Actions need explicit tools and approval boundaries |
| Multimodal resumes/documents | Multimodal model when deterministic parsing is insufficient | Use for scans, tables, images and visual layouts |
| Hiring decision | Human recruiter + deterministic evidence | Never delegate the decision to an LLM |

## Current default direction
For OpenRouter-backed generation, the code now supports task-specific environment variables:
- OPENROUTER_MODEL — normal default
- OPENROUTER_ASSISTANT_MODEL — recruiter assistant
- OPENROUTER_VALIDATION_MODEL — secondary validation
- OPENROUTER_DEEP_REASONING_MODEL — optional complex reasoning

The current default is a Gemini Flash-class model because routine ATS tasks benefit more from latency/cost than from maximum reasoning. A frontier model is reserved for genuinely difficult tasks.

## Model selection rule
1. Can code solve it? Use code.
2. Is it retrieval/search? Use embeddings + retrieval.
3. Is it predictable structured transformation? Use a small/fast model with JSON schema.
4. Is it open-ended but routine? Use a fast capable model.
5. Is it ambiguous, long-horizon or high-reasoning? Escalate.
6. Does it change candidate state or send something externally? Require an explicit application action and human approval.

## Production controls
Every AI response should have:
- task-specific prompt
- strict output schema
- application-side validation
- source/evidence references
- confidence/data-coverage signal
- model/version recorded in logs
- timeout and fallback behavior
- prompt-injection resistance
- human approval for consequential actions

Roadmap alignment: terminology, inference, tokens/cost, embeddings, vector databases, RAG, prompt engineering, pre-trained/open-source models, agents, multimodal AI and safety.