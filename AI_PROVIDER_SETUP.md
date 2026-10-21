# AI provider setup for BluePace ATS

AI Hiring Studio now offers a provider selector for OpenRouter, OpenAI/ChatGPT API, Claude/Anthropic, DeepSeek, Cloudflare Workers AI and local Ollama. Provider/model/key selections apply to all AI Hiring Studio operations.

## Configure hosted providers

Set the provider's secrets in the backend's environment or enter its API key under AI Hiring Studio → Settings. Keys are only held in browser session storage when entered in the UI; never place credentials in frontend Vite environment variables or commit real secrets.

| Provider | Backend environment variables | Default model |
|---|---|---|
| OpenRouter | `OPENROUTER_API_KEY` | `openrouter/free` |
| OpenAI / ChatGPT API | `OPENAI_API_KEY` | `gpt-5.4` |
| Claude / Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` |
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-flash` |
| Cloudflare Workers AI | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | `@cf/qwen/qwen3.8-27b` |

The model ID is editable because availability depends on provider account, plan and region. The Test connection action sends a short prompt for direct provider adapters and may create a small usage charge. OpenRouter test validates the key and checks the model list.

## Local Ollama with Qwen

Install Ollama on the same machine as the backend. Pull a model:

```bash
ollama pull qwen3.5:4b
```

Choose **Local Ollama · Qwen 3.5**, keep the base URL at `http://localhost:11434/v1`, and use model `qwen3.5:4b` or another already installed Ollama model. The published Ollama library lists Qwen 3.5 tags; the phrase “Qwen 3.4.5” is not a model tag I could verify. See the [Ollama Qwen 3.5 library](https://ollama.com/library/qwen3.5).

**Deployment limitation:** `localhost` is the backend host. When the API is running on Railway, it cannot reach Ollama installed on your personal computer by using localhost. The adapter accepts loopback URLs only and rejects remote addresses to prevent SSRF. Local inference in the deployed UI requires the backend and Ollama on the same machine, or a separately secured local bridge. That is not established by a simple URL setting.

Provider policies and cost vary. Make sure your organisation authorises the provider to process candidate information. AI assessments remain recruiter decision support and require human review.
