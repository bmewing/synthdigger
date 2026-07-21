# 11 · Custom Domain (Optional)

By default your app lives at a `…ondigitalocean.app` address. If you'd rather use your own,
like `music.example.com`, here's how. Skip this page if the default address is fine.

## Step 1 — Add the domain in DigitalOcean

1. In the DigitalOcean dashboard, open your app → **Settings** → **Domains**.
2. Click **Add Domain** and enter your subdomain, e.g. `music.example.com`.
3. DigitalOcean shows you a **CNAME target** (a `…ondigitalocean.app` hostname).

## Step 2 — Point your DNS at it

At whoever manages your domain's DNS (your registrar or DNS provider), add a **CNAME**
record:

- **Name/Host:** `music` (the subdomain part)
- **Target/Value:** the `…ondigitalocean.app` hostname DigitalOcean gave you

DNS can take a few minutes to a few hours to take effect. HTTPS/TLS is set up automatically
once it resolves — you don't need to manage certificates.

## ⚠️ Important gotcha: keep the domain in your config

Once your domain is attached and working, add it to your **local** `.do/app.yaml` so future
updates don't remove it. Near the bottom of the file, uncomment and edit the `domains`
block:

```yaml
domains:
  - domain: music.example.com
    type: PRIMARY
```

**Why this matters:** the next time you run `doctl apps update <app-id> --spec .do/app.yaml`,
DigitalOcean makes the live app match your file *exactly*. If your file has no `domains`
block, it will **remove** the domain you attached — and your custom address stops working.
Keeping the block in your file mirrored with what's live prevents this.

## You're done when…

`https://music.example.com` (your domain) loads the SynthDigger sign-in page, and your
`.do/app.yaml` contains the matching `domains:` block.

**Next:** [[12 Keep Data Fresh and Day-2]]
