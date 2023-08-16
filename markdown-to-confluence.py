#!/usr/bin/env python3
import argparse
import logging
import os
import git
import sys
import re

from getpass import getpass
from markdown_to_confluence.confluence import Confluence
from markdown_to_confluence.convert import convtoconf, parse

"""Synchronizes pages rendered in Markdown to Confluence

This script is meant to be executed as either part of a CI/CD job or on an
adhoc basis.
"""

logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)
log = logging.getLogger(__name__)

# Global vars to store failed and skipped pages
failedpages = []
skippedpages = []

# Potential for future supported formats
SUPPORTED_FORMATS = ['.md']


def get_environ_headers(prefix):
    """Returns a list of headers read from environment variables whose key
    starts with prefix.

    The header names are derived from the environment variable keys by
    stripping the prefix. The header values are set to the environment
    variable values.

    Arguments:
        prefix {str} -- The prefix of the environment variable keys which specify headers.
    """
    headers = []
    for key, value in os.environ.items():
        if key.startswith(prefix):
            header_name = key[len(prefix):]
            headers.append("{}:{}".format(header_name, value))
    return headers


def get_last_modified(repo):
    """Returns the paths to the last modified files in the provided Git repo
    
    Arguments:
        repo {git.Repo} -- The repository object
    """
    changed_files = repo.git.diff('HEAD~1..HEAD', name_only=True).split()
    for filepath in changed_files:
        if not filepath.startswith('content/'):
            changed_files.remove(filepath)
    return changed_files


def get_slug(filepath, prefix=''):
    """Returns the slug for a given filepath
    
    Arguments:
        filepath {str} -- The filepath for the post
        prefix {str} -- Any prefixes to the slug
    """
    slug, _ = os.path.splitext(os.path.basename(filepath))
    # Confluence doesn't support searching for labels with a "-",
    # so we need to adjust it.
    slug = slug.replace('-', '_')
    if prefix:
        slug = '{}_{}'.format(prefix, slug)
    return slug

def parse_args():
    # Parse command line arguments
    
    parser = argparse.ArgumentParser(
        description='Converts and deploys a single or directory of markdown page/s to Confluence')
    parser.add_argument(
        '--api_url',
        dest='api_url',
        default=os.getenv('CONFLUENCE_API_URL'),
        help=
        'REQUIRED: The URL to the Confluence API (e.g. https://wiki.example.com/rest/api/)'
    )
    parser.add_argument(
        '--space',
        dest='space',
        default=os.getenv('CONFLUENCE_SPACE'),
        help=
        'REQUIRED: The Confluence space where the page/s should reside (default: env(\'CONFLUENCE_SPACE\'))'
    )
    parser.add_argument(
        '--username',
        dest='username',
        default=os.getenv('CONFLUENCE_USERNAME'),
        help=
        'REQUIRED: The username for authentication to Confluence (default: env(\'CONFLUENCE_USERNAME\'))'
    )
    parser.add_argument(
        '--password',
        dest='password',
        default=os.getenv('CONFLUENCE_PASSWORD'),
        help=
        'The password for authentication to Confluence (default: env(\'CONFLUENCE_PASSWORD\'))'
    )
    parser.add_argument(
        '--dir',
        dest='dir',
        default='None',
        help='The path to your directory containing markdown pages (default: None)'
    )
    parser.add_argument(
        '--git',
        dest='git',
        default='None',
        help='The path to your Git repository containing markdown pages (default: None)'
    )
    parser.add_argument(
        '--global_label',
        dest='global_label',
        default=os.getenv('CONFLUENCE_GLOBAL_LABEL'),
        help=
        'The label to apply to every page for easier discovery in Confluence (default: env(\'CONFLUENCE_GLOBAL_LABEL\'))'
    )
    parser.add_argument(
        '--header',
        metavar='HEADER',
        dest='headers',
        action='append',
        default=get_environ_headers('CONFLUENCE_HEADER_'),
        help=
        'Extra header to include in the request when sending HTTP to a server. May be specified multiple times. (default: env(\'CONFLUENCE_HEADER_<NAME>\'))'
    )
    parser.add_argument(
        '--dry-run',
        dest='dry_run',
        action='store_true',
        help=
        'Print requests that would be sent - don\'t actually make requests against Confluence (note: we return empty responses, so this might impact accuracy)'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Can be used with --git flag. Upload pages without checking for changes'
    )
    parser.add_argument(
        '--no-minoredit',
        dest='minoredit',
        action='store_false',
        help='Don\'t use minorEdit flag when creating content and trigger notifications for all changes'
    )
    parser.add_argument(
        '--no-optimizeattachments',
        dest='optimizeattachments',
        action='store_false',
        help='Upload all attachments everytime'
    )
    parser.add_argument(
        '--save-cookie',
        dest='save_cookie',
        default=None,
        help='File system location to write cookie'
    )
    parser.add_argument(
        '--cookie-file',
        dest='cookie',
        default=None,
        help='Instead of using a user name and password use a cookie created with --save-cookie'
    )
    parser.add_argument(
        'posts',
        type=str,
        nargs='*',
        help=
        'Individual pages to deploy to Confluence'
    )
    
    args = parser.parse_args()

    if not args.api_url:
        log.error('Please provide a valid Confluence API_URL')
        parser.print_help(sys.stderr)
        sys.exit(1)
    if not args.space:
        log.error('Please provide a valid Confluence Space')
        parser.print_help(sys.stderr)
        sys.exit(1)
    if not (args.username or args.cookie):
        log.error('Please provide a valid user or cookie file')
        parser.print_help(sys.stderr)
        sys.exit(1)
    if len(sys.argv)==1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    return parser.parse_args()

class Page():
    def __init__(self, post_path, args, confluence):
        self.post_path = post_path
        self.ignore = True

        _, ext = os.path.splitext(post_path)
        if ext not in SUPPORTED_FORMATS:
            log.info('Skipping {} since it\'s not a supported format.'.format(
                post_path))
            return

        try:
            self.front_matter, markdown = parse(post_path)
        except Exception as e:
            log.error(
                'Unable to process {}. Normally not a problem, but here\'s the error we received: {}'
                .format(post_path, e))
            return

        
        if 'wiki' not in self.front_matter or not self.front_matter['wiki'].get('share'):
            log.info(
                'Page {} not set to be uploaded to Confluence'.format(post_path))
            return
        
        if self.front_matter.get('draft'):
            log.info(
                'Page {} has draft status set to true....ignoring'.format(post_path))
            return

        if self.front_matter['wiki'].get('title'):
            deploy_title=self.front_matter['wiki'].get('title')
            self.front_matter['title']=deploy_title

        if self.front_matter['wiki'].get('parent'):
            deploy_parent=self.front_matter['wiki'].get('parent')
            self.front_matter['parent']=deploy_parent

        self.front_matter['author_keys'] = []
        authors = self.front_matter.get('authors', [])
        for author in authors:
            confluence_author = confluence.get_author(author)
            if not confluence_author:
                continue
            self.front_matter['author_keys'].append(confluence_author['userKey'])

        ext = post_path.split('.')[-1]

     
        # Normalize the content into whatever format Confluence expects
        self.html, self.attachments = convtoconf(markdown, front_matter=self.front_matter)

        static_path = os.path.join(args.dir, 'static')
        for i, attachment in enumerate(self.attachments):
            self.attachments[i] = os.path.join(static_path, attachment.lstrip('/'))

        self.post_slug = get_slug(post_path)

        self.space = self.front_matter.get('space', args.space)

        self.tags = self.front_matter.get('tags', [])
        
        # Confluence does not support spaces in labels. Replace these with dashes
        for i in range(len(self.tags)):
            altag = re.sub(r'[^A-Za-z0-9 -]+', '', self.tags[i])
            ftag = altag.replace(" ","-")
            self.tags[i] = ftag
        
        if args.global_label:
            self.tags.append(args.global_label)
        self.ignore = False
        self.children = []

    def deploy(self, args, confluence, parent_id):        
        if 'parent' in self.front_matter and not parent_id:
            parent_title = self.front_matter['parent']
            parent = confluence.exists(title=parent_title, space=self.space)
            if not parent:
                log.error(f'Cannot find parent page "{parent_title}". Skipping {self.post_path}.')
                self.id = None
                return
            parent_id = parent['id']
        
        page = confluence.exists(title=self.front_matter['title'], ancestor_id=parent_id, space=self.space)
        result=""
        if page:
            self.id = page['id']
            # FIXME: confluence sometimes changes the file so unchanged file will not match
            if not args.force and confluence.get_page_content(page['id']) == self.html.strip():
                log.info(f'Skipping {self.post_path} since there are no changes')
            else:
                result = confluence.update(page['id'],
                                content=self.html,
                                title=self.front_matter['title'],
                                tags=self.tags,
                                slug=self.post_slug,
                                space=self.space,
                                ancestor_id=parent_id,
                                page=page,
                                attachments=self.attachments)
                if result.endswith("fail"):
                    failedpages.append(self.post_path)
        else:
                result = self.id = confluence.create(content=self.html,
                            title=self.front_matter['title'],
                            tags=self.tags,
                            slug=self.post_slug,
                            space=self.space,
                            ancestor_id=parent_id,
                            attachments=self.attachments)
                if result.endswith("fail"):
                    failedpages.append(self.post_path)
        

def main():
    args = parse_args()

    if args.password is None and args.cookie is None:
        args.password = getpass()

    confluence = Confluence(api_url=args.api_url,
                            username=args.username,
                            password=args.password,
                            cookie=args.cookie,
                            headers=args.headers,
                            dry_run=args.dry_run,
                            optimizeattachments=args.optimizeattachments,
                            minoredit=args.minoredit)

    if args.save_cookie:
        log.info('Attempting to save cookie.  Input files will be ignored')
        if confluence.save_cookie(args.save_cookie):
            log.info(f'Cookie saved successfully to {args.save_cookie}')
        else:
            log.error(f'Failed to save cookie {args.save_cookie}')
        return

    if args.posts:
        changed_posts = [os.path.abspath(post) for post in args.posts]
        for post_path in changed_posts:
            if not os.path.exists(post_path) or not os.path.isfile(post_path):
                log.error('File doesn\'t exist: {}'.format(post_path))
                sys.exit(1)
 
    elif args.git != 'None':
          repo = git.Repo(args.git)
          log.info('Checking content pages modified in the last Git commit')
          changed_posts = [
              os.path.join(args.git, post) for post in get_last_modified(repo)
          ]
          if not changed_posts:
            log.info('No pages created/modified in the latest Git commit')
            return

    elif args.dir != 'None':
          log.info(f'Checking content pages in directory {args.dir}')
          changed_posts = [
              os.path.join(path, name) for path, subdirs, files in os.walk(args.dir) for name in files
          ]
          for filepath in changed_posts[:]:
            if not filepath.startswith(f'{args.dir}/content/'):
                changed_posts.remove(f'{filepath}')

    else:
        log.info('No pages found in input source')
        return

    pages = [ p for p in (Page(post, args, confluence) for post in changed_posts) if not p.ignore ]

    page_map = dict((p.front_matter['title'], p) for p in pages)

    seen = set()
    root_pages = []

    for p in pages:
        parent = p.front_matter['wiki'].get('parent', None)
        if parent and parent in page_map:
            page_map[parent].children.append(p)
        else:
            root_pages.append(p)
    
    def deploy_pages(pages, offset = 0, parent_id = None):
        for p in pages:
            if p.front_matter['title'] not in seen:
                seen.add(p.front_matter['title'])
                log.info('-' * offset + '> Attempting to deploy ' + p.front_matter['title'])
                p.deploy(args, confluence, parent_id)
                deploy_pages(p.children, offset + 4, p.id)
            else:
                log.info('ERROR ---- ' + 'Duplicate Confluence page ' + '"' + p.front_matter['title'] +'"' + ' already exists. Skipping.....')
                skippedpages.append('"' + p.front_matter['title'] + '"' + ' at ' + p.post_path)

    deploy_pages(root_pages)

    if len(failedpages) > 0:
        log.info('---------- Failure Summary -----------')
        log.info(f'{len(failedpages)} pages failed to deploy. Please check the pages listed below for invalid content:\n')
        for f in failedpages:
            log.info(f)
        log.info('--------------------------------------')
            
    if len(skippedpages) > 0:
        log.info('---------- Skipped Summary -----------')
        log.info(f'{len(skippedpages)} pages were skipped due to duplicate page titles. Please check the pages listed below for duplicate titles:\n')
        for s in skippedpages:
            log.info(s)
        log.info('--------------------------------------')

if __name__ == '__main__':
    main()
