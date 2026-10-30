# ClosureCheck

**A verification layer for government complaint portals.**

> "A lie detector for the word *resolved*."

**Live demo:** https://priyanka2007.pythonanywhere.com

Open it on a **phone** for the full citizen flow — filing a complaint needs a live camera and GPS, which a laptop cannot provide. On a laptop you can still browse the complaints list and the department view.

---

## The problem

Complaints filed on government grievance portals — potholes, streetlights, water supply, garbage — are often marked **"resolved"** without the work actually being done.

Nobody checks independently. So closure rates look healthy on paper while the pothole is still there, and the citizen files the same complaint again next month.

As a benchmark: one district-level review of Aaple Sarkar complaints in Gondia showed 868 complaints with 765 marked resolved. Whether those closures were real was never independently verified.

---

## What ClosureCheck does

When a department marks a complaint as resolved, ClosureCheck asks the **citizen who filed it** to go back and take a live after-photo from the same spot.

The app then checks the closure and labels it:

| Label | Meaning |
| --- | --- |
| Verified | Evidence supports that the work was done |
| Not fixed | Evidence shows the problem is still there |
| Unclear | Not enough evidence to decide |

Officers get a dashboard showing **reported closures vs verified closures** — a real closure rate instead of a reported one.

---

## Honest status

**Stage: early prototype.** This is not a finished product, and some of what the concept describes is not built yet.

### What actually works today

- Citizen sign up and login, with hashed passwords and roles
- Filing a complaint with a **live camera photo** and device GPS
- Department officer login via an access code, and a "Mark resolved" button
- After-photo upload by the citizen once a complaint is marked resolved
- **Location check:** the server measures the haversine distance between the before-photo GPS point and the after-photo GPS point
  - more than 30 m apart → status `unclear`
  - within 30 m → status `after_submitted`

### What is NOT built yet

- **The AI photo comparison.** The before/after images are stored but are not yet compared by any model. The `Verified` and `Not fixed` labels described above are the design goal, not current behaviour.
- Same-spot visual matching (planned: OpenCV feature matching)
- Pothole detection — present in the before photo, gone in the after photo (planned: a pretrained detection model)
- Any real-world pilot. Nothing has been tested with an actual municipal body.

So right now the app verifies **where** the after-photo was taken, not **what it shows**.

---

## Anti-misuse measures

Because the whole idea depends on photos being real, the app tries to make faking one harder:

- **Live camera only.** Photos come from `getUserMedia`. There is no gallery upload on the citizen flow.
- **Signed capture token**, valid for 10 minutes, so a photo cannot be submitted long after it was taken.
- **Duplicate image blocking** via a SHA-256 hash of the file, so the same photo cannot be reused.
- **Phone-only gate** on the photo pages, using a User-Agent / `Sec-CH-UA-Mobile` check.
- **CSRF token** on every POST form.
- **Login throttling** — 5 wrong passwords per username per 10 minutes.
- **Ownership check** — a citizen can only add an after-photo to their own complaint.

**Honest limit:** these reduce casual misuse. They do not make it unbreakable. The phone-only check reads headers that a determined person can fake, and a live camera can still be pointed at a screen. A fuller fix would need a native app with stronger attestation, plus the AI checks described above.

---

## Tech

- Python 3 + Flask
- SQLite
- Plain HTML, CSS and JavaScript — no frontend framework
- Installable PWA (manifest + service worker)

---

## Running it locally

```bash
pip install -r requirements.txt
python app.py
```

Then open `http://127.0.0.1:5000`.

**Note on the camera:** browsers only allow camera access over `https://` or on `localhost`. So the camera works on the laptop running the app, but a phone cannot use `http://127.0.0.1:5000`. To test on a phone, the app has to be deployed somewhere that serves `https://`.

To browse the photo pages on a laptop during development, set `ALLOW_DESKTOP=1`.

---

## Environment variables for a real server

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Session signing key. Must be set to a long random value. |
| `OFFICER_CODE` | Access code required to sign up as a department officer. **Must be changed from the default.** |
| `COOKIE_SECURE` | Set to `1` when serving over https. |

Anyone holding `OFFICER_CODE` can mark complaints resolved, which is exactly the power this project exists to check. Keep it private.

---

## Roadmap

1. Same-spot check between before/after photos using OpenCV feature matching
2. Pothole detection with a pretrained model, to decide `Verified` vs `Not fixed`
3. A pilot in one district or municipal council, starting with pothole complaints, measuring reported vs verified closures

---

## Status of this repository

Submitted as an early prototype to the Seva First Innovation Challenge (Government of Maharashtra), October 2026.
