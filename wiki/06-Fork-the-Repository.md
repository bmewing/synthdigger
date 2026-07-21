# 06 · Fork the Repository

**Part B starts here** — hosting the web app so others can make playlists. Everything in
Part B is optional.

## Why a fork?

A **fork** is your own copy of the SynthDigger code on GitHub. The web app is built and
deployed *from your fork*, so you need one. It also means you control when updates happen.

## Step 1 — Create a GitHub account

If you don't have one, sign up free at [github.com](https://github.com/join).

## Step 2 — Fork the repo

1. Go to **https://github.com/bmewing/music_discovery**.
2. Click **Fork** (top right) → **Create fork**.
3. You now have `https://github.com/YOUR_USERNAME/music_discovery`.

## Step 3 — Use your fork on your computer

If you cloned the original repo back in [[02 Install the App]], point it at your fork
instead so you can deploy from it. From inside the `music_discovery` folder:

```bash
git remote set-url origin https://github.com/YOUR_USERNAME/music_discovery.git
```

(Or clone your fork fresh: `git clone https://github.com/YOUR_USERNAME/music_discovery.git`.)

## What "deploy from your fork" means later

When you push changes to your fork, DigitalOcean can automatically rebuild the web app.
You'll set that up in [[10 Deploy the Web App]]. For now, just having the fork is enough.

## You're done when…

You can see your own copy at `github.com/YOUR_USERNAME/music_discovery`.

**Next:** [[07 Sign Up Cloudflare R2]]
