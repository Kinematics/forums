#!/usr/bin/python3

# This program is designed to scrape forum threads off the Web and return their
# contents in a minimal common format. The ideal is to be able to write a plugin
# for any forum and access it using the same API. A thread is returned as a list
# of posts; a post is a dictionary providing HTML text, name of poster, date,
# and other metadata as appropriate.

import re, urllib.request, urllib.error, urllib.parse, sys, datetime, http.client
from bs4 import BeautifulSoup
import bs4
import dateutil.parser, datetime, math, time
import traceback
import json, gzip

def urlopen_retry(url, tries=3, delay=1):
    """Open a URL, with retries on failure. Spoofs user agent to look like Firefox,
    due to various sites attempting to prohibit automatic downloading."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux i686; rv:21.0) Gecko/20100101 Firefox/21.0"})
    for i in range(tries):
        try:
            r = urllib.request.urlopen(req)
        except urllib.error.URLError as e:
            if i == tries - 1:
                raise e
            time.sleep(delay)
        else:
            return r

class ThreadGetter:
    """This is an abstract class that should be subclassed for each individual
    forum implemented."""
    def __init__(self, url):
        self.url = url
    def get_thread(self, pages=None):
        """This method will download the thread (of the appropriate forum) which was
        passed to the object's constructor. URLs are not checked for
        correctness; unpredictable errors will occur on one which is not as
        expected. The parameter 'pages' controls which pages of the thread are
        downloaded; as a single number, it will download only that page, while
        as a tuple (x,y) it will download pages from x to y, inclusive. Pages
        are indexed from 1.

        """
        r = urlopen_retry(self.url)
        html = r.read()
        soup = BeautifulSoup(html)
        npages = self.get_npages(soup)
        print("{} pages".format(npages))
        thread = []
        if pages is None:
            it = range(1, npages+1)
        else:
            try:
                x, y = pages
                if x < 1: x = 1
                if y > npages: y = npages
                it = range(x, y+1)
            except TypeError:
                x = pages
                if x < 1 or x > npages: 
                    raise ValueError("Single value out of thread bounds")
                it = range(x, x+1)
        for i in it:
            purl = self.make_page_url(i)
            r = urlopen_retry(purl)
            html = r.read()
            soup = BeautifulSoup(html)
            thread = thread + self.get_posts(soup, purl)
            sys.stdout.write("Got page {} of {}\r".format(i, npages))
        sys.stdout.write('\n')
        return thread
    def get_posts(self, soup, url):
        """This method takes a BeautifulSoup of a forum page and extracts the
        list of posts from it, retaining the various data."""
        pass
    def get_title(self, soup):
        """This method takes a BeautifulSoup of a forum page and parses it for
        the title of the thread."""
        pass
    def get_curl(self, soup):
        """This method takes a BeautifulSoup of a forum page and parses it for
        the thread's canonical URL (i.e. the best available URL pointing to the
        thread's first page)."""
        pass
    def get_npages(self, soup):
        """This method takes a BeautifulSoup of a forum page, and parses it for
        the number of pages the thread takes up."""
        pass
    def make_page_url(self, page):
        """This method takes a page number, and constructs a page URL based on
        the original to fetch that page number."""
        pass
    def process_html(self, text):
        """This method takes the HTML text of a forum post and reconstructs it
        to rid it of dependency on a site's CSS and javascript, allowing easy
        static rendering."""
        return text
    def get_url_page(self, url):
        """This method takes a URL pointing to a thread page and returns the number of
        the page."""
        
class FFNGetter(ThreadGetter):
    fid = tid = None
    def get_posts(self, soup, url):
        rv = []
        for i in soup.find("table", id="gui_table2i").tbody("td"):
            poster_name = str(i.a.string)
            poster_url = "http://www.fanfiction.net" + i.a['href']
            post_url = url + "#{}".format(i.a['id'])
            text = ""
            for p in i.a.next_siblings:
                if isinstance(p, bs4.element.NavigableString):
                    if p != " ":
                        text += "<p>{}</p>\n".format(str(p).encode('utf-8').strip())
                    continue
                if p.name == "span":
                    break
                text += str(p) + "\n"
            date = dateutil.parser.parse(i.find("span", class_="xdate")['title']).isoformat()
            rv.append({'poster_name': poster_name, 'poster_url': poster_url, 'post_url': post_url, 'text': self.process_html(text), 'orig_text': text, 'date': date})
        return rv
    # FFn forums' rendering is so damned inconsistent and full of special cases
    # it's really not worth trying to extract the number of pages from the
    # thread page itself. Hence this, which is terrible but works.
    def get_npages(self, soup):
        n = 1
        # Scan for a reasonable starting point, so we aren't going through every page in a 150-page thread.
        pages = soup.find("center")
        for i in pages("a"):
            o = re.match(r"/topic/(\d+)/(\d+)/(\d+).*", i['href'])
            if o is not None:
                b = int(o.group(3))
                if b > n:
                    n = b
        a = http.client.HTTPConnection("www.fanfiction.net")
        while 1:
            u = self.make_page_url(n)[25:] # get filepath part of URL
            a.request("HEAD", u)
            try:
                b = a.getresponse()
            except (http.client.BadStatusLine, http.client.ResponseNotReady): # connection was closed
                a = http.client.HTTPConnection("www.fanfiction.net")
                continue
            if b.status == 200:
                n += 1
                continue
            elif b.status == 302:
                return n-1 # This is the response we get if the page is invalid
            else:
                raise Exception("Invalid status: {}".format(b.status))            
    def make_page_url(self, page):
        if self.fid == None or self.tid == None:
            o = re.match("http://www.fanfiction.net/topic/(\d+)/(\d+).*", self.url)
            self.fid = o.group(1)
            self.tid = o.group(2)
        return "http://www.fanfiction.net/topic/{}/{}/{}".format(self.fid, self.tid, page)

class XFGetter(ThreadGetter):
    """This class is designed to retrieve threads from XenForo forums, including
    Spacebattles and Sufficient Velocity. The domain is inferred from the thread
    URL.

    """
    tid = None
    def __init__(self, url):
        ThreadGetter.__init__(self, url)
        o = re.match("(https?://)?([^/]+)/", url)
        self.domain = o.group(2)
    def get_posts(self, soup, url):
        rv = []
        for i in soup.find_all("li", class_="message"):
            ul = i.find("a", class_="username")
            poster_name = str(ul.string)
            poster_url = "http://{}/{}".format(self.domain, ul['href'])
            text = str(i.find("blockquote", class_="messageText"))
            pl = i.find("a", title="Permalink")
            post_url = "http://{}/{}".format(self.domain, pl['href'])
            try:
                d = i.find(class_="DateTime")
                if d.name == 'abbr':
                    date = datetime.datetime.fromtimestamp(int(d['data-time'])).isoformat()
                elif d.name == 'span':
                    date = dateutil.parser.parse(d['title']).isoformat()
                #print(date)
            except:
                traceback.print_exc()
                print(i.prettify())
                date = ""
            rv.append({'poster_name': poster_name, 'poster_url': poster_url, 'text': self.process_html(text), 'orig_text': text, 'post_url': post_url, 'date': date})
        return rv
    def get_npages(self, soup):
        pages = soup.find("span", class_="pageNavHeader")
        o = re.match(r"Page \d+ of (\d+)", pages.string)
        npages = int(o.group(1))
        return npages
    def make_page_url(self, page):
        if self.tid == None:
            o = re.match(r"http://[^/]+/threads/[^.]+\.(\d+).*", self.url)
            self.tid = o.group(1)
        return "http://{}/threads/{}/page-{}".format(self.domain, self.tid, page)
    def get_url_page(self, url=None):
        if url is None:
            url = self.url
        o = re.match(r"https?://[^/]+/threads/[^/]+/?(page-(\d+))?", url)
        r = o.group(2)
        if r is None:
            return 1
        else:
            return int(r)
    def process_html(self, text):
        soup = BeautifulSoup(text)
        soup.blockquote.name = 'div'
        return str(soup)
        
class BLGetter(ThreadGetter):
    tid = None
    def get_posts(self, soup, url):
        rv = []
        for i in soup.find_all("li", class_="postcontainer"):
            try: # I officially hate BL's stupid inconsistent date-display code.
                subd = False
                de = i.find("span", class_="postdate")
                dstr = de.span.contents[0][:-2]
                if dstr == "Today":
                    dstr = ""
                if dstr == "Yesterday":
                    dstr = ""
                    subd = True
                dstr += "T" + de.span.span.string
                date = dateutil.parser.parse(dstr)
                if subd:
                    date = date - datetime.timedelta(1)
                date = date.isoformat()
            except Exception as e:
                traceback.print_exc()
                print(i.prettify())
                date = ""
            post_url = "http://forums.nrvnqsr.com/" + i.find("a", class_="postcounter")['href']
            ul = i.find("a", class_="username")
            poster_name = ul.string
            poster_url = "http://forums.nrvnqsr.com/" + ul['href']
            text = str(i.find("blockquote", class_="postcontent"))
            rv.append({'poster_name': poster_name, 'poster_url': poster_url, 'text': self.process_html(text), 'orig_text': text, 'post_url': post_url, 'date': date})
        return rv
    def get_npages(self, soup):
        for i in soup.find_all("a", class_="popupctrl"):
            o = re.match("Page \d+ of (\d+)", i.string)
            if o:
                npages = int(o.group(1))
                break
        return npages
    def make_page_url(self, page):
        if self.tid == None:
            o = re.match("http://forums.nrvnqsr.com/showthread.php/(\d+).*", self.url)
            self.tid = o.group(1)
        return "http://forums.nrvnqsr.com/showthread.php/{}/page{}".format(self.tid, page)
    def process_html(self, text):
        soup = BeautifulSoup(text)
        for i in soup.find_all('div', class_='bbcode_container'):
            j = i.div
            i.unwrap()
            i = j.div
            j.unwrap()
#            print(i.prettify())
            i.div.decompose()
            i.name = 'blockquote'
        return str(soup)

# Incomplete
class TVTGetter(ThreadGetter):
    def get_npages(self, soup):
        l = list(soup.find_all("a", class_="forumpagebutton"))
        return int(l[-1].string)
    def make_page_url(self, page):
        pass

getters = [ ( re.compile("(https?://)?forums.spacebattles.com/"), XFGetter ),
            ( re.compile("(https?://)?forums.sufficientvelocity.com/"), XFGetter ), 
            ( re.compile("(https?://)?forums.nrvnqsr.com/"), BLGetter ) ]

def make_getter(url):
    """Make a getter for the given URL, parsing the URL to determine which plugin
    should be used.

    """
    for i in getters:
        if i[0].match(url):
            return i[1](url)

def store_thread(thread, fname):
    with gzip.GzipFile(fname, 'w') as of:
        of.write(json.dumps(thread).encode())

def save_thread(plist, fname):
    of = file(fname, "w")
    html = """<html>
<head>
<meta charset="UTF-8">
<style>
table { border-collapse: collapse }
table, tr, td { border: 1px solid black }
td { padding: 5px }
.quoteStyle { color: gray; border-left: 5px solid gray; padding: 10px; margin-left: 20px; display: block }
</style>
</head>
<body>
<table>
"""
    of.write(html)
    for l in plist:
        html = '<tr><td><a href="{}">{}</a><br />\n'.format(l['poster_url'], l['poster_name'])
        html += l['text'] + '\n'
        html += '<small>{}</small>\n</td></tr>\n'.format(l['date'])
        of.write(html)
    html = """</table>
</body>
</html>
"""
    of.write(html)
    of.close()
