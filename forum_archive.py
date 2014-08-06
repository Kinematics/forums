#!/usr/bin/python3

# This program is designed to scrape forum threads off the Web and return their
# contents in a minimal common format. The ideal is to be able to write a plugin
# for any forum and access it using the same API. A thread is returned as a list
# of posts; a post is a dictionary providing HTML text, name of poster, date,
# and other metadata as appropriate.

# This code has recently undergone a major rewrite in conjunction with the
# thread_story script. The only thread modules which can be assumed to hold full
# functionality along with that script are XFGetter and QQGetter.

import re, urllib.request, urllib.error, urllib.parse, sys, datetime, http.client
from bs4 import BeautifulSoup
import bs4
import dateutil.parser, datetime, math, time
import traceback, http.cookiejar, hashlib
import json, gzip

def urlopen_retry(url, tries=3, delay=1, opener=None):
    """Open a URL, with retries on failure. Spoofs user agent to look like Firefox,
    due to various sites attempting to prohibit automatic downloading."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux i686; rv:21.0) Gecko/20100101 Firefox/21.0"})
    if opener is None:
        ofunc = urllib.request.urlopen
    else:
        ofunc = opener.open
    for i in range(tries):
        try:
            r = ofunc(req)
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
        self.opener = None
    def get_thread(self, pages=None):
        """This method will download the thread (of the appropriate forum) which was
        passed to the object's constructor. URLs are not checked for
        correctness; unpredictable errors will occur on one which is not as
        expected. The parameter 'pages' controls which pages of the thread are
        downloaded. If this is not iterable, it refers to a single page; if it
        is, it is construed as a list of pages to download. Each value can be
        either an integer, referring to a 1-indexed page number as the Web site
        provides, or an opaque string (page component) which will download the
        correct page when plugged into a URL.

        """
        r = urlopen_retry(self.url, opener=self.opener)
        html = r.read()
        soup = BeautifulSoup(html)
        npages = self.get_npages(soup)
        print("{} pages".format(npages))
        thread = []
        if pages is None:
            pages = range(1, npages+1)
        if type(pages) not in [list, tuple]:
            pages = [pages]
        for i in pages:
            purl = self.make_page_url(i)
            r = urlopen_retry(purl, opener=self.opener)
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
        """This method takes a URL pointing to a thread page and returns the page number
        or page component. This is guaranteed to be valid when passed to
        get_thread, and to refer to the thread 

        """
        
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
    def __init__(self, url):
        ThreadGetter.__init__(self, url)
        o = re.match("(https?://)?([^/]+)/", url)
        self.domain = o.group(2)
        o = re.match(r"http://[^/]+/threads/[^.]+\.(\d+).*", self.url)
        self.tid = o.group(1)
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
        if type(page) == int:
            page = "page-{}".format(page)
        return "http://{}/threads/{}/{}".format(self.domain, self.tid, page)
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

class QQGetter(ThreadGetter):
    def __init__(self, url):
        ThreadGetter.__init__(self, url)
        o = re.match(r"(https?://)?questionablequesting.com/index.php\?topic=(?P<tid>\d+)(\.(?P<pc>[^#]+))?(#.+)?", self.url)
        self.__dict__.update(o.groupdict())
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def login(self, username, password):
        d = self.opener.open('http://questionablequesting.com/index.php?action=login').read()
        s = BeautifulSoup(d)
        sid = re.search(r"'([^']+)'", s.find('form', id='frmLogin')['onsubmit']).group(1)
        hs1 = username.lower() + password
        hs2 = hashlib.sha1(hs1.encode()).hexdigest() + sid
        hs3 = hashlib.sha1(hs2.encode()).hexdigest()
        d = self.opener.open('http://questionablequesting.com/index.php?action=login2', 
                           data='user={}&passwrd=&cookieneverexp=on&hash_passwrd={}'.format(username, hs3).encode()).read()
        return d
    def handle_url(self, url):
        """This function removes QQ's PHPSESSID component from URLs, which it only
        inserts if viewing without cookies.

        """
        r = urllib.parse.urlparse(url)
        n = urllib.parse.parse_qs(r.query)
        n.pop('PHPSESSID', None)
        a = urllib.parse.urlencode(n, doseq=True)
        return urllib.parse.urlunparse((r[0], r[1], r[2], '', a, r[5]))
    def get_posts(self, soup, url):
        vclist = []
        for i in soup('div', class_="post_wrapper"):
            el = i.find('h5', id=re.compile("subject_"))
            pl = self.handle_url(el.a['href'])
            cpn = re.match(r"subject_(\d+)", el['id']).group(1)
            text = str(i.find('div', class_='inner', id='msg_{}'.format(cpn)))
            poe = i.find('div', class_='poster').h4.a
            poster = poe.string
            prol = self.handle_url(poe['href'])
            de = i.find('div', class_='smalltext')
            date = dateutil.parser.parse(de.strong.next_sibling[1:-2]).isoformat()
            pe = {'poster_name': poster, 'poster_url': prol, 'text': self.process_html(text), 'orig_text': text, 'post_url': pl, 'date': date}
            vclist.append(pe)
        return vclist
    def get_npages(self, soup):
        pl = soup.find('div', class_='pagelinks')
        cpage = int(pl.find('strong').string)
        try:
            mpage = int(soup.find_all('a', class_='navPages')[-1].string)
        except IndexError: # no other pages
            mpage = 1
        mpage = mpage if mpage > cpage else cpage
        return mpage
    def make_page_url(self, page):
        if type(page) == int:
            page = str((page - 1) * 50)
        return "http://questionablequesting.com/index.php?topic={}.{}".format(self.tid, page)
    def get_url_page(self, url=None):
        if url is None:
            return self.pc
        o = re.match(r"(https?://)?questionablequesting.com/index.php\?topic=(?P<tid>\d+)(\.(?P<pc>[^#]+))?(#.+)?", self.url)
        r = o.group('pc')
        return r
        
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
    def get_url_page(self, url=None):
        if url is None:
            url = self.url
        

# Incomplete
class TVTGetter(ThreadGetter):
    def get_npages(self, soup):
        l = list(soup.find_all("a", class_="forumpagebutton"))
        return int(l[-1].string)
    def make_page_url(self, page):
        pass

getters = [ ( re.compile("(https?://)?forums.spacebattles.com/"), XFGetter ),
            ( re.compile("(https?://)?forums.sufficientvelocity.com/"), XFGetter ), 
            ( re.compile("(https?://)?forums.nrvnqsr.com/"), BLGetter ),
            ( re.compile("(https?://)?questionablequesting.com/"), QQGetter ), ]

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
