![](banner.jpg)

# Claude Gauge

A desktop app that shows you — at a glance — how much of your Claude Code subscription you've used, and whether you're spending it too fast or too slow.

Two retro analog gauges track your usage across two time windows (a rolling 5-hour window and your weekly period), while a mood panel reacts in real time with a humorous personality score. If you're cruising comfortably under budget, you're "Crushing It." If you've gone a bit wild, expect "Red Alert!" or even "Meltdown 💥."

---

## What It Shows

**Two analog gauges**

- **5-Hour Window** — how much you've used in the current rolling 5-hour window, compared to how much time in that window has elapsed.
- **7-Day Period** — the same idea, but zoomed out to your full weekly billing period.

Each gauge shows two needles: your actual usage and where you *should* be if you're pacing evenly. If your usage needle is behind the pace needle, you're in good shape.

**Mood panel**

Below the gauges is a personality score that combines both windows into one vibe:

| Score | Mood |
|---|---|
| Way under budget | CRUSHING IT |
| Comfortably ahead | VERY COMFY / LOOKING GOOD |
| Right on track | ZEN BALANCE |
| A little hot | WATCH IT... |
| Over budget | PANIC MODE / RED ALERT! |
| Way over | MELTDOWN 💥 |

Each mood comes with a matching illustration and a pace summary (green/yellow/red dot) so you know exactly where you stand.

The display refreshes every 5 minutes automatically.

---

## Getting Started

**Prerequisites**

- Python 3.10 or later
- A Claude Code subscription (the app reads your existing Claude credentials — no extra setup needed)

**Run it**

```bash
git clone <this-repo>
cd claude-usage
./run start
```

That's it. The first time you run it, the app creates a virtual environment and installs its dependencies automatically. Subsequent launches are instant.

---

## Features at a Glance

- **Live usage gauges** — retro analog dials with two needles (usage vs. pace)
- **Mood panel** — 10 humorous states with illustrations that react to your budget score
- **Pace indicator** — a plain-English summary (🟢 Well under budget, 🟡 Watch your pace, 🔴 Over budget)
- **Countdown timers** — each gauge shows how long until the window resets
- **Auto-refresh** — polls your usage every 5 minutes in the background
- **Token auto-refresh** — quietly renews your credentials before they expire, no action needed
- **Window position memory** — drag the app wherever you like; it reopens in the same spot

---

## Tips & Tricks

**Keep it in a corner.** The window is compact (820×430 px) — tuck it in a corner of your screen while you work for a passive at-a-glance view.

**The 7-day gauge is the one that matters most.** The weekly period is your actual billing window. The 5-hour gauge is useful for catching short bursts of heavy use.

**ZEN BALANCE is the sweet spot.** A score of −2 to +2 means you're using Claude at almost exactly the right pace for your billing cycle. Aim for zen.

**If the gauges are blank on first launch**, wait a moment — the first data fetch happens a few seconds after startup. If they stay blank, check that Claude Code is installed and you've logged in at least once.

**If you see "Auth Error"**, your Claude credentials may have expired or been revoked. Log out and back in to Claude Code, then relaunch the app.

**The app updates itself silently.** You don't need to click anything — just leave it running and the gauges will stay fresh.

---

## Other Commands

```bash
./run test    # Run the test suite (no internet or display required)
./run lint    # Check the code for style issues
```