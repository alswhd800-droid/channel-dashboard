# -*- coding: utf-8 -*-
"""사파리 OAuth 허용 도우미(10-22 대시보드 개편 때 만듦). 유효조회수_연결.py --no-open 을 뒤에서 띄운 뒤:
  python3 유튜브허용_사파리.py auto <허용 화면의 브랜드 계정 이름> <연결 스크립트 출력 파일> [--fresh]
  python3 유튜브허용_사파리.py open <log> [--fresh]
  브랜드 이름은 옛 이름: 논스킵=빠른한방 · 거인의무덤=동물찰칵 · 새벽서랍=댕찰칵 · 라스트 씬=역사의 급소 · 거대한비밀=민종(개인)
  그 밖: open <log> | state | click <글자> | js <식> | close

★ 새 계정(만든 지 얼마 안 된 것)을 연결할 때는 반드시 --fresh 를 붙이세요.
  --fresh 없으면 기존 창에 이전 계정 쿠키가 남아 있어 구글이 봇으로 의심합니다."""
import sys, time, re, json, random
sys.path.insert(0, '/Users/minjong/Desktop/유튜브 4채널/거대한비밀/program/flow_helpers/safari')
import sf

KEY = 'yt-oauth'
BOUNDS = (3900, 40, 1300, 900)


def _human_sleep(lo=2.0, hi=5.0):
    """사람처럼 보이도록 무작위 대기. 고정 딜레이 대신 여기를 씁니다."""
    time.sleep(random.uniform(lo, hi))


def handle():
    r = sf._reg(); wid = r.get(KEY)
    if not wid or not sf.window_alive(wid):
        return None
    return 'wid:%d' % int(wid)


def fresh_window(url):
    """기존 창을 닫고 새 창을 엽니다. 새 계정 연결 때 이전 쿠키 오염을 막습니다."""
    h = handle()
    if h:
        sf.close_tool(KEY)
        time.sleep(1.5)
    sf.tool_window(KEY, url, bounds=BOUNDS)


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
    # 1단계: 요소를 찾아서 스크롤만(클릭 X) — 사람이 화면을 찾는 모습
    sf.fn(h, r"""
    const L = %s, EX = %s;
    const vis = el => { const r = el.getBoundingClientRect(); return r.width>0 && r.height>0; };
    const els = [...document.querySelectorAll('button,[role=button],a,[role=link],li,div[data-identifier],[data-email],[jsname],span')].filter(vis);
    const norm = s => (s||'').trim().replace(/\s+/g,' ');
    let hits = els.filter(e => { const t = norm(e.innerText || e.getAttribute('aria-label')); return EX ? t === L : t.includes(L); });
    const pref = hits.filter(e => /^(BUTTON|A)$/.test(e.tagName) || e.getAttribute('role')==='button' || e.getAttribute('role')==='link' || e.hasAttribute('data-identifier') || e.hasAttribute('data-email'));
    const pick = (pref.length ? pref : hits).sort((a,b)=> norm(a.innerText).length - norm(b.innerText).length)[0];
    if (pick) pick.scrollIntoView({block:'center', behavior:'smooth'});
    """ % (json.dumps(label), 'true' if exact else 'false'))
    _human_sleep(0.5, 1.5)  # 스크롤 후 잠깐 읽는 척
    # 2단계: 실제 클릭
    body = r"""
    const L = %s, EX = %s;
    const vis = el => { const r = el.getBoundingClientRect(); return r.width>0 && r.height>0; };
    const els = [...document.querySelectorAll('button,[role=button],a,[role=link],li,div[data-identifier],[data-email],[jsname],span')].filter(vis);
    const norm = s => (s||'').trim().replace(/\s+/g,' ');
    let hits = els.filter(e => { const t = norm(e.innerText || e.getAttribute('aria-label')); return EX ? t === L : t.includes(L); });
    const pref = hits.filter(e => /^(BUTTON|A)$/.test(e.tagName) || e.getAttribute('role')==='button' || e.getAttribute('role')==='link' || e.hasAttribute('data-identifier') || e.hasAttribute('data-email'));
    const pick = (pref.length ? pref : hits).sort((a,b)=> norm(a.innerText).length - norm(b.innerText).length)[0];
    if (!pick) return {res:'notfound', n: hits.length};
    pick.click();
    return {res:'clicked', tag: pick.tagName, t: norm(pick.innerText).slice(0,60), n: hits.length};
    """ % (json.dumps(label), 'true' if exact else 'false')
    return sf.fn(h, body)


if __name__ == '__main__':
    a = sys.argv[1:]
    cmd = a[0]
    use_fresh = '--fresh' in a
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
        if use_fresh:
            fresh_window(url)   # 새 계정: 기존 창·쿠키를 버리고 새로 시작
        else:
            h = handle()
            if h:
                sf.nav(h, url)
            else:
                sf.tool_window(KEY, url, bounds=BOUNDS)
        _human_sleep(3.5, 6.0)
        print(json.dumps(state(), ensure_ascii=False, indent=0))
    elif cmd == 'state':
        print(json.dumps(state(), ensure_ascii=False, indent=0))
    elif cmd == 'click':
        print(json.dumps(click(a[1], len(a) > 2 and a[2] == 'exact'), ensure_ascii=False))
        _human_sleep(float(a[3]) if len(a) > 3 else 2.5, float(a[3]) + 1.5 if len(a) > 3 else 4.5)
        print(json.dumps(state(), ensure_ascii=False, indent=0))
    elif cmd == 'js':
        print(json.dumps(sf.fn(handle(), a[1]), ensure_ascii=False))
    elif cmd == 'close':
        print(sf.close_tool(KEY))


def auto(brand, log, fresh=False):
    """허용 화면을 끝까지. brand = 브랜드 목록에서 고를 이름('민종' = 개인).
    fresh=True 면 기존 창을 닫고 새 창으로 시작합니다(새 계정 연결 시 권장)."""
    steps = []
    if fresh:
        h = handle()
        if h:
            sf.close_tool(KEY)
            time.sleep(1.5)
        steps.append('fresh_window')
    for i in range(14):
        s = state(); u = s.get('url', ''); t = s.get('txt', '')
        steps.append('@' + u.split('?')[0][-40:])
        if '127.0.0.1:8765' in u:
            return 'redirected', steps
        if re.search(r'비밀번호|패스키|2단계|본인 확인|Verify it|password', t) and 'accounts.google.com' in u and 'oauth' not in u.split('?')[0]:
            return 'NEED_USER: ' + u[:60] + ' | ' + t[:200], steps
        if 'accountchooser' in u:
            _human_sleep(0.8, 2.0)          # 계정 목록을 훑어보는 시간
            r = js_click_div('alswhd800@gmail.com', exact=True); steps.append('chooser:' + str(r))
        elif 'delegation' in u:
            names = [b.split('|')[2].replace(' YouTube', '') for b in s['btns'] if b.startswith('DIV|') and b.endswith('YouTube')]
            steps.append('brands=' + ','.join(names))
            _human_sleep(1.2, 3.0)          # 브랜드 목록을 읽는 시간
            if brand == '민종':
                r = js_click_div('민종 alswhd800@gmail.com', exact=True)
            elif brand in names:
                r = js_click_div(brand + ' YouTube', exact=True)
            else:
                return 'NOT_IN_LIST', steps
            steps.append('pick:' + str(r))
        elif 'oauth/warning' in u:
            _human_sleep(1.5, 3.5)          # 경고 문구를 읽는 시간
            if '채널 대시보드(으)로 이동(안전하지 않음)' in t:
                r = click('채널 대시보드(으)로 이동(안전하지 않음)', True)
            else:
                r = click('고급', True)
            steps.append('warn:' + r.get('res', ''))
        elif 'consent' in u:
            _human_sleep(1.2, 2.8)          # 권한 항목을 읽는 시간
            r = sf.fn(handle(), r"""const cb=[...document.querySelectorAll('input[type=checkbox]')]; let n=0; cb.forEach(c=>{ if(!c.checked){ c.scrollIntoView({block:'center', behavior:'smooth'}); c.click(); n++; } }); return {n:cb.length, clicked:n, all:cb.every(c=>c.checked)};""")
            steps.append('cb:' + json.dumps(r))
            _human_sleep(0.8, 2.0)
            r2 = click('계속', True); steps.append('cont:' + json.dumps(r2, ensure_ascii=False))
        elif 'support.google.com' in u:
            sf.fn(handle(), 'history.back(); return 1'); steps.append('back')
        else:
            steps.append('?' + u[:60] + ' ' + t[:80].replace('\n', ' '))
        _human_sleep(2.0, 5.0)              # 페이지 이동 후 사람처럼 대기
    return 'TIMEOUT', steps


def js_click_div(label, exact=True):
    body = r"""const L=%s; const ds=[...document.querySelectorAll('div,li')].filter(d=>{const r=d.getBoundingClientRect(); return r.width>0&&d.innerText&&d.innerText.trim().replace(/\s+/g,' ')===L;});
    const e=ds[ds.length-1]; if(!e) return 'none'; const c=e.closest('[role=link],[role=button],li,[data-identifier]')||e; c.scrollIntoView({block:'center', behavior:'smooth'}); c.click(); return c.tagName+':'+(c.getAttribute('role')||'')""" % json.dumps(label)
    return sf.fn(handle(), body)


if __name__ == '__main__' and sys.argv[1] == 'auto':
    use_fresh = '--fresh' in sys.argv
    log = sys.argv[3]
    url = None
    for _ in range(40):
        m = re.search(r'^URL: (\S+)', open(log).read(), re.M) if __import__('os').path.exists(log) else None
        if m:
            url = m.group(1); break
        time.sleep(0.5)
    if not url:
        print('no url'); sys.exit(1)
    if use_fresh:
        fresh_window(url)       # 새 계정: 기존 창·쿠키를 버리고 새로 시작
    else:
        h = handle()
        if h:
            sf.nav(h, url)
        else:
            sf.tool_window(KEY, url, bounds=BOUNDS)
    _human_sleep(3.5, 6.0)
    res, steps = auto(sys.argv[2], log, fresh=use_fresh)
    print(res)
    for st in steps:
        print(' ', st)
    time.sleep(5)
    print(''.join(l for l in open(log) if not l.startswith('URL:')))
