# -*- coding: utf-8 -*-
"""사파리 OAuth 허용 도우미(10-22 대시보드 개편 때 만듦). 유효조회수_연결.py --no-open 을 뒤에서 띄운 뒤:
  python3 유튜브허용_사파리.py auto <허용 화면의 브랜드 계정 이름> <연결 스크립트 출력 파일>
  브랜드 이름은 옛 이름: 논스킵=빠른한방 · 거인의무덤=동물찰칵 · 새벽서랍=댕찰칵 · 라스트 씬=역사의 급소 · 거대한비밀=민종(개인)
  그 밖: open <log> | state | click <글자> | js <식> | close"""
import sys, time, re, json
sys.path.insert(0, '/Users/minjong/Desktop/유튜브 4채널/거대한비밀/program/flow_helpers/safari')
import sf

KEY = 'yt-oauth'
BOUNDS = (3900, 40, 1300, 900)


def handle():
    r = sf._reg(); wid = r.get(KEY)
    if not wid or not sf.window_alive(wid):
        return None
    return 'wid:%d' % int(wid)


def state():
    h = handle()
    if not h:
        return {'err': 'no window'}
    body = r"""
    const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; };
    const txt = (document.body ? document.body.innerText : '').replace(/\s+\n/g,'\n').slice(0, 1500);
    const btns = [...document.querySelectorAll('button,[role=button],a,[role=link],li[data-identifier],div[data-identifier],[data-email],input[type=checkbox],[role=checkbox]')].filter(vis).map(e => (e.tagName + '|' + (e.getAttribute('type')||'') + '|' + (e.innerText||e.getAttribute('aria-label')||e.getAttribute('data-identifier')||'').trim().replace(/\s+/g,' ').slice(0,60) + (e.type==='checkbox'||e.getAttribute('role')==='checkbox' ? '|checked=' + (e.checked||e.getAttribute('aria-checked')) : ''))).slice(0,60);
    return {url: location.href.slice(0,90), title: document.title, vis: document.visibilityState, txt, btns};
    """
    return sf.fn(h, body)


def click(label, exact=False):
    h = handle()
    body = r"""
    const L = %s, EX = %s;
    const vis = el => { const r = el.getBoundingClientRect(); return r.width>0 && r.height>0; };
    const els = [...document.querySelectorAll('button,[role=button],a,[role=link],li,div[data-identifier],[data-email],[jsname],span')].filter(vis);
    const norm = s => (s||'').trim().replace(/\s+/g,' ');
    let hits = els.filter(e => { const t = norm(e.innerText || e.getAttribute('aria-label')); return EX ? t === L : t.includes(L); });
    // 가장 안쪽(작은) 요소 대신 클릭 가능한 요소 우선
    const pref = hits.filter(e => /^(BUTTON|A)$/.test(e.tagName) || e.getAttribute('role')==='button' || e.getAttribute('role')==='link' || e.hasAttribute('data-identifier') || e.hasAttribute('data-email'));
    const pick = (pref.length ? pref : hits).sort((a,b)=> norm(a.innerText).length - norm(b.innerText).length)[0];
    if (!pick) return {res:'notfound', n: hits.length};
    pick.scrollIntoView({block:'center'});
    pick.click();
    return {res:'clicked', tag: pick.tagName, t: norm(pick.innerText).slice(0,60), n: hits.length};
    """ % (json.dumps(label), 'true' if exact else 'false')
    return sf.fn(h, body)


if __name__ == '__main__':
    a = sys.argv[1:]
    cmd = a[0]
    if cmd == 'open':
        log = a[1]
        url = None
        for _ in range(40):
            try:
                m = re.search(r'^URL: (\S+)', open(log).read(), re.M)
            except Exception:
                m = None
            if m:
                url = m.group(1); break
            time.sleep(0.5)
        if not url:
            print('no url'); sys.exit(1)
        h = handle()
        if h:
            sf.nav(h, url)
        else:
            sf.tool_window(KEY, url, bounds=BOUNDS)
        time.sleep(4)
        print(json.dumps(state(), ensure_ascii=False, indent=0))
    elif cmd == 'state':
        print(json.dumps(state(), ensure_ascii=False, indent=0))
    elif cmd == 'click':
        print(json.dumps(click(a[1], len(a) > 2 and a[2] == 'exact'), ensure_ascii=False))
        time.sleep(float(a[3]) if len(a) > 3 else 3)
        print(json.dumps(state(), ensure_ascii=False, indent=0))
    elif cmd == 'js':
        print(json.dumps(sf.fn(handle(), a[1]), ensure_ascii=False))
    elif cmd == 'close':
        print(sf.close_tool(KEY))


def auto(brand, log):
    """허용 화면을 끝까지. brand = 브랜드 목록에서 고를 이름('민종' = 개인). 돌려주는 값 = 결과 문자열."""
    steps = []
    for i in range(14):
        s = state(); u = s.get('url', ''); t = s.get('txt', '')
        steps.append('@' + u.split('?')[0][-40:])
        if '127.0.0.1:8765' in u:
            return 'redirected', steps
        if re.search(r'비밀번호|패스키|2단계|본인 확인|Verify it|password', t) and 'accounts.google.com' in u and 'oauth' not in u.split('?')[0]:
            return 'NEED_USER: ' + u[:60] + ' | ' + t[:200], steps
        if 'accountchooser' in u:
            r = js_click_div('alswhd800@gmail.com', exact=True); steps.append('chooser:' + str(r))
        elif 'delegation' in u:
            names = [b.split('|')[2].replace(' YouTube', '') for b in s['btns'] if b.startswith('DIV|') and b.endswith('YouTube')]
            steps.append('brands=' + ','.join(names))
            if brand == '민종':
                r = js_click_div('민종 alswhd800@gmail.com', exact=True)
            elif brand in names:
                r = js_click_div(brand + ' YouTube', exact=True)
            else:
                return 'NOT_IN_LIST', steps
            steps.append('pick:' + str(r))
        elif 'oauth/warning' in u:
            if '채널 대시보드(으)로 이동(안전하지 않음)' in t:
                r = click('채널 대시보드(으)로 이동(안전하지 않음)', True)
            else:
                r = click('고급', True)
            steps.append('warn:' + r.get('res', ''))
        elif 'consent' in u:
            r = sf.fn(handle(), r"""const cb=[...document.querySelectorAll('input[type=checkbox]')]; let n=0; cb.forEach(c=>{ if(!c.checked){ c.click(); n++; } }); return {n:cb.length, clicked:n, all:cb.every(c=>c.checked)};""")
            steps.append('cb:' + json.dumps(r))
            time.sleep(1)
            r2 = click('계속', True); steps.append('cont:' + json.dumps(r2, ensure_ascii=False))
        elif 'support.google.com' in u:
            sf.fn(handle(), 'history.back(); return 1'); steps.append('back')
        else:
            steps.append('?' + u[:60] + ' ' + t[:80].replace('\n', ' '))
        time.sleep(3)
    return 'TIMEOUT', steps


def js_click_div(label, exact=True):
    body = r"""const L=%s; const ds=[...document.querySelectorAll('div,li')].filter(d=>{const r=d.getBoundingClientRect(); return r.width>0&&d.innerText&&d.innerText.trim().replace(/\s+/g,' ')===L;});
    const e=ds[ds.length-1]; if(!e) return 'none'; const c=e.closest('[role=link],[role=button],li,[data-identifier]')||e; c.click(); return c.tagName+':'+(c.getAttribute('role')||'')""" % json.dumps(label)
    return sf.fn(handle(), body)


if __name__ == '__main__' and sys.argv[1] == 'auto':
    log = sys.argv[3]
    url = None
    for _ in range(40):
        m = re.search(r'^URL: (\S+)', open(log).read(), re.M) if __import__('os').path.exists(log) else None
        if m:
            url = m.group(1); break
        time.sleep(0.5)
    if not url:
        print('no url'); sys.exit(1)
    h = handle()
    if h:
        sf.nav(h, url)
    else:
        sf.tool_window(KEY, url, bounds=BOUNDS)
    time.sleep(4)
    res, steps = auto(sys.argv[2], log)
    print(res)
    for st in steps:
        print(' ', st)
    time.sleep(5)
    print(''.join(l for l in open(log) if not l.startswith('URL:')))
