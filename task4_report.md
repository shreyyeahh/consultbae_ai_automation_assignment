# Task 4 — Data Issues Report

Every issue below was found by reading the 3 raw CSVs directly (see analysis in commit
history / conversation). Format: **Issue → why it was a problem → what I did.**

## source1_naukri_applicants.csv

1. **Duplicate person, different name format** — rows 25 (`R. Verma`) and 31 (`Rohit
   Verma`) have identical email, phone, city, experience, CTC, date, and skills; only
   the name string differs. A full-row-exact dedup would miss this since the rows
   aren't byte-identical. Resolved by matching on normalized phone/email instead of
   name or full-row equality, then keeping one canonical record.

2. **Duplicate person, alt email** — rows 27 and 37 are both `Nikhil Chopra`, same
   phone/city/experience/CTC/date/skills, but row 27's email is
   `alt.nikhil.chopra70@example.com` vs row 37's `nikhil.chopra70@example.com`. An
   email-only matching strategy would treat these as two different people. Caught by
   also matching on normalized phone; merged into one record, kept the non-"alt"
   email as primary and logged the alt one.

3. **Phone number format inconsistency** — three formats appear: bare 10-digit
   (`9000000237`), leading-0 11-digit (`09000000287`), and `+91`-prefixed
   (`+919000000254`). Left as-is, the same person reads as up to three different
   phone numbers. Normalized every phone to a canonical 10-digit string by stripping
   non-digits and dropping a leading `91` or `0`.

4. **City name inconsistency, including real aliases** — beyond casing/whitespace
   (`GURGAON` vs `gurugram `), `Gurgaon`/`Gurugram` and `Bangalore`/`Bengaluru` are
   the same cities under old/new official names. Left unresolved, location-based
   reporting or automations would fragment across duplicate city buckets. Trimmed
   whitespace, standardized casing, and mapped known aliases to one canonical
   spelling via a small lookup dict.

5. **Current CTC in mixed units** — roughly half the rows are raw rupees (e.g.
   `417964`) and half are small decimals (e.g. `4.2`, `8.3`) that read as lakhs.
   Treated naively, `4.2` would be read as four rupees, wrecking any CTC comparison
   or aggregation. Any value under 100 is treated as lakhs and multiplied by
   100,000; the raw original value is kept alongside for audit.

6. **Applied Date in 4+ formats, some genuinely ambiguous** — `DD-MM-YYYY`
   (`24-07-2026`), ISO `YYYY-MM-DD` (`2026-08-08`), `D Mon YYYY` (`7 Jul 2026`), and
   `MM/DD/YYYY` (`07/13/2026`) all appear; values like `07/03/2026` are ambiguous
   between 7-Mar and 3-Jul with no way to disambiguate from the data alone. Parsed
   with format-specific rules per detected pattern; rows that stay genuinely
   ambiguous are flagged rather than guessed.

## source2_gig_workers.csv

7. **Fully blank row** — line 12 has all 6 fields empty. Ingesting it as-is would
   either error out or create a null "ghost" record. Dropped any row where every
   field is empty before processing.

8. **Column-shifted duplicate row** — line 20 (`"react, javascript, mysql",
   ISHA.CHOPRA95@MAILTEST.EXAMPLE.ORG, Isha Chopra, 1406/hr, Pune, active`) is the
   exact same record as line 7, just with `skill_tags` rotated into the first column
   instead of the last. Parsed naively, every field on that row would land in the
   wrong column and corrupt the record. Identified it as a duplicate of line 7 and
   dropped it rather than writing one-off realignment logic for a single row.

9. **Rate column mixes units** — `1415/hr` and `15k/month` appear in the same
   column with no separate unit field. Comparing or summing these directly without
   converting would silently fabricate numbers, and a safe hours/month conversion
   factor isn't derivable from this data. Kept the raw string plus a parsed
   `(amount, unit)` pair instead of forcing a unit conversion.

10. **Status casing + a third state** — `Active`/`active`/`ACTIVE` all appear, plus
    separate `Inactive` and `paused` values. Case-sensitive downstream logic (e.g.
    an n8n filter on `status == "Active"`) would silently miss the lowercase/caps
    variants. Lowercased and mapped to a controlled 3-value set:
    `active` / `inactive` / `paused`.

11. **Email casing inconsistent across rows** — e.g.
    `ISHA.CHOPRA95@MAILTEST.EXAMPLE.ORG` vs lowercase emails elsewhere in the same
    file and in source1. An exact-match join against source1's lowercase emails
    would fail on these. Lowercased and trimmed every email before any comparison.

## source3_cbnexus_contacts.csv

12. **Embedded duplicate header row** — line 16 repeats the header
    (`Name,Phone Number,City,Verified,Projects Completed`) verbatim as if it were a
    data row, most likely from concatenating two exports without stripping the
    second header. Parsed naively, "Name" becomes a fake person record. Detected
    any data row that exactly matches the header and dropped it.

13. **Verified column mixes boolean representations** — `Y`/`N` and `Yes`/`No`/`yes`
    both appear for the same underlying yes/no field. Any downstream boolean
    filter or count would treat these as different values. Mapped
    `{Y, Yes, yes}` → `True` and `{N, No}` → `False` into one boolean column.

14. **Phone Number format inconsistency (again, 3 formats)** — bare 10-digit
    (`9000000268`), 12-digit `91`-prefixed with no plus (`919000000231`), and
    `+91-`-prefixed with a dash (`+91-9000000131`) all appear in this file too. Same
    problem as source1: the same number reads as multiple different strings.
    Applied the same normalization (strip non-digits, drop leading `91`/`0`) to get
    one canonical join key.

15. **Ambiguous duplicate name, different phone (unresolved by design)** — two rows
    are both named `Arjun Mehta`, both located in Noida: row 5 has phone
    `...9000000131`, row 28 has phone `...9000000272`. Nothing in this file or the
    others proves whether this is one person with a changed number or two different
    people sharing a name — merging or splitting would both be a guess. Left as two
    separate records and flagged here rather than silently decided.

## Cross-file

16. **No field is common to all 3 files** — source2 has no phone column, source3 has
    no email column, so a single "join on ID" approach is impossible by design
    (as the brief warned). Used normalized phone as the bridge for
    source1↔source3 and normalized email as the bridge for source1↔source2, with
    source1 acting as the connective file between the other two. See the matching
    strategy write-up in the README for the full reasoning.

17. **Same-name, different-source ambiguity: two "Deepak Nair" entries in
    source2** — row 15 (`deepak.nair44@example.com`) and row 32
    (`DEEPAK.NAIR57@example.in`) share a name but have different emails and no
    phone in this file to disambiguate. Whether these are the same person with two
    accounts or two different people can't be determined from source2 alone.
    Left as separate records unless a phone-based match from source1/source3 later
    ties one of them to a specific person.
