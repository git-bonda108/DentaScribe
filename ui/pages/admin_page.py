"""Admin — Texas retention sweep."""
from __future__ import annotations
import streamlit as st
from ui.theme import inject_global_css, hero, card_open, card_close


def render() -> None:
    inject_global_css()
    hero("Admin",
         "Retention follows 22 TAC §108.8: adult 5y from last DOS, minor until age 21 "
         "and 5y past last DOS. Purge is two-step, never automatic.",
         pill="DENTASCRIBE  •  ADMIN")
    try:
        from storage.retention import flag_due_for_purge, purge_flagged
    except Exception as e:
        st.error(f"Retention module unavailable: {e}")
        return
    card_open("Retention candidates")
    due = flag_due_for_purge()
    if not due:
        st.success("Nothing is past retention.")
    else:
        st.dataframe(
            [{"encounter_id": d["encounter_id"], "patient_id": d["patient_id"],
              "date_of_service": d["date_of_service"], "reason": d["reason"]} for d in due],
            use_container_width=True, hide_index=True,
        )
        ids = [d["encounter_id"] for d in due]
        confirm = st.checkbox("I have reviewed the above and confirm purge", key="purge_confirm")
        if st.button("🗑  Purge confirmed encounters", disabled=not confirm, type="primary"):
            result = purge_flagged(ids, dry_run=False)
            st.success(f"Purged {result['deleted']} encounters.")
    card_close()
