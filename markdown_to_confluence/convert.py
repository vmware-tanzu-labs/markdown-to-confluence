import mistune
import os
import textwrap
import yaml

from urllib.parse import urlparse

YAML_BOUNDARY = '---'


def parse(post_path):
    """Parses the metadata and content from the provided post.

    Arguments:
        post_path {str} -- The absolute path to the Markdown post
    """
    raw_yaml = ''
    markdown = ''
    in_yaml = True
    with open(post_path, 'r') as post:
        for line in post.readlines():
            # Check if this is the ending tag
            if line.strip() == YAML_BOUNDARY:
                if in_yaml and raw_yaml:
                    in_yaml = False
                    continue
            if in_yaml:
                raw_yaml += line
            else:
                markdown += line
    front_matter = yaml.load(raw_yaml, Loader=yaml.SafeLoader)
    markdown = markdown.strip()
    return front_matter, markdown


def convtoconf(markdown, front_matter={}):
    if front_matter is None:
        front_matter = {}

    author_keys = front_matter.get('author_keys', [])
    renderer = ConfluenceRenderer(authors=author_keys)
    content_html = mistune.markdown(markdown, renderer=renderer)
    page_html = renderer.layout(content_html)

    return page_html, renderer.attachments


class ConfluenceRenderer(mistune.Renderer):
    def __init__(self, authors=[]):
        self.attachments = []
        if authors is None:
            authors = []
        self.authors = authors
        self.has_toc = False
        super().__init__()

    def layout(self, content):
        """Renders the final layout of the content. This includes a two-column
        layout, with the ToC on the left, spacer column in the middle and the content on the
        right.

        The layout looks like this:

        -------------------------------------------
        |             |  |                        |
        |             |  |                        |
        | Sidebar     |  |       Content          |
        | (25% width) |  |    (73% width)         |
        |             |  |                        |
        -------------------------------------------

        Arguments:
            content {str} -- The HTML of the content
        """
        toc = textwrap.dedent('''
            <h1>Table of Contents</h1>
            <p><ac:structured-macro ac:name="toc" ac:schema-version="1">
                <ac:parameter ac:name="exclude">^(Authors|Table of Contents)$</ac:parameter>
            </ac:structured-macro></p>''')
        
        if self.has_toc:
            spacer = ''
            #authors = self.render_authors()
            column = textwrap.dedent('''
                <ac:structured-macro ac:name="column" ac:schema-version="1">
                    <ac:parameter ac:name="width">{width}</ac:parameter>
                    <ac:rich-text-body>{content}</ac:rich-text-body>
                </ac:structured-macro>''')
            sidebar = column.format(width='25%', content=toc)
            spacer = column.format(width='2%', content=spacer)
            main_content = column.format(width='73%', content=content)
            return sidebar + spacer + main_content
        
        # Ignore the TOC if none in source for better formatting
        if not self.has_toc:
            #authors = self.render_authors()
            column = textwrap.dedent('''
                <ac:structured-macro ac:name="column" ac:schema-version="1">
                    <ac:parameter ac:name="width">{width}</ac:parameter>
                    <ac:rich-text-body>{content}</ac:rich-text-body>
                </ac:structured-macro>''')
            main_content = column.format(width='100%', content=content)
            return main_content

    def header(self, text, level, raw=None):
        """Processes a Markdown header.

        In our case, this just tells us that we need to render a TOC. We don't
        actually do any special rendering for headers.
        """
        self.has_toc = True
        return super().header(text, level, raw)

    def render_authors(self):
        """Renders a header that details which author(s) published the post.

        This is used since Confluence will show the post published as our
        service account.
        
        Arguments:
            author_keys {str} -- The Confluence user keys for each post author
        
        Returns:
            str -- The HTML to prepend to the post specifying the authors
        """
        author_template = '''<ac:structured-macro ac:name="profile-picture" ac:schema-version="1">
                <ac:parameter ac:name="User"><ri:user ri:userkey="{user_key}" /></ac:parameter>
            </ac:structured-macro>&nbsp;
            <ac:link><ri:user ri:userkey="{user_key}" /></ac:link>'''
        author_content = '<br />'.join(
            author_template.format(user_key=user_key)
            for user_key in self.authors)
        return '<h1>Authors</h1><p>{}</p>'.format(author_content)

    def block_code(self, code, lang):
            """Formats a code block into a Confluence code block macro.

            Confluence code block macro uses bash as language
            rather than sh so this is explicity set.

            """
            if lang == "sh":
                lang = "bash"
            return textwrap.dedent('''\
                <ac:structured-macro ac:name="code" ac:schema-version="1">
                    <ac:parameter ac:name="language">{l}</ac:parameter>
                    <ac:parameter ac:name="theme">Midnight</ac:parameter>
                    <ac:plain-text-body><![CDATA[{c}]]></ac:plain-text-body>
                </ac:structured-macro>
            ''').format(c=code, l=lang or '')

    def image(self, src, title, alt_text):
        """Renders an image into XHTML expected by Confluence.

        Arguments:
            src {str} -- The path to the image
            title {str} -- The title attribute for the image
            alt_text {str} -- The alt text for the image

        Returns:
            str -- The constructed XHTML tag
        """
        # Check if the image is externally hosted, or hosted as a static
        # file within Journal
        is_external = bool(urlparse(src).netloc)
        tag_template = '<ac:image>{image_tag}</ac:image>'
        image_tag = '<ri:url ri:value="{}" />'.format(src)
        if not is_external:
            image_tag = '<ri:attachment ri:filename="{}" />'.format(
                os.path.basename(src))
            self.attachments.append(src)
        return tag_template.format(image_tag=image_tag)
