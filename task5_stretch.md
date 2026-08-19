# Task 5 — Stretch: 5,000 Gig Workers, One Weekend

Grounded in Task 3's actual implementation (`task3_audio_app/`), not
speculation — every failure point below traces to a specific line of code.

## What breaks first

**The submissions list page, almost immediately.** `pages/1_View_Submissions.py`
runs one unbounded `SELECT * FROM submissions ... ORDER BY submitted_at DESC`
and renders every row as its own `st.container` with an embedded `st.audio`
player. At 5,000 submissions that's 5,000 audio players rendered into one
page on first load — the browser tab freezes or crashes long before the
database itself is stressed. This is the single most certain, most immediate
failure, and it's a UI bug, not an infrastructure one — no amount of server
scaling fixes it without pagination.

**SQLite's single-writer lock, right behind it.** Every submission runs at
least one write transaction (`find_or_create_person` may `INSERT` a new
`people` row, then `insert_submission` always `INSERT`s). SQLite locks the
whole database *file* for the duration of a write — only one writer at a
time, full stop. A weekend launch means many people submitting audio in the
same few-second windows; writers start queuing, then timing out
(`database is locked` errors), well before 5,000 total submissions are
reached — this is about concurrent writes per second, not total row count.

**A duplicate-person race condition, silently.** `find_or_create_person`
does a `SELECT` to check for an existing phone match, then an `INSERT` if
none is found — two separate, non-atomic steps. If two people submit with
the *same brand-new phone number* within the same narrow window (plausible
at real concurrency — e.g. a testing team, or two family members sharing a
line), both requests can see "no match" and both `INSERT`, creating two
`people` rows for one real identity. Nothing in the current schema prevents
this — there's no `UNIQUE` constraint on `canonical_phone`. This one is
dangerous specifically because it fails *quietly* — no error, no crash, just
slowly corrupting the "one person, one record" guarantee Task 1 was built
around.

## Storage

Audio files are saved to local disk (`task3_audio_app/uploads/`). Two
distinct problems, not one: (1) **growth** — 5,000 submissions at the
~0.3–1.2MB per file observed in real testing is only a few GB total, not
alarming by itself; but (2) **durability** — if this were deployed on
ephemeral hosting (Streamlit Community Cloud, most free-tier PaaS), the
local filesystem is commonly wiped on every redeploy or restart. Every
previously-submitted recording would vanish the next time the app updates,
with the database rows pointing at files that no longer exist. Fix: object
storage (S3/GCS/equivalent) instead of local disk — survives redeploys, and
decouples file storage from app compute so scaling one doesn't require
scaling the other.

## Uploads / processing

Audio extraction (`pydub` + an `ffprobe` subprocess call) is synchronous and
CPU-bound, running inline in the same request that's serving the user's
page. On a small hosting instance, several concurrent submissions competing
for CPU turns "instant" into "the page hangs for 10+ seconds," and a burst
of submissions (the realistic shape of "5,000 users in a weekend," not a
steady trickle) queues them all behind whatever's currently decoding. Fix:
accept the upload immediately, hand the file off to a background job queue
(e.g. a simple task queue backed by Redis, or serverless functions) for
extraction, and let the UI show "processing" rather than blocking on it.

## Duplicates

Two distinct kinds, both real: **identity duplicates** (the race condition
above — same person, two `people` rows) and **submission duplicates**
(nothing stops a double-click on Submit, or a retried request after a slow
network response, from inserting the same recording twice — there's no
idempotency key on the submit action). Fix identity duplicates with a
`UNIQUE` constraint on `canonical_phone` (nulls excluded) and an
`INSERT ... ON CONFLICT DO NOTHING` pattern instead of check-then-insert.
Fix submission duplicates with a client-side idempotency token per form
render, checked server-side before insert.

## Cost

Local-disk storage is free at this scale but doesn't survive redeploys (see
Storage). Serving audio playback directly from the app's own backend (rather
than a CDN in front of object storage) means every "View Submissions" page
load pulls file bytes through the same process handling form submissions —
bandwidth and compute compete with each other under load. At 5,000 users
this is still probably affordable on any real cloud provider, but it's the
first cost line that scales *with usage* rather than being fixed, and it's
solved by the same fix as Storage: object storage + CDN in front of it.

## What I'd change before a real launch, in priority order

1. **Paginate (or lazy-load) the submissions view** — the single most certain
   failure, and the cheapest to fix.
2. **Add a `UNIQUE` constraint on `people.canonical_phone`** and switch
   `find_or_create_person` to an atomic insert-or-ignore pattern — closes the
   race condition before it ever needs to be debugged in production.
3. **Move audio storage to S3/equivalent** — removes both the durability risk
   on ephemeral hosting and the growth concern long-term.
4. **Move to Postgres** — real concurrent-write support instead of SQLite's
   single-writer lock; this is the change that unlocks actual concurrent
   submission volume.
5. **Decouple extraction into a background job** — keeps the submit page
   fast regardless of how loaded the audio-processing step is.
