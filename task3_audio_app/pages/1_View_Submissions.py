"""
Task 3 - second view: every submission with a play button and the
extracted properties, newest first.
"""

import streamlit as st

from db import get_connection, list_submissions

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

    with st.container(border=True):
        st.subheader(f"{name} ({phone})")
        st.audio(audio_path)
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Duration", f"{duration_sec:.1f}s")
        col2.metric("Sample rate", f"{sample_rate_hz / 1000:.1f} kHz")
        col3.metric("Bitrate", f"{bitrate_kbps:.0f} kbps")
        col4.metric("Loudness", f"{loudness_dbfs:.1f} dBFS")
        st.caption(f"Quality: {quality_label} · submitted {submitted_at}")
