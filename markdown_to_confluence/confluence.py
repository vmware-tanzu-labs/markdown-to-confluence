import logging
import requests
import hashlib
import os
import pickle
import sys

from urllib.parse import urljoin

API_HEADERS = {
    'User-Agent': 'markdown-to-confluence',
}

MULTIPART_HEADERS = {
    'X-Atlassian-Token': 'nocheck'  # Only need this for form uploads
}

DEFAULT_LABEL_PREFIX = 'global'

log = logging.getLogger(__name__)


class MissingArgumentException(Exception):
    def __init__(self, arg):
        self.message = 'Missing required argument: {}'.format(arg)


class Confluence():
    def __init__(self,
                 api_url=None,
                 username=None,
                 password=None,
                 cookie=None,
                 headers=None,
                 dry_run=False,
                 minoredit=True,
                 optimizeattachments=True,
                 _client=None):
        """Creates a new Confluence API client.
        
        Arguments:
            api_url {str} -- The URL to the Confluence API root (e.g. https://wiki.example.com/api/rest/)
            username {str} -- The Confluence service account username
            password {str} -- The Confluence service account password
            headers {list(str)} -- The HTTP headers which will be set for all requests
            dry_run {str} -- The Confluence service account password
            minoredit {bool} -- Flag for minorEdit in Confluence
        """
        # A common gotcha will be given a URL that doesn't end with a /, so we
        # can account for this
        if not api_url.endswith('/'):
            api_url = api_url + '/'
        self.api_url = api_url

        self.username = username
        self.password = password
        self.dry_run = dry_run
        self.minoredit = minoredit
        self.optimizeattachments = optimizeattachments

        if _client is None:
            _client = requests.Session()

        self._session = _client
        if cookie:
            log.info(f'Using existing cookie from {cookie}')
            with open(cookie, 'rb') as f:
                self._session.cookies.update(pickle.load(f))
        else:
            log.info('No cookie provided.  User username and password')
            self._session.auth = (self.username, self.password)
        
        for header in headers or []:
            try:
                name, value = header.split(':', 1)
            except ValueError:
                name, value = header, ''
            self._session.headers[name] = value.lstrip()

    def _require_kwargs(self, kwargs):
        """Ensures that certain kwargs have been provided
        
        Arguments:
            kwargs {dict} -- The dict of required kwargs
        """
        missing = []
        for k, v in kwargs.items():
            if not v:
                missing.append(k)
        if missing:
            raise MissingArgumentException(missing)

    def _request(self,
                 method='GET',
                 path='',
                 params=None,
                 files=None,
                 data=None,
                 headers=None):
        url = urljoin(self.api_url, path)

        if not headers:
            headers = {}
        headers.update(API_HEADERS)

        if files:
            headers.update(MULTIPART_HEADERS)

        if data:
            headers.update({'Content-Type': 'application/json'})

        if self.dry_run:
            log.info('''{method} {url}:
            Params: {params}
            Data: {data}
            Files: {files}'''.format(method=method,
                                     url=url,
                                     params=params,
                                     data=data,
                                     files=files))
            if method != 'GET':
                return {}

        response = self._session.request(method=method,
                                         url=url,
                                         params=params,
                                         json=data,
                                         headers=headers,
                                         files=files)

        if not response.ok:
            log.info('''{method} {url}: {status_code} {reason}
            Params: {params}
            Data: {data}
            Files: {files}'''.format(method=method,
                                     url=url,
                                     status_code=response.status_code,
                                     reason=response.reason,
                                     params=params,
                                     data=data,
                                     files=files))
            if response.status_code == 403 or response.status_code == 401:
                log.info('Authorization failed. Please check your credentials.')
                sys.exit(1)
            return response.content

        # Will probably want to be more robust here, but this should work for now
        return response.json()

    def get(self, path=None, params=None):
        return self._request(method='GET', path=path, params=params)

    def post(self, path=None, params=None, data=None, files=None):
        return self._request(method='POST',
                             path=path,
                             params=params,
                             data=data,
                             files=files)

    def put(self, path=None, params=None, data=None):
        return self._request(method='PUT', path=path, params=params, data=data)

    def exists(self, space=None, title=None, ancestor_id=None):
        """Returns the Confluence page that matches the provided metdata, if it exists.

        Specifically, this leverages a Confluence Query Language (CQL) query
        against the Confluence API. We assume that each slug is unique, at
        least to the provided space/ancestor_id.
        
        Arguments:
            space {str} -- The Confluence space to use for filtering posts
            slug {str} -- The page slug
            ancestor_id {str} -- The ID of the parent page
        """
        self._require_kwargs({'title': title})

        cql_args = []
        if title:
            cql_args.append(f'title="{title}"')
        if ancestor_id:
            cql_args.append('ancestor={}'.format(ancestor_id))
        if space:
            cql_args.append('space={!r}'.format(space))

        cql = ' and '.join(cql_args)

        params = {'expand': 'version', 'cql': cql}
        response = self.get(path='content/search', params=params)
        if not response.get('size'):
            return None
        ret = [ r for r in response['results'] if r['type'] == 'page' and r['title'] == title ]
        assert(len(ret) == 1)
        return ret[0]
        
    def ping(self):
        """
            Basic request to get a cookie
        """
        response = self.get(path=f'content', params={ 'type': 'page', 'limit': 1 })
        return response.get('size')

    def save_cookie(self, dest):
        if self.ping():
            with open(dest, 'wb') as f:
                pickle.dump(self._session.cookies, f)
            return True
        return False
    
    def get_page_content(self, id):
        """Returns the content of the Confluence page that matches the provided metdata, if it exists.

        Arguments:
            id {str} -- The ID of the page
        """
        response = self.get(path=f'content/{id}', params={ 'expand': 'body.storage' })
        return response.get('body')['storage']['value']

    def create_labels(self, page_id=None, tags=[]):
        """Creates labels for the page to both assist with searching as well
        as categorization.

        We specifically require a slug to be provided, since this is how we
        determine if a page exists. Any other tags are optional.
        
        Keyword Arguments:
            page_id {str} -- The ID of the existing page to which the label should apply
            slug {str} -- The page slug to use as the label value
            tags {list(str)} -- Any other tags to apply to the post
        """
        
        labels = []

        if tags is None:
            tags = []
        for tag in tags:
            labels.append({'prefix': DEFAULT_LABEL_PREFIX, 'name': tag})
        path = 'content/{page_id}/label'.format(page_id=page_id)
        response = self.post(path=path, data=labels)

        # Do a sanity check to ensure that the label for the slug appears in
        # the results, since that's needed for us to find the page later.
        labels = response.get('results', [])
        if not labels:
            log.error(
                'No labels found after attempting to update page {}'.format(
                    page_id))
            log.error('Here\'s the response we got:\n{}'.format(response))
            return labels

        log.info(
            'Created the following labels for page {page_id}: {labels}'.format(
                page_id=page_id,
                labels=', '.join(label['name'] for label in labels)))
        return labels

    def _create_page_payload(self,
                             content=None,
                             title=None,
                             ancestor_id=None,
                             attachments=None,
                             space=None,
                             type='page'):
        ret = {
            'type': type,
            'title': title,
            'space': {
                'key': space
            },
            'body': {
                'storage': {
                    'representation': 'storage',
                    'value': content
                }
            }
        }
        if ancestor_id:
            ret['ancestors'] = [{
                'id': str(ancestor_id)
            }]
        return ret

    def get_attachments(self, post_id):
        """Gets the attachments for a particular Confluence post
        
        Arguments:
            post_id {str} -- The Confluence post ID
        """
        response = self.get("/content/{}/attachments".format(post_id))
        return response.get('results', [])

    def upload_attachment(self, post_id=None, attachment_path=None):
        """Uploads an attachment to a Confluence post
        
        Keyword Arguments:
            post_id {str} -- The Confluence post ID
            attachment_path {str} -- The absolute path to the attachment
        """
        path = 'content/{}/child/attachment'.format(post_id)
        if not os.path.exists(attachment_path):
            log.error('Attachment {} does not exist'.format(attachment_path))
            return
        log.info(
            'Uploading attachment {attachment_path} to post {post_id}'.format(
                attachment_path=attachment_path, post_id=post_id))
        shahash = None
        if self.optimizeattachments:
            response = self.get(path="content/{}/child/attachment".format(post_id),
                        params= {'filename': os.path.basename(attachment_path),
                                'expand': 'version'})
            shahash = hashlib.sha256(open(attachment_path, 'rb').read()).hexdigest()
            try:
                if len(response['results']) == 1 and \
                shahash == response['results'][0]['version']['message']:
                    log.info('Not Uploaded {} to post ID {} - no changes in file'.format(attachment_path, post_id))
                    return
            except KeyError:
                pass
        if not self.dry_run:
            self.post(path=path,
                    params={'allowDuplicated': 'true'},
                    files={'comment': shahash, 'minorEdit': self.minoredit, 'file': open(attachment_path, 'rb')})
        log.info('Uploaded {} to post ID {}'.format(attachment_path, post_id))

    def get_author(self, username):
        """Returns the Confluence author profile for the provided username,
        if it exists.

        Arguments:
            username {str} -- The Confluence username
        """
        log.info('Looking up Confluence user key for {}'.format(username))
        response = self.get(path='user', params={'username': username})
        if not isinstance(response, dict) or not response.get('userKey'):
            log.error('No Confluence user key for {}'.format(username))
            return {}
        return response

    def create(self,
               content=None,
               space=None,
               title=None,
               ancestor_id=None,
               slug=None,
               tags=None,
               attachments=None,
               type='page'):
        """Creates a new page with the provided content.

        If an ancestor_id is specified, then the page will be created as a
        child of that ancestor page.
        
        Keyword Arguments:
            content {str} -- The HTML content to upload (required)
            space {str} -- The Confluence space where the page should reside
            title {str} -- The page title
            ancestor_id {str} -- The ID of the parent Confluence page
            slug {str} -- The unique slug for the page
            tags {list(str)} -- The list of tags for the page
            attachments {list(str)} -- List of absolute paths to attachments
                which should uploaded.
        """
        self._require_kwargs({
            'content': content,
            'slug': slug,
            'title': title,
            'space': space
        })

        page = self._create_page_payload(content='Created by markdown-to-confluence - <a href="https://github.com/vmware-tanzu-labs/markdown-to-confluence">https://github.com/vmware-tanzu-labs/markdown-to-confluence</a>',
                                         title=title,
                                         ancestor_id=ancestor_id,
                                         space=space,
                                         type=type)
        response = self.post(path='content/', data=page)

        page_id = response['id']
        page_url = urljoin(self.api_url, response['_links']['webui'])

        log.info('Page "{title}" (id {page_id}) created successfully at {url}'.
                 format(title=title, page_id=response.get('id'), url=page_url))

        # Now that we have the page created, we can just treat the rest of the
        # flow like an update.
        return self.update(post_id=page_id,
                           content=content,
                           space=space,
                           title=title,
                           ancestor_id=ancestor_id,
                           slug=slug,
                           tags=tags,
                           page=response,
                           attachments=attachments)

    def update(self,
               post_id=None,
               content=None,
               space=None,
               title=None,
               ancestor_id=None,
               slug=None,
               tags=None,
               attachments=None,
               page=None,
               type='page'):
        """Updates an existing page with new content.

        This involves updating the attachments stored on Confluence, uploading
        the page content, and finally updating the labels.
        
        Keyword Arguments:
            post_id {str} -- The ID of the Confluence post
            content {str} -- The page represented in Confluence storage format
            space {str} -- The Confluence space where the page should reside
            title {str} -- The page title
            ancestor_id {str} -- The ID of the parent Confluence page
            slug {str} -- The unique slug for the page
            tags {list(str)} -- The list of tags for the page
            attachments {list(str)} -- The list of absolute file paths to any
                attachments which should be uploaded
        """
        self._require_kwargs({
            'content': content,
            'slug': slug,
            'title': title,
            'post_id': post_id,
            'space': space
        })
        # Since the page already has an ID in Confluence, before updating our
        # content which references certain attachments, we should make sure
        # those attachments have been uploaded.
        if attachments is None:
            attachments = []

        for attachment in attachments:
            self.upload_attachment(post_id=post_id, attachment_path=attachment)

        # Next, we can create the updated page structure
        new_page = self._create_page_payload(content=content,
                                             title=title,
                                             ancestor_id=ancestor_id,
                                             space=space,
                                             type=type)
        # Increment the version number, as required by the Confluence API
        # https://docs.atlassian.com/ConfluenceServer/rest/7.1.0/#api/content-update
        new_version = page['version']['number'] + 1
        new_page['version'] = {'minorEdit': self.minoredit, 'number': new_version}

        # With the attachments uploaded, and our new page structure created,
        # we can upload the final content up to Confluence.
        path = 'content/{}'.format(page['id'])
        response = self.put(path=path, data=new_page)
        failure = False

        # Dry-run option doesn't create any pages hence no urls,
        # we set it to a fixed value
       
        if self.dry_run:
            page_url = '(dry run)'
        
        # Test if there was a page creation error, if so set
        # failure var to True

        else: 
            try:
                test = response['_links']['webui']
            except(TypeError):
                failure = True
            else:
                page_url = urljoin(self.api_url, response['_links']['webui'])

        # Check for page creation failure and pass it back in the post_id var for tracking
        
        if failure:
            log.error('ERROR ---- Page "{title}" (id {page_id}) failed to update'.format(title=title, page_id=post_id))
            post_id = post_id + " - fail"
        else:
            if tags:
                # Finally, we can update the labels on the page
                self.create_labels(page_id=post_id, tags=tags)

            log.info('Page "{title}" (id {page_id}) updated successfully at {url}'.
            format(title=title, page_id=post_id, url=page_url))

        return post_id
