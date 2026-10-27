"""Opportunity Scout Bot
Scans jobs, bonuses/promos and new site launches, scores them,
flags scam red flags, and sends the best new items to Telegram.
"""
import os
import re
import json
import time
import hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import feedparser
import requests

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SEEN_FILE = "seen.json"
MAX_ALERTS_PER_RUN = 10
MAX_AGE_HOURS = 48
MIN_SCORE = 2


def gnews(q):
    """Google News RSS search, last 2 days, Nigeria edition."""
    return ("https://news.google.com/rss/search?q=" + quote(q + " when:2d")
            + "&hl=en-NG&gl=NG&ceid=NG:en")


# (category, source name, feed url) -- add or remove freely
FEEDS = [
    # JOBS
    ("JOB", "WeWorkRemotely", "https://weworkremotely.com/remote-jobs.rss"),
    ("JOB", "RemoteOK", "https://remoteok.com/remote-jobs.rss"),
    ("JOB", "News: Nigeria jobs", gnews("jobs Nigeria hiring graduate trainee")),
    ("JOB", "News: Jobberman/MyJobMag",
     gnews("site:jobberman.com OR site:myjobmag.com")),
    ("JOB", "News: biochemist/lab jobs", gnews("biochemist OR laboratory jobs Nigeria")),
    # BONUSES / PROMOS
    ("BONUS", "Reddit beermoney", "https://www.reddit.com/r/beermoney/new/.rss"),
    ("BONUS", "Reddit freebies", "https://www.reddit.com/r/freebies/new/.rss"),
    ("BONUS", "Reddit signupsforpay", "https://www.reddit.com/r/signupsforpay/new/.rss"),
    ("BONUS", "News: signup bonus", gnews("signup bonus OR referral bonus OR cashback Nigeria")),
    ("BONUS", "News: grants", gnews("grant OR scholarship OR fellowship Nigeria apply")),
    # NEW SITE / PLATFORM LAUNCHES
    ("LAUNCH", "Product Hunt", "https://www.producthunt.com/feed"),
    ("LAUNCH", "BetaList", "https://betalist.com/feed"),
    ("LAUNCH", "News: new platform launch", gnews("launches OR launched app Nigeria earn rewards")),
]

# word -> weight
POSITIVE = {
    "bonus": 2, "signup": 2, "sign-up": 2, "sign up": 1, "referral": 2,
    "free": 1, "reward": 2, "cashback": 2, "giveaway": 2, "airdrop": 2,
    "grant": 3, "scholarship": 2, "fellowship": 2, "paid": 1, "earn": 1,
    "launch": 2, "launching": 2, "launched": 2, "beta": 2, "early access": 3,
    "waitlist": 2, "founding": 2, "hiring": 2, "vacancy": 2, "recruit": 2,
    "internship": 2, "graduate trainee": 3, "remote": 1, "nigeria": 2,
    "worldwide": 1, "anywhere": 1, "biochemist": 3, "laboratory": 2,
    "no experience": 2, "entry level": 2, "entry-level": 2,
}

RED_FLAGS = [
    "guaranteed profit", "guaranteed return", "double your money",
    "risk-free", "risk free", "100% profit", "daily profit", "passive income",
    "ponzi", "hyip", "investment plan", "get rich", "send btc", "send usdt",
    "deposit to withdraw", "pay to join", "registration fee", "pay a fee",
    "mlm", "binary plan", "doubling",
]


def load_seen():
    try:
        with open(SEEN_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(seen[-5000:], f)


def uid(link):
    return hashlib.sha1(link.encode()).hexdigest()[:16]


def entry_time(e):
    t = e.get("published_parsed") or e.get("updated_parsed")
    if not t:
        return None
    return datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)


def clean(text):
    return re.sub(r"<[^>]+>", " ", text or "").replace("&nbsp;", " ")


def score_item(text):
    t = text.lower()
    score = sum(w for k, w in POSITIVE.items() if k in t)
    flags = [r for r in RED_FLAGS if r in t]
    return score, flags


def send(msg):
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": msg, "disable_web_page_preview": "false"},
        timeout=30,
    )
    if not r.ok:
        print("Telegram error:", r.text)


def main():
    seen = load_seen()
    seen_set = set(seen)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
    found = []

    for cat, name, url in FEEDS:
        try:
            resp = requests.get(url, timeout=25,
                                headers={"User-Agent": "Mozilla/5.0 OpportunityScout/1.0"})
            feed = feedparser.parse(resp.content)
        except Exception as ex:
            print(f"[skip] {name}: {ex}")
            continue
        print(f"{name}: {len(feed.entries)} entries")
        for e in feed.entries:
            link = e.get("link")
            if not link:
                continue
            i = uid(link)
            if i in seen_set:
                continue
            seen_set.add(i)
            seen.append(i)
            ts = entry_time(e)
            if ts and ts < cutoff:
                continue
            title = clean(e.get("title", "")).strip()
            body = clean(e.get("summary", ""))[:600]
            score, flags = score_item(title + " " + body)
            if cat == "LAUNCH":
                score += 1  # launches are the priority
            if score >= MIN_SCORE:
                found.append((score, cat, name, title, link, flags))

    found.sort(key=lambda x: x[0], reverse=True)
    icons = {"JOB": "💼", "BONUS": "🎁", "LAUNCH": "🚀"}
    for score, cat, name, title, link, flags in found[:MAX_ALERTS_PER_RUN]:
        warn = ("\n⚠️ RED FLAGS: " + ", ".join(flags) + "\nVerify before you pay or deposit anything."
                if flags else "")
        send(f"{icons[cat]} {cat} (score {score})\n{title}\nSource: {name}\n{link}{warn}")
        time.sleep(1)

    save_seen(seen)
    print(f"Done. {len(found)} matches, sent {min(len(found), MAX_ALERTS_PER_RUN)}.")


if __name__ == "__main__":
    main()
