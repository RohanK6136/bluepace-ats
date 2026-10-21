## 4. Deep Fine-Tuning Research Report

### Executive Summary

For a small open-source ATS and resume-evaluation pipeline, the most practical path is to start with a compact instruction-tuned model such as Qwen 2.5 1.5B and optimize it for structured output, resume scoring, and domain-specific extraction. The goal is not to maximize raw model size, but to maximize quality-per-GPU-hour while keeping inference lightweight enough for local deployment or a modest cloud server.

The most promising strategy is a hybrid approach:

- Use a high-quality base model already trained for instruction following and multilingual reasoning.
- Run it in 4-bit quantized GGUF or AWQ format to reduce memory usage dramatically.
- Fine-tune only the most relevant layers using LoRA adapters.
- Keep the output format strict and schema-constrained so the model returns clean JSON for ATS scoring.

This approach can reduce RAM consumption from roughly 8GB for a higher-precision model to about 1.5GB in a compressed, quantized runtime while preserving most of the model’s reasoning ability for task-specific scoring.

### 1. Model Selection Strategy

For resume evaluation and ATS matching, the ideal model is not necessarily the largest model. A compact, well-tuned model often performs better in practical use because it can be run locally, tuned repeatedly, and integrated into a production pipeline with low latency.

The Qwen 2.5 1.5B family is a strong candidate because it provides:

- Strong instruction following at a small parameter size.
- Good multilingual handling.
- Better reasoning and summarization than many earlier small models.
- Efficient inference on CPU and modest GPU setups.

For the ATS workflow, the base model should be tuned for:

- Resume parsing from raw text and PDFs.
- Skill extraction and classification.
- Candidate vs job description matching.
- Scoring standards such as match percentage, mandatory skills coverage, and recommendation output.
- Structured JSON generation with fixed schemas.

### 2. Model Parameters and Practical Trade-offs

A 1.5B parameter model is a strong balance for production training and inference. At this size, the model is large enough to learn structured extraction patterns, but small enough to be fine-tuned on a moderate GPU.

Key parameters to consider during fine-tuning:

- Learning rate: usually between 1e-4 and 5e-5 for LoRA-based tuning.
- LoRA rank: often 8, 16, or 32 depending on task complexity.
- LoRA alpha: commonly set to 16 or 32 to scale adapter contributions.
- Batch size: small but efficient batches to maintain stable training.
- Epochs: 2 to 5 for a narrow domain task is often enough.
- Max sequence length: 2048 or 4096 depending on average resume length.

For ATS-specific tasks, the model should not be trained to “hallucinate” missing information. The important objective is to produce structured, consistent, and explainable outputs rather than freeform prose.

### 3. Quantization and GGUF for Memory Reduction

Quantization is one of the most important practical techniques for deploying smaller models effectively.

#### 4-bit GGUF Quantization

GGUF is a memory-efficient model format used in llama.cpp and other inference stacks. Quantizing a model to 4-bit precision reduces the memory footprint significantly. In many practical cases:

- An 8GB full-precision runtime can be reduced to around 1.5GB to 2GB depending on model architecture and context size.
- The speed trade-off is acceptable for inference workloads such as resume scoring and JSON extraction.
- This is especially useful for CPU inference or lower-end GPU servers.

This is important because:

- ATS tasks are high-frequency and may require batch evaluation.
- A quantized model is easier to run in smaller cloud or edge environments.
- It reduces infrastructure cost while preserving usable model quality.

#### Quantization considerations

Not all quantization schemes are equal. For production use, common choices include:

- 4-bit GGUF: best for low-memory inference and broad compatibility.
- 8-bit AWQ or GPTQ: better quality than 4-bit but higher memory usage.
- 16-bit bf16/fp16: best quality but much more memory intensive.

For resume matching workflows, 4-bit GGUF is often the best trade-off when cost, memory, and inference speed all matter.

### 4. LoRA Fine-Tuning Strategy

LoRA (Low-Rank Adaptation) is far more practical than full fine-tuning for this use case.

Instead of updating the entire model, LoRA adds low-rank trainable matrices to selected linear layers. This allows the model to learn ATS-specific behaviors without rewriting the full network.

#### Recommended LoRA configuration

- Target modules: q_proj, k_proj, v_proj, o_proj, and FFN projection layers.
- Rank: 8 to 32
- Alpha: 16 to 32
- Dropout: 0.05 to 0.1
- Bias: none
- Target modules may be conservative in early runs and expanded later.

#### Why LoRA works well here

- It preserves the base model’s general knowledge.
- It adapts the model quickly to ATS tasks.
- It is efficient enough to run on limited hardware.
- It makes iterative experiments much cheaper than full fine-tuning.

### 5. Fine-Tuning Data Design

For an ATS-focused model, the training data should be explicit and high quality. The dataset should include:

- Resume text samples with extracted fields.
- Job descriptions and normalized candidate match tasks.
- Paired examples of candidate skill alignment and missing skill detection.
- Structured-output examples in JSON format.
- Labelled recommendations such as Strong Yes, Yes, Maybe, or No.

Example training objectives:

- Extract name, email, phone, skills, education, projects, and experience.
- Match the candidate’s skills to job requirements.
- Identify missing mandatory skills.
- Score relevance on a bounded 0–100 scale.
- Return valid JSON in a fixed schema.

The model should be trained to be deterministic in output structure, because downstream UI rendering depends on clean schema compliance.

### 6. Recommended Training Pipeline

A strong fine-tuning workflow would look like this:

1. Start with Qwen 2.5 1.5B instruct model.
2. Curate a domain dataset of resumes + job descriptions.
3. Convert examples to prompt/response pairs with strict JSON output.
4. Fine-tune with LoRA using a low learning rate and a moderate rank.
5. Validate on held-out examples for:
   - field extraction accuracy
   - required skill recall
   - score calibration
   - JSON validity
6. Quantize the final checkpoint to 4-bit GGUF for deployment.
7. Use a serving stack such as llama.cpp or a lightweight inference backend.

### 7. Performance and Cost Considerations

This architecture is attractive because it lowers both memory and operational cost:

- Full model fine-tuning is too heavy and expensive for iterative experimentation.
- LoRA is inexpensive compared to retraining the entire model.
- 4-bit quantization makes inference cheap enough for local or low-cost deployment.
- Qwen 2.5 1.5B is large enough to be useful but small enough to iterate quickly.

### 8. Recommended Production Recommendation

For this ATS product, the best path is:

- Use Qwen 2.5 1.5B Instruct as the base model.
- Fine-tune with LoRA on ATS-specific resume/job-description datasets.
- Enforce structured JSON output.
- Quantize to 4-bit GGUF for memory efficiency.
- Keep the runtime under a low-memory inference environment for cost-effective deployment.

This provides the best balance between quality, deployment simplicity, and scalability.

### Final Conclusion

The most realistic and effective fine-tuning strategy for a small open-source ATS model is to combine:

- Qwen 2.5 1.5B as the base model,
- LoRA for efficient domain adaptation,
- 4-bit GGUF quantization for reduced RAM usage,
- strict JSON schema training for deterministic ATS output.

This approach can dramatically reduce memory usage—from around 8GB to roughly 1.5GB in practical quantized deployment—while maintaining the capability to perform accurate resume evaluation and structured extraction for real-world ATS workloads.
