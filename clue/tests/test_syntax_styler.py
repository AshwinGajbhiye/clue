"""
Unit tests for Clue's ChatGPT-Style Syntax Highlighter & Markdown Renderer
"""

import unittest
from clue.ui.syntax_styler import (
    ChatGPTCodeHtmlFormatter,
    render_markdown_to_rich_html,
)


class TestSyntaxStyler(unittest.TestCase):

    def test_cpp_code_highlighting(self):
        code = """int main() {
    vector<int> nums = {1, 2, 3};
    return 0;
}"""
        highlighted = ChatGPTCodeHtmlFormatter.highlight_code(code, "cpp")
        self.assertIn("int", highlighted)
        self.assertIn("return", highlighted)
        # Check that colors were applied
        self.assertTrue("<span style=" in highlighted)

    def test_python_code_highlighting(self):
        code = """def solve(nums):
    # Two pointer approach
    return sorted(nums)
"""
        highlighted = ChatGPTCodeHtmlFormatter.highlight_code(code, "python")
        self.assertIn("def", highlighted)
        self.assertIn("solve", highlighted)
        self.assertTrue("<span style=" in highlighted)

    def test_markdown_to_rich_html(self):
        markdown_input = """### 🗣️ WHAT TO SAY TO THE INTERVIEWER
- Use two pointers on sorted array.
- Time complexity is O(N log N).

### 💻 CODE SOLUTION
```cpp
#include <vector>
using namespace std;
vector<int> solve() { return {}; }
```

### ⏱️ COMPLEXITY & TRADEOFFS
- Time: O(N log N)
- Space: O(1)
"""
        rendered_html = render_markdown_to_rich_html(markdown_input, "cpp")
        self.assertIn("WHAT TO SAY", rendered_html)
        self.assertIn("CODE SOLUTION", rendered_html)
        self.assertIn("<pre", rendered_html)
        self.assertIn("vector", rendered_html)
        self.assertIn("text-shadow", rendered_html)


if __name__ == "__main__":
    unittest.main()
