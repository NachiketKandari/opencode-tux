#!/usr/bin/env python3
"""
fetch_data.py - Fetch batch data from JSONPlaceholder API

Downloads posts from JSONPlaceholder in paginated batches,
formats them as pipe-delimited lines for the Tuxedo batch
ingestion service.

Usage:
    python3 scripts/fetch_data.py                    # fetch all 100 posts
    python3 scripts/fetch_data.py --count 50         # fetch first 50
    python3 scripts/fetch_data.py -o data/input.dat  # output to file
"""

import argparse
import sys
import urllib.request
import json
import time

API_BASE = "https://jsonplaceholder.typicode.com"
POSTS_PER_PAGE = 20  # API default page size


def fetch_page(page: int, limit: int = POSTS_PER_PAGE) -> list:
    """Fetch one page of posts from JSONPlaceholder."""
    url = f"{API_BASE}/posts?_page={page}&_limit={limit}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  Error fetching page {page}: {e}", file=sys.stderr)
        return []


def fetch_all_posts(max_count: int = 100) -> list:
    """Fetch all posts in paginated batches."""
    all_posts = []
    page = 1

    print(f"Fetching up to {max_count} posts from JSONPlaceholder...", file=sys.stderr)

    while len(all_posts) < max_count:
        remaining = max_count - len(all_posts)
        limit = min(POSTS_PER_PAGE, remaining)

        print(f"  Page {page} (fetching {limit} posts)...", file=sys.stderr)

        posts = fetch_page(page, limit)
        if not posts:
            break

        all_posts.extend(posts)

        if len(posts) < limit:
            break  # No more data

        page += 1
        time.sleep(0.1)  # Be polite to the API

    print(f"  Fetched {len(all_posts)} posts total.", file=sys.stderr)
    return all_posts[:max_count]


def format_posts(posts: list) -> str:
    """Format posts as pipe-delimited lines for batch ingestion.

    Output format: user_id|id|title|body
    One line per record — easily parsed by strtok in C.
    """
    lines = []
    for post in posts:
        # Sanitize: remove newlines, pipes from title and body
        title = post['title'].replace('\n', ' ').replace('|', '/')
        body = post['body'].replace('\n', ' ').replace('|', '/')
        lines.append(f"{post['userId']}|{post['id']}|{title}|{body}")

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch batch data from JSONPlaceholder API"
    )
    parser.add_argument('--count', '-n', type=int, default=100,
                        help='Number of posts to fetch (default: 100)')
    parser.add_argument('--output', '-o', default='data/input.dat',
                        help='Output file path (default: data/input.dat)')
    args = parser.parse_args()

    posts = fetch_all_posts(args.count)
    if not posts:
        print("ERROR: No posts fetched.", file=sys.stderr)
        sys.exit(1)

    output = format_posts(posts)

    with open(args.output, 'w') as f:
        f.write(output)

    print(f"Wrote {len(posts)} records to {args.output}")
    print(f"File size: {len(output)} bytes")


if __name__ == '__main__':
    main()
