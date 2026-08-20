"""
Task 3 - audio submission form. Collects name + phone, accepts either an
in-browser recording (st.audio_input) or a file upload - either is enough,
per the brief - extracts required metadata, and stores both the audio file
and a DB record linked to a Task 1 `people` row via phone matching.
"""

import uuid
from pathlib import Path

import streamlit as st

from audio_utils import UnsupportedAudioError, extract_metadata
from db import find_or_create_person, get_connection, insert_submission

UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

st.set_page_config(page_title="Submit Audio - ConsultBae")
st.title("Submit a recording")

with st.form("submission_form"):
    name = st.text_input("Name")
    phone = st.text_input("Phone number")

    st.write("Record in your browser, or upload a file instead:")
    recorded = st.audio_input("Record audio")
    uploaded = st.file_uploader(
        "...or upload an audio file", type=["wav", "mp3", "ogg", "m4a", "webm"]
    )

    submitted = st.form_submit_button("Submit")

if submitted:
    audio_file = recorded or uploaded

    if not name.strip() or not phone.strip():
        st.error("Name and phone number are both required.")
    elif not audio_file:
        st.error("Record or upload an audio clip before submitting.")
    else:
        original_filename = getattr(audio_file, "name", "recording.wav")
        extension = Path(original_filename).suffix or ".wav"
        temp_path = UPLOAD_DIR / f"{uuid.uuid4().hex}{extension}"
        temp_path.write_bytes(audio_file.getvalue())

        # Extract metadata BEFORE touching the DB - a failed decode must
        # never leave a half-written row behind.
        try:
            metadata = extract_metadata(temp_path)
        except UnsupportedAudioError as exc:
            temp_path.unlink(missing_ok=True)
            st.error(f"Couldn't read that audio file: {exc}")
        else:
            conn = get_connection()
            try:
                person_id, is_new = find_or_create_person(conn, name, phone)
            except ValueError as exc:
                temp_path.unlink(missing_ok=True)
                st.error(str(exc))
            else:
                # Store just the filename, not an absolute path - an
                # absolute path baked in on this machine (e.g. a Windows
                # `D:\...` path) is meaningless once the DB is deployed
                # elsewhere. The full path is reconstructed from
                # UPLOAD_DIR wherever it's needed instead.
                insert_submission(conn, person_id, temp_path.name, original_filename, metadata)
                st.success(
                    f"Saved. Linked to {'a new' if is_new else 'an existing'} "
                    f"person (person_id={person_id})."
                )
                st.json(metadata)
            finally:
                conn.close()
