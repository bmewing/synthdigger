# 09 · Optional: AI Features (OpenRouter)

SynthDigger can give playlists an **AI-generated title and cover image**, and interpret
freeform "vibe" prompts more cleverly. This is **completely optional** — skip this page and
everything else still works.

These features go through **OpenRouter**, a single service that routes to the AI models
used (a DeepSeek text model and a Flux image model). One API key covers all of it. Cost is
pay-per-use and tiny (fractions of a cent per playlist).

## If you want AI features

### Step 1 — Sign up

Create an account at [openrouter.ai](https://openrouter.ai/) and add a small amount of
credit.

### Step 2 — Create an API key

In OpenRouter, go to **Keys** → **Create Key**. Copy it — it starts with `sk-or-v1-…`.

### Step 3 — Add it to `.env`

```
OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

The model choices already have sensible defaults; you can leave these as-is or override:

```
OPENROUTER_TEXT_MODEL=deepseek/deepseek-v4-flash
OPENROUTER_IMAGE_MODEL=black-forest-labs/flux.2-klein-4b
```

Now `synthdigger playlist --ai-cover` (and the web app's AI buttons) will work.

## If you DON'T want AI features

You have two choices — either is fine:

- **Just leave it blank.** With no `OPENROUTER_API_KEY`, all AI steps are skipped
  gracefully. Playlists still generate; they just get a plain auto-title and no cover.
- **Turn them off explicitly.** Set this to hide the AI buttons and vibe box in the web app
  entirely:
  ```
  DISABLE_AI_FEATURES=true
  ```

## You're done when…

You've decided: either a working `OPENROUTER_API_KEY` is in `.env`, or you've knowingly left
it blank / set `DISABLE_AI_FEATURES=true`.

**Next:** [[10 Deploy the Web App]]
