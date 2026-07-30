# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
import mistune

# Module imports
from plane.utils.content_validator import validate_html_content

# `escape=True` keeps raw HTML coming from external sources out of the output,
# the rendered markup is sanitized afterwards as a second layer of defense.
markdown = mistune.create_markdown(escape=True, plugins=["strikethrough", "table", "task_lists"])


def convert_markdown_to_html(content: str) -> str:
    """Render markdown into sanitized editor-compatible HTML.

    Headings, lists, tables and fenced code blocks are preserved so the content
    renders as rich text instead of raw markdown characters.
    """
    if not content or not content.strip():
        return "<p></p>"

    rendered_html = markdown(content)
    _, _, clean_html = validate_html_content(rendered_html)
    return clean_html or "<p></p>"
