# 08 · Sign Up for DigitalOcean and Install doctl

**DigitalOcean App Platform** runs the actual website. This is the one part with a small
monthly cost (typically a few dollars). **`doctl`** is DigitalOcean's command-line tool that
you'll use to create and update the app.

## Step 1 — Create a DigitalOcean account

Sign up at [cloud.digitalocean.com](https://cloud.digitalocean.com/). You'll add a payment
method; new accounts often come with trial credit.

## Step 2 — Install doctl

Follow DigitalOcean's official instructions for your system:
[How to install doctl](https://docs.digitalocean.com/reference/doctl/how-to/install/).

Quick pointers:
- **Windows:** download the release zip and add `doctl.exe` to a folder on your PATH, or use
  a package manager if you have one.
- **Mac:** `brew install doctl`.
- **Linux:** use the Snap or the download in the docs.

Check it's installed:

```bash
doctl version
```

## Step 3 — Create an API token

1. In the DigitalOcean dashboard: **API** (left sidebar) → **Tokens** → **Generate New
   Token**.
2. Give it a name (e.g. `synthdigger`), full access, and generate it.
3. Copy the token — it's shown only once. Keep it private.

## Step 4 — Connect doctl to your account

```bash
doctl auth init
```

Paste the token when prompted. You should see "Validating token... OK".

> **Multiple DigitalOcean accounts?** You can keep them separate with named contexts:
> `doctl auth init --context myname`, then add `--context myname` to later commands.

## You're done when…

`doctl account get` prints your account details without an error.

**Next:** [[09 Optional AI Features OpenRouter]] (or skip straight to [[10 Deploy the Web App]]).
