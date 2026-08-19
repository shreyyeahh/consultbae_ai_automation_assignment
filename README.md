# ConsultBae — AI Automation Take-Home

Merges 3 messy CSVs from different systems into one SQLite database (deduplicating
people across files), builds one n8n automation on top of it, and a Streamlit app
for audio submission collection. Full brief:
[`data/ConsultBae - AI Automation Assignment.pdf`](data/ConsultBae%20-%20AI%20Automation%20Assignment.pdf).

## Repo structure

```
data/               3 raw source CSVs + assignment brief
task1_merge/        merge script + SQLite DB
task2_automation/   n8n flow export (JSON)
task3_audio_app/    Streamlit audio collection app
task4_report.md     data issues report (full detail below is a summary — see the file)
task5_stretch.md    scale/launch stretch answer
```

## Setup

> To be filled in as each task's code is built — placeholder until task1's merge
> script exists.

## Data sources

### `source1_naukri_applicants.csv` — 42 rows

| Column | Type | Notes |
|---|---|---|
| Full Name | string | mixed casing, one abbreviated (`R. Verma`) |
| Email | string | 3 domains; lowercase in this file |
| Phone | string | 3 formats — see Matching Strategy below |
| City | string | casing/whitespace + real aliases (Gurgaon/Gurugram, Bangalore/Bengaluru) |
| Experience (Years) | float | clean |
| Current CTC | float/int | **mixed units** — raw rupees vs lakh-decimals |
| Applied Date | string | 4+ date formats mixed |
| Skills | string | comma list in one cell |

Duplicates: 2 pairs (4 rows) — see [task4_report.md](task4_report.md) #1–2.

### `source2_gig_workers.csv` — 32 raw rows (30 usable)

| Column | Type | Notes |
|---|---|---|
| email_id | string | mixed case |
| worker_name | string | mixed casing |
| rate | string | **mixed units** — `/hr` vs `k/month` |
| location | string | same city issues as source1 |
| status | string | mixed casing, 3 states (active/inactive/paused) |
| skill_tags | string | comma list, lowercase |

Row 12 is fully blank (dropped). Row 20 is a column-shifted duplicate of row 7
(dropped). No phone column at all in this file.

### `source3_cbnexus_contacts.csv` — 31 raw rows (30 usable)

| Column | Type | Notes |
|---|---|---|
| Name | string | ALL CAPS / Title Case mix |
| Phone Number | string | 3 formats — see Matching Strategy below |
| City | string | same casing/alias issues |
| Verified | string | `Y`/`N` vs `Yes`/`No` mixed |
| Projects Completed | int | clean |

Line 16 is the header row repeated as data (dropped). No email column at all in
this file. One unresolved ambiguity: two `Arjun Mehta` rows (5 and 28), same city,
different phone — see [task4_report.md](task4_report.md) #15.

**Full issue-by-issue detail (17 issues, all 3 files + cross-file):
[task4_report.md](task4_report.md).**

## Matching strategy (Task 1)

No field is common to all 3 files — source2 has no phone, source3 has no email —
so a single ID join is impossible by design.

**Approach: exact match on normalized email OR normalized phone**, connected via
union-find (two rows are the same person if their normalized email matches, or
their normalized phone matches; connected groups become one merged person). Name
is used only as a post-merge sanity check, never as a matching criterion.

- Phone normalization: strip all non-digit characters, then drop a leading `91`
  (12-digit case) or leading `0` (11-digit case), leaving a canonical 10-digit
  number.
- Email normalization: lowercase + trim.
- source1↔source2 link via email, source1↔source3 link via phone, source2↔source3
  only link transitively through a shared source1 row.

**Why not fuzzy name-matching:** every row here already carries at least one
reliable identifier (source1/source2 have email, source1/source3 have phone), so
nothing needs fuzzy help to be found. Fuzzy name matching would add a threshold to
justify while *increasing* risk — this dataset has repeated surnames (Mehta,
Chopra, Sharma, Bhatia) and two real `Arjun Mehta` rows with different phone
numbers that a lenient threshold could wrongly merge. Exact-match is simpler, has
a one-sentence explanation, and correctly leaves genuinely ambiguous cases
(Arjun Mehta x2, Deepak Nair x2) unmerged and flagged instead of silently guessed.

## Stuck log

*(Filled in as I actually get stuck — not pre-written. 2-3 hardest places, what I
searched, what I asked AI, what I rejected and why.)*

1. TBD
2. TBD
3. TBD
