"""
Clue UI — Design System & Glassmorphism Tokens (Cluely-grade polish)
"""

PALETTE = {
    # Base Glass & Backdrop
    "bg_dark":            "#0a0c12",
    "border_subtle":      "rgba(255, 255, 255, 0.12)",
    "border_highlight":   "rgba(255, 255, 255, 0.26)",
    "border_blue":        "rgba(56, 189, 248, 0.42)",
    "border_green":       "rgba(16, 185, 129, 0.45)",

    # High-contrast text (readable over any translucent bg)
    "text_primary":       "#FFFFFF",
    "text_secondary":     "#E2E8F0",
    "text_muted":         "#94A3B8",
    "text_blue":          "#38BDF8",
    "text_green":         "#34D399",
    "text_amber":         "#FBBF24",
    "text_pink":          "#F472B6",

    # ChatGPT-exact syntax token colours
    "code_bg":            "rgba(10, 13, 20, 0.80)",
    "code_header":        "rgba(20, 24, 32, 0.90)",
    "code_border":        "rgba(255, 255, 255, 0.10)",
    "tok_keyword":        "#F472B6",   # pink
    "tok_fn":             "#38BDF8",   # sky blue
    "tok_string":         "#4ADE80",   # mint green
    "tok_number":         "#FB923C",   # amber
    "tok_comment":        "#94A3B8",   # slate
    "tok_type":           "#FDE047",   # yellow
    "tok_op":             "#E2E8F0",   # white

    # Interactive
    "accent_blue0":       "#2563EB",
    "accent_blue1":       "#1D4ED8",
    "green_live":         "#10B981",
    "red_stop":           "#EF4444",
}


def get_hud_stylesheet(opacity: float = 0.65) -> str:
    """
    Generate the main card stylesheet for the chat drawer.
    Ghost (0.40) / Balanced (0.65) / Focus (0.85).
    """
    r, g, b = 14, 17, 24
    border_a = min(0.32, opacity * 0.44)
    inner_a  = max(0.18, opacity * 0.68)

    return f"""
    QFrame#card {{
        background-color: rgba({r}, {g}, {b}, {opacity:.2f});
        border: 1px solid rgba(255, 255, 255, {border_a:.2f});
        border-radius: 20px;
    }}
    QFrame#inner_box {{
        background-color: rgba(8, 10, 16, {inner_a:.2f});
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 10px;
    }}
    /* Ultra-slim translucent scrollbar */
    QScrollBar:vertical {{
        background: transparent;
        width: 5px;
        margin: 3px 1px;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(255, 255, 255, 0.20);
        border-radius: 2px;
        min-height: 22px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: rgba(255, 255, 255, 0.42);
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0; background: none;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
    }}
    QScrollBar:horizontal {{ height: 0; }}
    """


INPUT_STYLESHEET = """
QLineEdit {
    background: rgba(255, 255, 255, 0.06);
    color: #FFFFFF;
    font-size: 14px;
    font-weight: 500;
    font-family: 'Helvetica Neue', Arial, sans-serif;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 9px;
    padding: 7px 12px;
    selection-background-color: rgba(56, 189, 248, 0.32);
}
QLineEdit:focus {
    background: rgba(255, 255, 255, 0.09);
    border: 1px solid rgba(56, 189, 248, 0.65);
}
QLineEdit::placeholder { color: rgba(255, 255, 255, 0.40); }
"""

BUTTON_PRIMARY_STYLESHEET = """
QPushButton {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #2563eb,stop:1 #1d4ed8);
    border: 1px solid rgba(147, 197, 253, 0.30);
    border-radius: 8px;
    color: #FFFFFF;
    font-size: 12.5px;
    font-weight: 650;
    padding: 5px 13px;
}
QPushButton:hover {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #3b82f6,stop:1 #2563eb);
    border-color: rgba(147, 197, 253, 0.55);
}
QPushButton:pressed { background: #1e40af; }
"""

BUTTON_SECONDARY_STYLESHEET = """
QPushButton {
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.11);
    border-radius: 7px;
    color: rgba(255, 255, 255, 0.82);
    font-size: 12px;
    font-weight: 500;
    padding: 4px 10px;
}
QPushButton:hover {
    background: rgba(255, 255, 255, 0.13);
    border-color: rgba(255, 255, 255, 0.22);
    color: #FFFFFF;
}
QPushButton:pressed { background: rgba(255, 255, 255, 0.20); }
"""

# Aliases kept for backward compat with clue_hud.py
BUTTON_COLLAPSED_STYLESHEET = BUTTON_SECONDARY_STYLESHEET
BUTTON_EXPANDED_STYLESHEET  = """
QPushButton {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 rgba(56,189,248,0.22), stop:1 rgba(37,99,235,0.30));
    border: 1px solid rgba(56, 189, 248, 0.50);
    border-radius: 7px;
    color: #38BDF8;
    font-size: 12px;
    font-weight: 650;
    padding: 4px 12px;
}
QPushButton:hover {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 rgba(56,189,248,0.38), stop:1 rgba(37,99,235,0.46));
    border-color: rgba(56, 189, 248, 0.85);
    color: #FFFFFF;
}
QPushButton:pressed { background: rgba(37,99,235,0.55); }
"""
