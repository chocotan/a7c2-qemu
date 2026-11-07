#!/usr/bin/env python3
"""Download every source package listed on Sony's exact ILCE-7CM2 2.01 page."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit, unquote
from urllib.request import Request, urlopen

PAGE = 'https://oss.sony.net/Products/Linux/DI/ILCE-7CM2_Ver201.html'
NOTICE = 'https://oss.sony.net/Products/Linux/notice.html'
PREFIX = 'https://prodgpl.blob.core.windows.net/download/DI/20251111_ILCE-7CM2_Ver.2.01/'


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            for name, value in attrs:
                if name == 'href' and value:
                    url = urljoin(PAGE,value)
                    if url.startswith(PREFIX):
                        self.urls.append(url)


def request(url):
    return urlopen(Request(url,headers={'User-Agent':'A7C2-source-research/1.0'}),timeout=90)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def checkpoint(path, content):
    temporary = path.with_name(path.name+'.new')
    temporary.write_text(json.dumps(content,indent=2)+'\n')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dest',type=Path,required=True)
    args = parser.parse_args()
    dest = args.dest.resolve()
    dest.mkdir(parents=True,exist_ok=True)
    for url, name in ((PAGE,'source-page.html'),(NOTICE,'notice.html')):
        with request(url) as response:
            raw = response.read(1024*1024+1)
        if len(raw)>1024*1024:
            raise ValueError('Unexpectedly large source index')
        (dest/name).write_bytes(raw)
    raw = (dest/'source-page.html').read_text()
    if 'ILCE-7CM2 Ver.2.01' not in raw:
        raise ValueError('Sony source-page model/version differs')
    links = Links()
    links.feed(raw)
    urls = sorted(set(links.urls))
    if not urls:
        raise ValueError('No source packages found; did not silently skip downloads')
    names = {url:unquote(urlsplit(url).path.rsplit('/',1)[-1]) for url in urls}
    if len(set(names.values()))!=len(urls) or any(not re.fullmatch(r'[A-Za-z0-9_.+-]+',n) for n in names.values()):
        raise ValueError('Duplicate or unsafe download filename')
    previous = {}
    if (dest/'manifest.json').exists():
        previous = json.loads((dest/'manifest.json').read_text()).get('files',{})
    report = {'source_page':PAGE,'source_page_sha256':sha(dest/'source-page.html'),
              'notice':NOTICE,'notice_sha256':sha(dest/'notice.html'),
              'expected_count':len(urls),'listed_files':[names[u] for u in urls],'files':{},'errors':{}}
    checkpoint(dest/'manifest.json',report)
    print('SONY_VER201_SOURCE_LIST count='+str(len(urls)),flush=True)

    def download(url):
        name = names[url]
        path = dest/name
        if path.is_symlink():
            raise ValueError('Refusing source-file symlink: '+name)
        old = previous.get(name)
        if old and old.get('url')==url and path.is_file() and path.stat().st_size==old['bytes'] and sha(path)==old['sha256']:
            return name,old
        part = dest/(name+'.part')
        for attempt in range(3):
            try:
                with request(url) as response, part.open('wb') as output:
                    final = response.geturl()
                    if not final.startswith(PREFIX):
                        raise ValueError('Unexpected source redirect')
                    declared = response.headers.get('Content-Length')
                    size = 0
                    digest = hashlib.sha256()
                    while data := response.read(1024*1024):
                        output.write(data); digest.update(data); size+=len(data)
                    output.flush(); os.fsync(output.fileno())
                    if size==0 or declared is not None and size!=int(declared):
                        raise ValueError('Incomplete source download')
                    record = {'url':url,'final_url':final,'bytes':size,'sha256':digest.hexdigest(),
                              'last_modified':response.headers.get('Last-Modified'),
                              'etag':response.headers.get('ETag')}
                part.replace(path)
                return name,record
            except Exception:
                if attempt==2: raise
                time.sleep(2**attempt)
        raise AssertionError('unreachable')

    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = {pool.submit(download,u):names[u] for u in urls}
        for future in as_completed(pending):
            name = pending[future]
            try:
                _,record=future.result();report['files'][name]=record
                print('SOURCE_OK',name,record['bytes'],record['sha256'],flush=True)
            except Exception as error:
                report['errors'][name]=str(error)
                print('SOURCE_FAILED',name,str(error),flush=True)
            checkpoint(dest/'manifest.json',report)
    if report['errors'] or len(report['files'])!=report['expected_count']:
        raise SystemExit('Not all Sony source packages downloaded; see manifest errors')
    report['complete']=True
    report['total_bytes']=sum(r['bytes'] for r in report['files'].values())
    checkpoint(dest/'manifest.json',report)
    print('SONY_VER201_ALL_SOURCES_DOWNLOADED',len(urls),report['total_bytes'],flush=True)


if __name__=='__main__':
    main()
