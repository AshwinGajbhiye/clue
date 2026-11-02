"""
Clue UI — ChatGPT-Style Colorful Code Syntax Highlighter & Markdown Renderer
Turns Markdown + Code Blocks into High-Contrast, Legible Translucent HTML
"""

import html
import re
from typing import Optional

try:
    from pygments import highlight
    from pygments.lexers import get_lexer_by_name, guess_lexer, TextLexer
    from pygments.formatter import Formatter
    HAVE_PYGMENTS = True
except ImportError:
    HAVE_PYGMENTS = False


class ChatGPTCodeHtmlFormatter:
    """
    Renders Pygments tokens into vibrant ChatGPT-style colorized HTML.
    Colors match ChatGPT's dark mode code blocks:
      - Keywords: Pink/Magenta (#F472B6)
      - Functions/Methods: Electric Sky Blue (#38BDF8)
      - Strings: Mint Green (#4ADE80)
      - Numbers/Booleans: Amber/Orange (#FB923C)
      - Comments: Slate Gray (#94A3B8)
      - Types/Classes: Golden Yellow (#FDE047)
      - Operators: Soft Crisp White (#E2E8F0)
    """

    COLOR_MAP = {
        # Keywords
        "Keyword": "#F472B6",
        "Keyword.Constant": "#FB923C",
        "Keyword.Declaration": "#F472B6",
        "Keyword.Namespace": "#F472B6",
        "Keyword.Pseudo": "#F472B6",
        "Keyword.Type": "#FDE047",

        # Names / Functions / Classes
        "Name": "#E2E8F0",
        "Name.Function": "#38BDF8",
        "Name.Class": "#FDE047",
        "Name.Namespace": "#FDE047",
        "Name.Builtin": "#38BDF8",
        "Name.Tag": "#F472B6",
        "Name.Attribute": "#38BDF8",
        "Name.Decorator": "#F472B6",

        # Literals
        "Literal": "#FB923C",
        "Literal.String": "#4ADE80",
        "Literal.String.Doc": "#94A3B8",
        "Literal.String.Interpol": "#4ADE80",
        "Literal.Number": "#FB923C",
        "Literal.Number.Integer": "#FB923C",
        "Literal.Number.Float": "#FB923C",

        # Comments
        "Comment": "#94A3B8",
        "Comment.Single": "#94A3B8",
        "Comment.Multiline": "#94A3B8",

        # Operators & Punctuation
        "Operator": "#E2E8F0",
        "Punctuation": "#CBD5E1",
    }

    @classmethod
    def highlight_code(cls, code: str, lang: str = "cpp") -> str:
        """Colorize raw code string into rich HTML."""
        code = code.strip("\n")
        lang_normalized = (lang or "cpp").lower().strip()
        aliases = {"c++": "cpp", "py": "python", "js": "javascript", "ts": "typescript"}
        lang_normalized = aliases.get(lang_normalized, lang_normalized)

        if HAVE_PYGMENTS:
            try:
                try:
                    lexer = get_lexer_by_name(lang_normalized, stripall=True)
                except Exception:
                    lexer = TextLexer(stripall=True)

                tokens = lexer.get_tokens(code)
                highlighted_spans = []
                for ttype, value in tokens:
                    val_escaped = html.escape(value)
                    ttype_str = str(ttype)

                    color = None
                    for key, c in cls.COLOR_MAP.items():
                        if key in ttype_str:
                            color = c
                            break

                    if color:
                        highlighted_spans.append(f'<span style="color: {color};">{val_escaped}</span>')
                    else:
                        highlighted_spans.append(val_escaped)

                return "".join(highlighted_spans)
            except Exception:
                pass

        # Fallback regex-based colorizer if Pygments is unavailable
        return cls._fallback_regex_highlight(code, lang_normalized)

    @classmethod
    def _fallback_regex_highlight(cls, code: str, lang: str) -> str:
        """Robust fallback tokenizer with regex."""
        escaped = html.escape(code)

        # Comments
        escaped = re.sub(
            r"(&#x2F;&#x2F;.*$|//.*$)",
            r'<span style="color: #94A3B8; font-style: italic;">\1</span>',
            escaped,
            flags=re.MULTILINE,
        )
        # Strings
        escaped = re.sub(
            r'(&quot;.*?&quot;|&#39;.*?&#39;|".*?"|\'.*?\')',
            r'<span style="color: #4ADE80;">\1</span>',
            escaped,
        )
        # Numbers
        escaped = re.sub(
            r"\b(\d+)\b",
            r'<span style="color: #FB923C;">\1</span>',
            escaped,
        )
        # Keywords
        kw_pattern = r"\b(auto|int|float|double|char|bool|void|class|struct|def|return|if|else|for|while|const|let|var|new|delete|public|private|vector|string|std|import|from|async|await)\b"
        escaped = re.sub(
            kw_pattern,
            r'<span style="color: #F472B6; font-weight: 600;">\1</span>',
            escaped,
        )
        # Functions
        escaped = re.sub(
            r"\b([a-zA-Z_][a-zA-Z0-9_]*)(?=\s*\()",
            r'<span style="color: #38BDF8;">\1</span>',
            escaped,
        )
        return escaped


def render_markdown_to_rich_html(markdown_text: str, default_lang: str = "cpp") -> str:
    """
    Converts complete AI response (Markdown + Code fences) into a high-contrast,
    gorgeous HTML document with ChatGPT-style code blocks and distinct sections.
    """
    if not markdown_text:
        return ""

    # 1. Extract triple-backtick code blocks and replace with styled HTML cards
    def replace_code_block(match):
        lang = match.group(1).strip() if match.group(1) else default_lang
        raw_code = match.group(2)
        highlighted_inner = ChatGPTCodeHtmlFormatter.highlight_code(raw_code, lang)

        display_lang = lang.upper() if lang else "CODE"
        card_html = f"""
        <div style="
            background: rgba(13, 16, 23, 0.88);
            border: 1px solid rgba(255, 255, 255, 0.16);
            border-radius: 10px;
            margin: 10px 0;
            overflow: hidden;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
        ">
            <!-- Code Block Header -->
            <div style="
                background: rgba(22, 27, 34, 0.95);
                padding: 6px 14px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.08);
                display: flex;
                justify-content: space-between;
                align-items: center;
            ">
                <span style="color: #94A3B8; font-size: 11px; font-weight: 700; font-family: monospace; letter-spacing: 0.5px;">
                    {display_lang}
                </span>
            </div>
            <!-- Code Block Body -->
            <pre style="
                margin: 0;
                padding: 12px 14px;
                font-family: 'JetBrains Mono', 'Fira Code', 'SF Mono', Menlo, Consolas, monospace;
                font-size: 13px;
                line-height: 1.55;
                color: #E2E8F0;
                white-space: pre-wrap;
                word-wrap: break-word;
            "><code>{highlighted_inner}</code></pre>
        </div>
        """
        return card_html

    # Replace ```lang ... ``` blocks
    processed = re.sub(r"```([a-zA-Z0-9_\-\+]*)\n(.*?)```", replace_code_block, markdown_text, flags=re.DOTALL)

    # 2. Format section headers: ### 🗣️ WHAT TO SAY, etc.
    def format_headers(match):
        title = match.group(1).strip()
        color = "#38BDF8" if "SAY" in title else ("#34D399" if "CODE" in title else "#FBBF24")
        return f"""
        <div style="
            color: {color};
            font-size: 13.5px;
            font-weight: 700;
            letter-spacing: 0.4px;
            margin-top: 14px;
            margin-bottom: 6px;
            text-transform: uppercase;
            text-shadow: 0 1px 3px rgba(0,0,0,0.9);
        ">
            {title}
        </div>
        """
    processed = re.sub(r"^###\s*(.*?)$", format_headers, processed, flags=re.MULTILINE)
    processed = re.sub(r"^##\s*(.*?)$", format_headers, processed, flags=re.MULTILINE)

    # 3. Format inline code `code`
    processed = re.sub(
        r"`([^`]+)`",
        r'<code style="background: rgba(255, 255, 255, 0.12); color: #F472B6; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-size: 12px;">\1</code>',
        processed,
    )

    # 4. Format bold text **text**
    processed = re.sub(
        r"\*\*([^\*]+)\*\*",
        r'<strong style="color: #FFFFFF; font-weight: 700;">\1</strong>',
        processed,
    )

    # 5. Format bullet points
    processed = re.sub(
        r"^[ \t]*[\-\*]\s+(.*)$",
        r'<div style="margin-left: 12px; margin-bottom: 4px; color: #E2E8F0; line-height: 1.5; font-size: 13.5px;">• \1</div>',
        processed,
        flags=re.MULTILINE,
    )

    # Wrap in root container with high-contrast text shadow for legibility over translucent window
    root_html = f"""
    <div style="
        color: #E2E8F0;
        font-family: 'Helvetica Neue', Arial, sans-serif;
        font-size: 13.5px;
        line-height: 1.6;
        text-shadow: 0 1px 2px rgba(0, 0, 0, 0.85);
    ">
        {processed}
    </div>
    """
    return root_html
