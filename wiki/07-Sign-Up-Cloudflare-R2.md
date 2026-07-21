# 07 · Sign Up for Cloudflare R2

The web app reads your analyzed library from cloud storage called **R2**. Cloudflare's free
tier is generous — this typically costs nothing.

## Step 1 — Create a Cloudflare account

Sign up at [dash.cloudflare.com](https://dash.cloudflare.com/). Verify your email.

## Step 2 — Create an R2 bucket

A "bucket" is just a storage container.

1. In the dashboard sidebar, click **R2**. (The first time, you may be asked to enable R2 —
   follow the prompt; the free tier doesn't require payment details for basic use, though
   Cloudflare may ask you to add a card on file.)
2. Click **Create bucket**.
3. Name it **`music-discovery`** (this is the default SynthDigger expects). Click **Create**.

## Step 3 — Create an API token (read/write)

This lets SynthDigger upload to, and the web app read from, your bucket.

1. In **R2**, open **Manage R2 API Tokens** → **Create API token**.
2. Give it **Object Read & Write** permission. You can scope it to just the
   `music-discovery` bucket.
3. Click create. Cloudflare shows you three things **once** — copy them now:
   - **Access Key ID**
   - **Secret Access Key**
   - your **Account ID** (also shown on the R2 overview page)

> **Save these somewhere safe and private.** The Secret Access Key is shown only once. Treat
> it like a password.

## Step 4 — Put them in your `.env`

Open `.env` (from [[03 Connect to Plex]]) and fill in the R2 lines:

```
R2_ACCOUNT_ID=your-account-id
R2_ACCESS_KEY_ID=your-access-key-id
R2_SECRET_ACCESS_KEY=your-secret-access-key
R2_BUCKET=music-discovery
```

You'll use these when you publish and deploy in [[10 Deploy the Web App]].

## You're done when…

You have a bucket named `music-discovery` and all four `R2_*` values saved in `.env`.

**Next:** [[08 Sign Up DigitalOcean and Install doctl]]
