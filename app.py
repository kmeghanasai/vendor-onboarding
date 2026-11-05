"""Streamlit entry point with the shared visual theme applied."""

from visual_theme import apply_visual_theme
from vendor_ui import main


apply_visual_theme()


if __name__ == "__main__":
    main()
