"""
app.py — Streamlit UI for the Payment Collection AI Agent
"""

import streamlit as st
from agent import Agent

st.set_page_config(
    page_title="Payment Collection Agent",
    page_icon="💳",
    layout="centered",
)

st.title("💳 Payment Collection Agent")
st.caption("Securely pay your outstanding balance through a guided conversation.")

# ── Session state init ─────────────────────────────────────────────────────

if "agent" not in st.session_state:
    st.session_state.agent = Agent()

if "messages" not in st.session_state:
    st.session_state.messages = []  # list of {"role": "user"|"assistant", "content": str}

if "session_over" not in st.session_state:
    st.session_state.session_over = False

# ── Render existing chat history ───────────────────────────────────────────

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── Helper ─────────────────────────────────────────────────────────────────

def is_terminal_stage() -> bool:
    stage = st.session_state.agent.sm.stage
    return stage in ("COMPLETED", "FAILED")


def add_message(role: str, content: str):
    st.session_state.messages.append({"role": role, "content": content})


# ── Show "Start" button before first message ──────────────────────────────

if not st.session_state.messages and not st.session_state.session_over:
    if st.button("Start Session", type="primary"):
        with st.spinner("Connecting..."):
            response = st.session_state.agent.next("Hello")
        add_message("assistant", response["message"])
        st.rerun()

# ── Chat input (disabled once session ends) ────────────────────────────────

elif not st.session_state.session_over:
    user_input = st.chat_input("Type your message here…")

    if user_input:
        # Show user message immediately
        add_message("user", user_input)
        with st.chat_message("user"):
            st.markdown(user_input)

        # Get agent response
        with st.chat_message("assistant"):
            with st.spinner("Processing…"):
                try:
                    response = st.session_state.agent.next(user_input)
                    reply = response["message"]
                except Exception as e:
                    reply = f"An unexpected error occurred: {e}. Please refresh and try again."

            st.markdown(reply)
            add_message("assistant", reply)

        # Lock input if session reached a terminal stage
        if is_terminal_stage():
            st.session_state.session_over = True
            st.rerun()

# ── Terminal state banner ──────────────────────────────────────────────────

if st.session_state.session_over:
    stage = st.session_state.agent.sm.stage
    if stage == "COMPLETED":
        st.success("Session complete. Your payment was processed successfully.")
    else:
        st.error("Session terminated. Please contact support to proceed.")

    if st.button("Start New Session"):
        st.session_state.agent = Agent()
        st.session_state.messages = []
        st.session_state.session_over = False
        st.rerun()
