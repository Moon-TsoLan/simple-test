import sys, time
import requests
import lxml.html

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}
kw = '中标公告'
u = ('http://search.ccgp.gov.cn/bxsearch?searchtype=1&page_index=1&bidSort=0&buyerName=&projectId='
     f'&pinMu=0&bidType=0&dbselect=bidx&kw={requests.utils.quote(kw)}'
     '&start_time=2026%3A08%3A10&end_time=2026%3A08%3A16&timeType=2&displayZone=&zoneId=&pppStatus=0&agentName=')
s = requests.Session()
s.get('http://www.ccgp.gov.cn/', headers={**HEADERS, 'Referer': 'http://www.ccgp.gov.cn/'}, timeout=30)
time.sleep(5)
r = s.get(u, headers={**HEADERS, 'Referer': 'http://www.ccgp.gov.cn/'}, timeout=30)
r.encoding = 'utf-8'
root = lxml.html.fromstring(r.text)
print('status', r.status_code, 'len', len(r.content))
print('title', root.findtext('.//title'))
for a in root.xpath('//a[@href]'):
    href = a.get('href')
    text = ' '.join(a.text_content().split())
    if href and ('/cggg/' in href or 'detail' in href or href.endswith('.htm')):
        print(text[:80], '|', href[:220])
print('UL COUNT', len(root.xpath('//ul')))
print('LI COUNT', len(root.xpath('//li')))
