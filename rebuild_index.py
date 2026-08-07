import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publisher import get_existing_posts, update_index_page

if __name__ == "__main__":
    posts = [p for p in get_existing_posts() if p['file'] != "index.html"]
    if posts:
        latest = posts[0]
        update_index_page(latest['title'], latest['file'], latest['image'])
    else:
        print("No posts available to seed index.html.")
