"""
Task 3 - second view: every submission with a play button and the
extracted properties, newest first.
"""

from pathlib import Path

import streamlit as st

from db import get_connection, list_submissions

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"

st.set_page_config(page_title="Submissions - ConsultBae")
st.title("All submissions")

conn = get_connection()
rows = list_submissions(conn)
conn.close()

if not rows:
    st.info("No submissions yet.")

for row in rows:
    (submission_id, name, phone, audio_path, duration_sec, sample_rate_hz,
     bitrate_kbps, loudness_dbfs, quality_label, submitted_at) = row

    # audio_path is stored as just a filename (see app.py) - reconstructed
    # here against this machine's own uploads folder, not trusted as a
    # standalone path. Path(...).name also tolerates old rows that still
    # have a full path baked in, by discarding everything but the filename.
    audio_file = UPLOAD_DIR / Path(audio_path).name

    with st.container(border=True):
        st.subheader(f"{name} ({phone})")
        if audio_file.exists():
            st.audio(str(audio_file))
        else:
            st.warning(f"Audio file not found on this machine: {audio_file.name}")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Duration", f"{duration_sec:.1f}s")
        col2.metric("Sample rate", f"{sample_rate_hz / 1000:.1f} kHz")
        col3.metric("Bitrate", f"{bitrate_kbps:.0f} kbps")
        col4.metric("Loudness", f"{loudness_dbfs:.1f} dBFS")
        st.caption(f"Quality: {quality_label} · submitted {submitted_at}")
