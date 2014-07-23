#!/usr/bin/python3

# This program uses forum_archive to download a story thread, and then a
# manually compiled list of story chapters to create a single story ebook file.

import forum_archive, html2text, urllib.request, markdown
import argparse, tempfile, os, subprocess, re, sys
from bs4 import BeautifulSoup

def get_redirect(url):
    """Takes a URL, sends a HEAD request, returns the URL of final redirection.
    Necessary for determining the canonical post URL from one of multiple
    possible forms. Imitates Firefox user agent string, in order to ensure
    access to sites.

    """
    ro = urllib.request.Request(url, method='HEAD', headers={"User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux i686; rv:21.0) Gecko/20100101 Firefox/21.0"})
    r = urllib.request.urlopen(ro)
    return r.geturl()

def download_story(chapters):
    """Takes a list of chapters, returns a list of strings with chapter text.
    chapters is a list of tuples (title, url), where url points to a chapter
    post directly.

    """
    cthread, rlist = [], []
    for i in chapters:
        while True:
            try:
                n = [j['post_url'] for j in cthread].index(i[1])
                rlist.append((i[0], cthread[n]['text']))
            except ValueError:
                print("Getting thread for URL {}".format(i[1]))
                g = forum_archive.make_getter(i[1])
                pn = g.get_url_page(i[1])
                cthread = g.get_thread(pn)
                continue
            break
    return rlist

def to_string(chapters):
    """Takes a list of chapters, stores it as a string; one per line, format <url>
    <title>.

    """
    rv = ""
    for i in chapters:
        rv = rv + "{} {}\n".format(i[1], i[0])
    return rv

def to_chapters(string):
    rv = []
    for i in string.splitlines():
        try:
            u, t = i.split(' ', 1)
        except:
            continue
        rv.append((t, u))
    return rv

def make_toc(contents):
    """Makes an HTML string table of contents to be concatenated into outstr, given the return value
    of get_contents (array of chapter names)."""
    rs = "<h2>Contents</h2>\n<ol>\n"
    for x in range(len(contents)):
        n = x + 1
        anc = "#ch{}".format(n)
        rs += "<li><a href=\"{}\">{}</a></li>\n".format(anc, contents[x])
    rs += "</ol>\n"
    return rs

def compile_story(title, chapters, urls, outfile, headers=True, contents=False):
    """Takes a list of chapter text strings from download_story, writes them to a
    nice HTML file. HTML is written to the stream passed as outfile.

    """
    outfile.write("""<html>
<head>
<meta charset="UTF-8">
<title>{}</title>
<style type="text/css">
body {{ font-family: sans-serif }}
</style>
</head>
<!--
""".format(title[0]))
    outfile.write("title: {}\n".format(title[0]))
    outfile.write("author: {}\n".format(title[1]))
    outfile.write("source: {}\n".format(title[2]))
    outfile.write("Chapters:\n")
    outfile.write(to_string(urls))
    outfile.write("-->\n<body>\n")
    if headers:
        outfile.write("<h1>{}</h1>\n".format(title[0]))
    if contents:
        outfile.write(make_toc([i[0] for i in chapters]))
    for n, t in enumerate(chapters):
        x = n + 1
        t2 = re.sub(r"(\s+)</([^>]+)>", r"</\2>\1", t[1])
        text = markdown.markdown(html2text.html2text(t2)) # Seems to be best available way to quickly get sane HTML
        if headers:
            outfile.write("""<h2 id="ch{}" class="chapter">{}</h2>\n""".format(x, t[0]))
        outfile.write(text + "\n\n")
    outfile.write("</body>\n</html>\n")


def make_listing(html):
    """Takes some HTML with links in it, returns a list of (title, url) tuples
    suitable to pass to compile_story. Designed for extracting from
    table-of-contents pages. Calls get_redirect on all URLs, for the purpose of
    normalizing them. (This may fail on non-XF fora. Fix it later.)

    """
    soup = BeautifulSoup(html)
    it = soup.find_all('a')
    l = len(it)
    for n, i in enumerate(it):
        print("{}/{}".format(n+1, l), end='\r')
        yield (i.string, get_redirect(i['href']))
    print("\n", end="")

def make_filename(title):
    title = title.lower().replace(" ", "_")
    return re.sub("[^a-z0-9_]", "", title)

def read_file(fn):
    with open(fn) as idata:
        title, source, chapters = None, None, ""
        cg = False
        for i in idata:
            if i.startswith('title: ') and not title:
                title = i[7:-1]
            if i.startswith('source: ') and not source:
                source = i[8:-1]
            if i.startswith("-->"):
                break
            if cg:
                chapters += i
            if i.startswith("Chapters:"):
                cg = True
    return title, source, chapters

def main():
    ap = argparse.ArgumentParser(description="Forum-based story downloader/compiler")
    ap.add_argument("-u", "--update", help="Update an existing story", action="store_true", default=False)
    ap.add_argument("url", help="Post URL to contents page")
    ap.add_argument("title", help="Story title in file", default=None, nargs='?')
    args = ap.parse_args()
    if args.update and args.title:
        print("Error: may not provide title when updating", file=sys.stderr)
        sys.exit(1)
    if not args.update and not args.title:
        print("Error: must provide title", file=sys.stderr)
        sys.exit(1)
    if args.update:
        args.title, args.url, cli = read_file(args.url)
    g = forum_archive.make_getter(args.url)
    fp = g.get_thread(g.get_url_page(args.url))
    cl = [i for i in fp if i['post_url'] == args.url][0]
    author = cl['poster_name']
    l = list(make_listing(cl['text']))

    ede = os.environ.get('EDITOR', 'vim')
    helpstr = """Above the marker is the table of contents from the original file; below is
that derived from the source. Edit the former as desired, then quit. Everything
below the marker will be ignored.
"""
    ifstr = to_string(l) if not args.update else cli + '-' * 20 + "\n" + helpstr + to_string(l)
    with tempfile.NamedTemporaryFile() as tf:
        tf.write(ifstr.encode())
        tf.flush()
        subprocess.call(ede.split() + [tf.name])
        tf.seek(0)
        ofstr = tf.read().decode()

    if args.update:
        ofstr = ofstr.split('-'*20)[0]
    l = to_chapters(ofstr)

    stext = download_story(l)
    fn = make_filename(args.title) + '.html'
    with open(fn, 'w') as of:
        compile_story((args.title, author, args.url), stext, l, of)

if __name__=="__main__":
    main()
