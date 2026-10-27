# AI provider setup for BluePace ATS

AI Hiring Studio offers a provider selector for OpenAI/ChatGPT API, Google Gemini, Claude/Anthropic, DeepSeek, xAI Grok, GitHub Models (Copilot ecosystem), OpenRouter, Cloudflare Workers AI and local Ollama. OpenRouter is optional; use a direct provider if its selected model is unavailable. Provider/model/key selections apply to all AI Hiring Studio operations.

## Configure hosted providers

Set the provider's secrets in the backend's environment or enter its API key under AI Hiring Studio → Settings. Keys are only held in browser session storage when entered in the UI; never place credentials in frontend Vite environment variables or commit real secrets.

| Provider | Backend environment variables | Default model |
|---|---|---|
| OpenRouter | `OPENROUTER_API_KEY` | `openrouter/free` |
| OpenAI / ChatGPT API | `OPENAI_API_KEY` | `gpt-5.4` |
| Claude / Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` |
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| xAI Grok | `XAI_API_KEY` | `grok-3-mini` |
| GitHub Models (Copilot ecosystem) | `GITHUB_MODELS_TOKEN` or `GITHUB_TOKEN` | `openai/gpt-4.1` |
| Cloudflare Workers AI | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | `@cf/qwen/qwen3.8-27b` |

The model ID is editable because availability depends on provider account, plan and region. The Test connection action sends a short prompt for direct provider adapters and may create a small usage charge. OpenRouter test validates the key and checks the model list. DeepSeek defaults to `deepseek-chat`; verify the current model and pricing in the [official model and pricing docs](https://api-docs.deepseek.com/quick_start/pricing/).

## Local Ollama with Qwen

Install Ollama on the same machine as the backend. Pull a model:

```bash
ollama pull qwen3.5:4b
```

Choose **Local Ollama · Qwen 3.5**, keep the base URL at `http://localhost:11434/v1`, and use model `qwen3.5:4b` or another already installed Ollama model. The published Ollama library lists Qwen 3.5 tags; the phrase “Qwen 3.4.5” is not a model tag I could verify. See the [Ollama Qwen 3.5 library](https://ollama.com/library/qwen3.5).

**Deployment limitation:** `localhost` is the backend host. When the API is running on Railway, it cannot reach Ollama installed on your personal computer by using localhost. The adapter accepts loopback URLs only and rejects remote addresses to prevent SSRF. Local inference in the deployed UI requires the backend and Ollama on the same machine, or a separately secured local bridge. That is not established by a simple URL setting.

Provider policies and cost vary. Make sure your organisation authorises the provider to process candidate information. AI assessments remain recruiter decision support and require human review.


## Notes on Grok and Copilot

- **Grok** uses the xAI API at `https://api.x.ai/v1/chat/completions`. Create an xAI API key and configure `XAI_API_KEY` on the backend or enter it in AI Hiring Studio Settings.
- **Copilot:** a Microsoft Copilot or GitHub Copilot subscription is not, by itself, a general-purpose API key for third-party applications. The new **GitHub Models (Copilot ecosystem)** option calls the GitHub Models inference API and requires a GitHub token with access to Models. Configure `GITHUB_MODELS_TOKEN` (preferred) or `GITHUB_TOKEN`; model access depends on GitHub account/organisation policy and rate limits. This does not embed or automate the Copilot chat product.
- OpenRouter's default has been changed from the potentially unavailable `openrouter/free` alias to `google/gemini-2.5-flash`. You can still enter any model ID available to your OpenRouter account. Provider availability is verified only when you use **Test connection**.
- API keys entered in Settings remain in browser session storage; server-side environment variables are preferred for shared production configuration. Never put provider secrets in public Vite variables.
