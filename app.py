import streamlit as st

st.set_page_config(page_title="Cash Radar", page_icon="📡", layout="wide")

from src import ui  # noqa: E402  (must come after set_page_config)

ui.render_app()