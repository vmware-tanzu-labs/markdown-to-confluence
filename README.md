# markdown-to-confluence

Converts and deploys a single or multiple Markdown files to Confluence.

This project was created to synchronize pages rendered in Markdown to Confluence either manually or as part of a CI process. It can also be used to selectively replicate Hugo static site content to Confluence while maintaining its inherent content hierarchy.

# Requirements

* Python 3
* An available Confluence instance
* A single or set of markdown files to synchronize.

# Installation

To install the project, you need to first install the dependencies:

```sh
pip install -r requirements.txt
```

Alternatively, you can use the provided Docker-file to build a runnable container:

```sh
docker build -t markdown-to-confluence:v1.0 .
```

This container can then be executed by substituting the mount location of the content directory and executing:

```
docker run -it -v ~/hugo-site:/site markdown-to-confluence:v1.0 --api_url "CONFLUENCE_URL" --space "CONFLUENCE_SPACE" --user "CONFLUENCE_USER" --dir /site
```

# Usage

```
usage: markdown-to-confluence.py [-h] [--api_url API_URL] [--space SPACE]
                                 [--username USERNAME] [--password PASSWORD]
                                 [--dir DIR] [--git GIT]
                                 [--global_label GLOBAL_LABEL]
                                 [--header HEADER] [--dry-run] [--force]
                                 [--no-minoredit] [--no-optimizeattachments]
                                 [--save-cookie SAVE_COOKIE]
                                 [--cookie-file COOKIE]
                                 [posts [posts ...]]

Converts and deploys a single or directory of markdown page/s to Confluence

positional arguments:
  posts                 Individual pages to deploy to Confluence

optional arguments:
  -h, --help            show this help message and exit
  --api_url API_URL     REQUIRED: The URL to the Confluence API (e.g. https://wiki.example.com/rest/api/)
  --space SPACE         REQUIRED: The Confluence space where the page/s should reside (default: env('CONFLUENCE_SPACE'))
  --username USERNAME   REQUIRED: The username for authentication to Confluence (default: env('CONFLUENCE_USERNAME'))
  --password PASSWORD   The password for authentication to Confluence (default: env('CONFLUENCE_PASSWORD'))
  --dir DIR             The path to your directory containing markdown pages (default: None)
  --git GIT             The path to your Git repository containing markdown pages (default: None)
  --global_label GLOBAL_LABEL
                        The label to apply to every page for easier discovery in Confluence (default: env('CONFLUENCE_GLOBAL_LABEL'))
  --header HEADER       Extra header to include in the request when sending HTTP to a server. May be specified multiple times. (default: env('CONFLUENCE_HEADER_<NAME>'))
  --dry-run             Print requests that would be sent - don't actually make requests against Confluence (note: we return empty responses, so this might impact accuracy)
  --force               Can be used with --git flag. Upload pages without checking for changes
  --no-minoredit        Don't use minorEdit flag when creating content and trigger notifications for all changes
  --no-optimizeattachments
                        Upload all attachments everytime
  --save-cookie SAVE_COOKIE
                        File system location to write cookie
  --cookie-file COOKIE  Instead of using a user name and password use a cookie created with --save-cookie
```

## What Posts are Deployed?

This project assumes that the Markdown files being processed have YAML formatted front-matter at the top. In order for a file to be processed, we expect the following front-matter to be present:

```yaml
wiki:
    share: true
```

## Maintaining the Content Hierarchy

By default the markdown files will be synchronized to the root of the specified Confluence Space. In the case of synchronizing an entire Hugo site you will want to maintain the content hierarchy of that site. This can be done by specifying the parent of the page in the set of front-matter as follows:

```yaml
wiki:
    share: true
    parent: "Name of parent page"
```

In most cases the parent page will be a `_index.md` file and will also require the `share` front-matter to be added to its file. Parent pages will be processed and created first in order to make sure that the parent-child hierarchy can be maintained. If no parent page with the specified name exists or has front-matter added, the child page will be skipped.

## Confluence Limitations

Confluence has some limitations in terms of content that can be created via the API.

### Duplicate page names

Confluence does not allow the creation of multiple pages with the same title in the same space even if they have a different parent https://jira.atlassian.com/browse/CONFSERVER-2524. To work around this limitation a new title can be specified without modifying the original front matter. This can be done by specifying a unique title in the set of front-matter as follows:

```yaml
wiki:
    share: true
    title: "New name of page" 
```

markdown-to-confluence will attempt to use the title specified in the standard front-matter as the page title unless a new title is specified as per above. If a page with the title already exists it will be skipped and shown in a summary after execution.

A standard recommendation is to number the content as per its hierarchy to ensure unique page names. An example of this is:

```
1. Product A
  1.1 Intro/Overview
  1.2 Pricelist
    1.2.1 License Info
  1.3 How to use

2. Product B
  2.1 Intro/Overview
  2.2 Pricelist
    2.2.1 License Info
  2.3 How to use
```

Alternatively you could also prefix the title with the name of the parent but this could potentially start to create large unruly title names.

### Special characters

The Confluence API can not handle some special characters when sending pages in a POST request. This includes some standard markdown formatting such as horizontal rule "---" and emojis such as :joy:. If page creation fails based on the source page content an error will be shown including the request made to the Confluence API server. A summary of all failed pages will be shown post execution.

## Deploying a Page

There are three ways to synchronize a page or set of pages to Confluence:

### Deploying Single Pages On-Demand

You may wish to synchronize a single page on-demand, rather than building this process into your CI/CD pipeline. To do this, just put the filenames of the page/s you wish to deploy to Confluence as arguments:

```
python3 markdown-to-confluence.py --api_url "CONFLUENCE_URL" --space "CONFLUENCE_SPACE" --user "CONFLUENCE_USER" /path/to/your/post.md
```

### Deploying a Directory of Pages On-Demand

To aid in synchronizing an entire Hugo site on-demand you can synchronize all pages contained within a directory. To do this, just provide the `--dir` flag with the path to the base content directory you wish to deploy to Confluence:

```
python3 markdown-to-confluence.py --api_url "CONFLUENCE_URL" --space "CONFLUENCE_SPACE" --user "CONFLUENCE_USER" --dir /site/content
```

### Syncing from a Git Repository

This project was originally created to keep an instance of Hugo in sync with a Confluence instance. To that end, this project is able to be run as part of a CI/CD pipeline, taking the Markdown files modified in the latest Git commit and syncing them to the upstream Confluence instance.

To enable this as part of your CI/CD pipeline, run `markdown-to-confluence`, providing the `--git` flag:

```
python3 markdown-to-confluence.py --api_url "CONFLUENCE_URL" --space "CONFLUENCE_SPACE" --user "CONFLUENCE_USER" --git /path/to/your/repo
```
