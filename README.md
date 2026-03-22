![](banner.jpg)

# Claude Gauge

Ever wonder if you're burning through your Claude Code subscription too fast — or leaving it untouched when you could be getting more out of it? Claude Gauge gives you the answer at a glance, right on your desktop.

It shows two retro-style analog dials tracking your Claude usage across two time windows, plus a mood panel that reacts with a healthy dose of humour. Think of it as a fuel gauge for your AI subscription.

---

## What It Does

### Two Analog Gauges

**5-Hour Window** — how much of your rolling 5-hour usage allowance you've consumed, compared to how much of that window has passed. Great for catching short bursts of heavy use before they add up.

**7-Day Period** — the big picture. This tracks your usage across your full weekly billing cycle. If you're pacing well here, you're in good shape overall.

Each gauge has two needles:
- One needle shows your **actual usage**
- The other shows your **ideal pace** — where you'd be if you spread your usage evenly

If your usage needle is behind the pace needle, you're doing great. If it's ahead, it might be time to ease up a little.

### Countdown Timers

Each gauge shows a timer counting down to when that window resets, so you always know how much runway you have left.

### Mood Panel

Below the gauges is a personality score that captures your overall vibe in one line. It updates automatically to reflect how your usage compares to a healthy pace:

| Mood | What It Means |
|---|---|
| **CRUSHING IT** | Way under budget — you've got loads of headroom |
| **VERY COMFY** | Nicely ahead of pace |
| **LOOKING GOOD** | Comfortably on track |
| **ZEN BALANCE** | Almost exactly where you should be |
| **WATCH IT...** | Starting to run a little hot |
| **PANIC MODE** | Over budget, things are getting spicy |
| **RED ALERT!** | Significantly over budget |
| **MELTDOWN 💥** | You have been using Claude *a lot* |

Each mood comes with a matching illustration and a plain-English pace summary with a colour-coded dot (🟢 🟡 🔴) so you can read it in a split second.

---

## Getting Started

**What you need:**
- A Mac running macOS
- Python 3.10 or later (comes pre-installed on most Macs)
- An active Claude Code subscription — the app reads your existing login, nothing extra to set up
- `tmux` installed — if you don't have it yet, run `brew install tmux` in your Terminal

**Launch it:**

```bash
git clone <this-repo>
cd claude-usage
./run start
```

The very first launch takes a moment to set itself up automatically. After that, opening it is instant. The gauges may take a few seconds to show data on first load — that's normal.

---

## Feature Guide

### Auto-Refresh
Claude Gauge quietly polls your usage every 5 minutes in the background. You don't need to click anything or manually refresh — just leave it open and it stays current.

### Window Position Memory
Drag the window wherever you like on your screen. Claude Gauge remembers where you put it and reopens in the same spot next time.

### Auto-Start at Login
Once you've launched it the first time, Claude Gauge is registered to start automatically when you log in. It'll always be there when you need it.

### Credential Handling
If your Claude session needs to be renewed, the app takes care of it silently in the background. You won't be interrupted mid-work.

---

## Tips & Tricks

**Tuck it in a corner.** The window is deliberately compact. Position it in a corner of your screen so it's visible but out of the way — a passive at-a-glance view while you work.

**Watch the 7-day gauge most.** The weekly period is your actual billing window and the most meaningful signal. The 5-hour gauge is a handy early warning system, but the weekly one is what matters.

**ZEN BALANCE is the sweet spot.** If the mood panel says ZEN BALANCE, you're using Claude at almost exactly the right pace for your billing cycle. That's the goal.

**The two needles tell the whole story.** You don't need to read any numbers — just glance at whether the usage needle is ahead of or behind the pace needle. Behind = relaxed. Ahead = keep an eye on it.

**If the gauges stay blank after a minute**, make sure you've logged into Claude Code at least once on this machine. A quick `claude` in your Terminal to check your login status should do it.

**If you see "Auth Error"**, your credentials may have expired. Open Terminal and log back into Claude Code, then relaunch the app.

---

## Other Commands

```bash
./run test    # Run the test suite (no internet or display required)
./run lint    # Check the code for style issues
```