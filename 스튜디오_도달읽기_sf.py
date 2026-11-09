# -*- coding: utf-8 -*-
"""스튜디오 분석 '도달범위'(썸네일 노출수·노출 클릭률) 읽기 — 읽기만. 2026-11-09 채널 대시보드용으로 만듦.

쓰는 법:  python3 스튜디오_도달읽기_sf.py <출력.json> [채널ID ...]
          (채널ID 를 안 주면 아래 DEFAULT 9개 — 우리 7채널 + 다른 구글 계정(현우) 2채널)
결과(JSON): {"at","source","period":{"label":"지난 28일","start","end","tz":"PT"},
             "channels":{채널ID:{"name","ok","err","total":{impressions,ctr,views,avd_sec,avp,watch_hours,subs_net},
                                  "traffic":[{key,label,impressions,ctr,views}], "videos":[{id,impressions,ctr,views,avd_sec,avp,shorts_kept_pct}]}}}
  - ctr·avp·shorts_kept_pct 는 % 숫자(2.81 = 2.81%). avd_sec 초, watch_hours 시간. 화면 반올림 전 값. 값이 없으면 null.
  - shorts_kept_pct = Shorts 피드 '계속 시청함' %(SHORTS_FEED_IMPRESSIONS_VTR) — Shorts 피드 노출이 있는 영상(=쇼츠)만, 나머지 null.
  - traffic key 는 스튜디오 내부 이름 그대로: SUBSCRIBER=탐색 기능, YT_RELATED=추천 동영상, YT_SEARCH=검색, SHORTS=Shorts 피드 …
    (트래픽 소스의 impressions/ctr 은 '썸네일' 노출 — Shorts 피드 줄은 썸네일 노출이 없어 null 이 정상)

하는 일(채널마다):
  1) www.youtube.com/channel_switcher?next=<그 채널 분석 주소> 에서 그 채널 항목(핸들)을 JS 클릭으로 전환
     (스튜디오는 주소 끝 ?c=채널ID 로는 이제 '권한 없음' — 11-09 확인)
  2) 분석 화면 ytcfg CHANNEL_ID 가 그 채널인지 확인 → 아니면 읽지 않음
  3) XHR 을 가로채고 history.pushState 로 '콘텐츠' 탭을 열어 화면이 부르는 yta_web/get_cards 요청의 헤더·context 를 얻음
     (요청 screenConfig.entity.channelId 도 그 채널인지 확인) → 같은 헤더로 yta_web/join 에 직접 질의
  4) 기간 = 화면 머리글의 '지난 28일' 날짜 범위(태평양 시간). 11-09 거대한비밀로 대조: 화면 Shorts 조회수 787.2만 = 질의 7,872,027,
     화면 카드 노출 1,132,669·CTR 7.6 = 질의 값 그대로.
  - 누르는 것은 channel_switcher 의 채널 항목뿐. 저장·적용·A/B·제목·썸네일·설정·업로드는 건드리지 않는다.
  - 시작 전·전환 전마다 다른 스튜디오 도구(*_sf.py — 그림·Flow 도구 빼고)가 돌면 끝날 때까지 기다린다(세션은 모든 사파리 창이 같이 씀).
  - 끝나면(실패해도) 기본 채널을 '@논스킵'으로 되돌리고 확인한 뒤 도구 창을 닫는다(SF_KEEP=1 이면 창만 남김).
  - 창: 사파리 도구 창 하나(sf.tool_window 'studio_reach'), 앞으로 안 가져옴, 둘째 화면 오른쪽 아래 50x105 만 보이는 자리.
"""
import datetime, json, os, re, shutil, subprocess, sys, time, urllib.parse

sys.path.insert(0, '/Users/minjong/Desktop/유튜브 4채널/거대한비밀/program/flow_helpers/safari')
import sf  # noqa: E402

KEY = 'studio_reach'
BOUNDS = (3790, 975, 1336, 861)   # 11-09: 화면 1920x1080 두 개(0~3840) — 둘째 화면 오른쪽 아래 50x105 만 보임(업로드 도구와 같은 자리)
FLOW_LOCK = '/Users/minjong/Desktop/유튜브 4채널/거대한비밀/episodes/_flow.lock'
HOME_CH = 'UCTW1Dy2mEpRWAdZ12qVVL8A'   # 논스킵 — 다른 도구들이 기본 채널로 기대함
HOME_HANDLE = '@논스킵'

# 채널ID: (이름, channel_switcher 핸들) — 핸들이 None 이면 이 사파리 계정의 전환 목록에 없음
CHANNELS = {
    'UCvv5gDOhB164Ao_IB2zC0nA': ('거대한비밀', '@거대한비밀'),
    'UCTW1Dy2mEpRWAdZ12qVVL8A': ('논스킵', '@논스킵'),
    'UCiQOGLTz89s8ZhWGxMp1JfA': ('스튜디오 이면', '@스튜디오이면'),
    'UC0N5pdcVXvvZ9fVqTiRKXSA': ('밑바닥부터', '@mitbadakbuteo'),
    'UCrjSI-EYrWrxNUOEo06tS0w': ('몸리학', '@momrihak'),
    'UC4SccKanDerMZK3CtBZjVnQ': ('스튜디오K', '@studiok_official'),
    'UCAy5fJTHLrG8WatQqUcJS0g': ('새벽서랍', '@새벽서랍dawn'),
    'UCbVskN7P3vwHhL2UNrfzB6A': ('플레이트미디어', None),   # 다른 구글 계정(현우)
    'UCCbtZv--gwZNVVGovQl2KBg': ('메디스튜디오', None),     # 다른 구글 계정(현우)
}
OTHER_ACCOUNT = {'UCbVskN7P3vwHhL2UNrfzB6A', 'UCCbtZv--gwZNVVGovQl2KBg'}
DEFAULT = list(CHANNELS)

# 스튜디오 채널을 건드리지 않는 도구(기다리지 않음)
NOT_STUDIO = ('vrun_sf', 'gpt_sf', 'gemini_sf', 'nb2run_sf', 'flow_sf', 'gem_multi', 'editrun_sf', 'align_sf',
              'chatgpt', 'gpt_', 'dreamina', '스튜디오_도달읽기_sf')

M_VIDEO = ['VIDEO_THUMBNAIL_IMPRESSIONS', 'VIDEO_THUMBNAIL_IMPRESSIONS_VTR', 'EXTERNAL_VIEWS', 'AVERAGE_WATCH_TIME',
           'AVERAGE_WATCH_PERCENTAGE', 'SHORTS_FEED_IMPRESSIONS', 'SHORTS_FEED_IMPRESSIONS_VTR']
M_TOTAL = ['VIDEO_THUMBNAIL_IMPRESSIONS', 'VIDEO_THUMBNAIL_IMPRESSIONS_VTR', 'EXTERNAL_VIEWS', 'AVERAGE_WATCH_TIME',
           'AVERAGE_WATCH_PERCENTAGE', 'EXTERNAL_WATCH_TIME', 'SUBSCRIBERS_NET_CHANGE']
M_TRAFFIC = ['VIDEO_THUMBNAIL_IMPRESSIONS', 'VIDEO_THUMBNAIL_IMPRESSIONS_VTR', 'EXTERNAL_VIEWS']   # TRAFFIC_SOURCE_TYPE 은 측정 하나당 노드 하나(여럿이면 failure UNKNOWN)

TS_LABEL = {
    'SUBSCRIBER': '탐색 기능', 'YT_RELATED': '추천 동영상', 'YT_SEARCH': 'YouTube 검색', 'SHORTS': 'Shorts 피드',
    'YT_CHANNEL': '채널 페이지', 'EXT_URL': '외부', 'YT_OTHER_PAGE': '기타 YouTube 기능',
    'UNKNOWN_MOBILE_OR_DIRECT': '직접 입력 또는 알 수 없음', 'NO_LINK_OTHER': '직접 입력 또는 알 수 없음',
    'YT_PLAYLIST_PAGE': '재생목록', 'PLAYLIST': '재생목록', 'NOTIFICATION': '알림', 'END_SCREEN': '최종 화면',
    'ANNOTATION': '카드·주석', 'HASHTAGS': '해시태그 페이지', 'SOUND_PAGE': '사운드 페이지',
    'SHORTS_CONTENT_LINKS': 'Shorts 콘텐츠 링크', 'ADVERTISING': 'YouTube 광고', 'CAMPAIGN_CARD': '캠페인 카드',
    'VIDEO_REMIXES': '리믹스', 'LIVE_REDIRECT': '실시간 리디렉션', 'PRODUCT_PAGE': '제품 페이지',
    'NO_LINK_EMBEDDED': '삽입된 플레이어', 'UNKNOWN_EMBED': '삽입된 플레이어', 'PROMOTED': '프로모션',
    'IMMERSIVE_LIVE': '몰입형 라이브',
}

VIS_SHIM = r"""(() => { if (window.__visShim) return; window.__visShim = Date.now();
  for (const [k, v] of [['visibilityState', 'visible'], ['hidden', false], ['webkitVisibilityState', 'visible'], ['webkitHidden', false]]) { try { Object.defineProperty(Document.prototype, k, {get() { return v; }, configurable: true}); } catch (e) {} }
  document.hasFocus = () => true;
  const oraf = window.requestAnimationFrame.bind(window), ocaf = window.cancelAnimationFrame.bind(window); let seq = 0; const live = new Map();
  window.requestAnimationFrame = function (cb) { const id = ++seq + 1e6; let done = false; const fire = t => { if (done) return; done = true; live.delete(id); try { cb(t); } catch (e) { setTimeout(() => { throw e; }); } };
    const h = oraf(fire); const to = setTimeout(() => fire(performance.now()), 16); live.set(id, [h, to]); return id; };
  window.cancelAnimationFrame = function (id) { const v = live.get(id); if (v) { ocaf(v[0]); clearTimeout(v[1]); live.delete(id); } else { try { ocaf(id); } catch (e) {} } };
  document.dispatchEvent(new Event('visibilitychange'));
})()"""

NO_LEAVE = "window.onbeforeunload=null; window.addEventListener('beforeunload', e=>{e.stopImmediatePropagation();}, true);"

HOOK = r"""(() => { if (window.__jh) return 'already'; window.__jh = [];
 const oo = XMLHttpRequest.prototype.open, os = XMLHttpRequest.prototype.send, osh = XMLHttpRequest.prototype.setRequestHeader;
 XMLHttpRequest.prototype.open = function(m, u) { this.__u = u; this.__h = {}; return oo.apply(this, arguments); };
 XMLHttpRequest.prototype.setRequestHeader = function(k, v) { try { this.__h[k] = v; } catch(e){} return osh.apply(this, arguments); };
 XMLHttpRequest.prototype.send = function(b) { try { if (/yta_web\//.test(this.__u || '')) window.__jh.push({u:this.__u, h:this.__h, b:(typeof b==='string')?b:null, t:Date.now()}); } catch(e){} return os.apply(this, arguments); };
 const of = window.fetch;
 window.fetch = function(input, init) { try { const u = (typeof input === 'string') ? input : (input && input.url) || '';
   if (/yta_web\//.test(u)) { let h = {}; try { const hh = (init && init.headers) || (input && input.headers); if (hh) { if (hh.forEach) hh.forEach((v,k)=>h[k]=v); else Object.assign(h, hh); } } catch(e){}
     window.__jh.push({u:u, h:h, b:(init && typeof init.body==='string')?init.body:null, t:Date.now()}); } } catch(e){}
   return of.apply(this, arguments); };
 return 'hooked'; })()"""

STATE = r"""(()=>{let ch=null; try{ch=(window.ytcfg&&ytcfg.get)?ytcfg.get('CHANNEL_ID'):null}catch(e){}
 const t=(document.body&&document.body.innerText||'');
 return {url:location.href.slice(0,200), host:location.host, ch:ch, ready:document.readyState, vis:document.visibilityState,
   denied:/권한이 없습니다|Permission denied|don't have permission/.test(t.slice(0,3000)),
   name:((document.querySelector('#entity-name')||{}).innerText||'').trim()};})()"""

# 그 핸들 항목 하나만 JS 클릭(전환 목록 글: "거대한비밀 @거대한비밀 구독자 24,200명")
PICK = r"""const H=%s.toLowerCase(); const it=[...document.querySelectorAll('ytd-account-item-renderer')];
 const toks=e=>(e.innerText||'').trim().replace(/\s+/g,' ').toLowerCase().split(' ');
 const names=it.map(e=>(e.innerText||'').trim().replace(/\s+/g,' ').slice(0,50));
 const m=it.filter(e=>toks(e).indexOf(H)>=0);
 if(m.length!==1) return {n:it.length, err:'match '+m.length, names:names};
 const p=m[0].querySelector('tp-yt-paper-icon-item')||m[0]; p.scrollIntoView({block:'center'}); p.click();
 return {n:it.length, clicked:(m[0].innerText||'').trim().replace(/\s+/g,' ').slice(0,50)};"""

SW_LIST = r"""(()=>{const it=[...document.querySelectorAll('ytd-account-item-renderer')];
 return it.map(e=>{const t=(e.innerText||'').trim().replace(/\s+/g,' '); const h=(t.match(/@\S+/)||[null])[0]; return {t:t.slice(0,60), h:h, sel:!!((e.data||{}).isSelected)};});})()"""

JOIN_JS = r"""
const want = %s;
const tpl = (window.__jh||[]).filter(z=>/yta_web\//.test(z.u)&&z.b&&z.h&&z.h.Authorization).slice(-1)[0];
if (!tpl) throw new Error('no yta_web template');
const base = JSON.parse(tpl.b);
const ent = ((base.screenConfig||{}).entity||{}).channelId || null;
if (ent !== want) throw new Error('template channel ' + ent + ' != ' + want);
const spec = %s;
const body = {nodes: spec.map(n=>({key:n.key, value:{query:Object.assign({currency:'KRW', returnDataInNewFormat:true, limitedToBatchedData:false}, n.query)}})),
  connectors:[], allowFailureResultNodes:true, context:base.context};
const u = tpl.u.replace(/yta_web\/[a-z_]+/, 'yta_web/join');
const res = await new Promise((ok, no) => { const r = new XMLHttpRequest(); r.open('POST', u);
  for (const [k,v] of Object.entries(tpl.h)) r.setRequestHeader(k, v);
  r.onload = () => ok({st:r.status, t:r.responseText}); r.onerror = () => no('xhr error'); r.send(JSON.stringify(body)); });
return res;
"""


class Stop(Exception):
    pass


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def short(v, n=300):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s[:n]


# ---------------- 다른 도구 ----------------
def others_running():
    r = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True)
    me = os.getpid()
    out = []
    for ln in r.stdout.splitlines():
        ln = ln.strip()
        try:
            pid = int(ln.split(None, 1)[0])
        except Exception:
            continue
        if pid == me or 'python' not in ln.lower() or not re.search(r'_sf\.py\b', ln):
            continue
        if any(k in ln for k in NOT_STUDIO):
            continue
        out.append(ln[:160])
    return out


def wait_others(max_s=3600):
    oth = others_running()
    t0 = time.time()
    while oth:
        if time.time() - t0 > max_s:
            raise Stop('다른 스튜디오 도구가 %d분 넘게 돎 — 채널 전환 안 함 %s' % (max_s // 60, short(oth)))
        log('다른 스튜디오 도구가 돎 — 끝날 때까지 기다림', short(oth))
        time.sleep(30)
        oth = others_running()


# ---------------- 창·JS ----------------
def W():
    wid = sf._reg().get(KEY)
    if not wid or not sf.window_alive(wid):
        raise Stop('도구 창 없음')
    return 'wid:%d' % int(wid)


def x(expr):
    return sf.ev(W(), '(%s, (%s))' % (VIS_SHIM, expr))


def f(body):
    return sf.fn(W(), VIS_SHIM + ';' + body)


def q(expr):
    try:
        return x(expr)
    except Stop:
        raise
    except Exception as e:
        return {'__err': str(e)[:300]}


def open_window(url):
    # 업로드 도구와 같은 방식: Veo(vrun)가 _flow.lock 을 쥐고 있으면 비는 틈에 잠깐 잡고 창을 연다
    t0 = time.time()
    while os.path.isdir(FLOW_LOCK) and time.time() - t0 < 600:
        time.sleep(2)
    got = False
    try:
        os.mkdir(FLOW_LOCK)
        open(FLOW_LOCK + '/owner.txt', 'w', encoding='utf-8').write(KEY + ' open %s\n' % time.strftime('%F %T'))
        got = True
    except FileExistsError:
        pass
    try:
        wid = sf.tool_window(KEY, url, bounds=BOUNDS)
    finally:
        if got:
            shutil.rmtree(FLOW_LOCK, ignore_errors=True)
    log('도구 창', wid, '| 앞 앱', str(sf._front_app().bundleIdentifier()))
    return wid


def close_window():
    try:
        f(NO_LEAVE + ' return 1;')
    except Exception:
        pass
    return sf.close_tool(KEY)


def nav(url, sec=45):
    try:
        f(NO_LEAVE + ' window.__old=1; return 1;')
    except Stop:
        raise
    except Exception:
        pass
    sf.nav(W(), url)
    t0 = time.time()
    while time.time() - t0 < sec:
        time.sleep(0.6)
        r = q("window.__old?'old':document.readyState")
        if r in ('interactive', 'complete'):
            return True
    raise Stop('새 페이지가 안 열림: %s' % url[:120])


def wait_state(sec=40):
    st = {}
    t0 = time.time()
    while time.time() - t0 < sec:
        st = q(STATE)
        if isinstance(st, dict) and 'accounts.google' in (st.get('host') or ''):
            raise Stop('사용자 필요: 구글 로그인 화면(accounts.google.com)')
        if isinstance(st, dict) and st.get('ready') == 'complete' and (st.get('ch') or st.get('denied')):
            return st
        time.sleep(1)
    return st


def ok_state(st, ch):
    return isinstance(st, dict) and st.get('host') == 'studio.youtube.com' and st.get('ch') == ch and not st.get('denied')


# ---------------- 채널 전환 ----------------
def switcher_list(next_url=None):
    u = 'https://www.youtube.com/channel_switcher' + ('?next=' + urllib.parse.quote(next_url, safe='') if next_url else '')
    nav(u)
    if 'accounts.google' in str(q('location.host')):
        raise Stop('사용자 필요: 구글 로그인 화면')
    t0 = time.time()
    while time.time() - t0 < 40:
        if q("document.querySelectorAll('ytd-account-item-renderer').length>0") is True:
            break
        time.sleep(1)
    time.sleep(1.5)
    r = q(SW_LIST)
    return r if isinstance(r, list) else []


def switch_to(ch, handle, dest):
    """channel_switcher 에서 handle 항목을 눌러 ch 로 전환하고 dest 가 그 채널로 열릴 때까지. 돌려주는 값 = STATE"""
    wait_others()
    items = switcher_list(dest)
    if not any((it.get('h') or '').lower() == handle.lower() for it in items):
        raise Stop('전환 목록에 %s 없음 (%s)' % (handle, short([it.get('t') for it in items], 400)))
    f('window.__old=1; return 1;')
    r = f(PICK % json.dumps(handle, ensure_ascii=False))
    log('전환 누름', short(r, 200))
    if not (isinstance(r, dict) and r.get('clicked')):
        raise Stop('전환 목록에서 %s 를 하나로 못 고름 %s' % (handle, short(r, 400)))
    t0 = time.time()
    while time.time() - t0 < 25:
        time.sleep(1)
        u = q("window.__old?null:location.href")
        if isinstance(u, str) and u.startswith('https://studio.youtube.com/'):
            break
    st = wait_state(30)
    t1 = time.time()
    while not ok_state(st, ch) and time.time() - t1 < 45:
        # 전환이 늦게 반영되면(10-24 메모: 10~15초) 같은 주소를 4초 간격으로 다시 연다 — 두 번째 클릭은 안 함
        time.sleep(4)
        nav(dest)
        st = wait_state(30)
    return st


def ensure_channel(ch, handle):
    dest = 'https://studio.youtube.com/channel/%s/analytics/tab-overview/period-default' % ch
    nav(dest)
    st = wait_state(40)
    if ok_state(st, ch):
        return st
    log('세션이 다른 채널 — 전환', ch, handle, short(st, 160))
    st = switch_to(ch, handle, dest)
    if ok_state(st, ch):
        return st
    # 같은 탭이 옛 채널을 기억하는 경우(10-24 메모) — 창을 새로 열어 한 번 더 본다
    log('전환 뒤에도 채널이 다름 — 창을 새로 열어 다시 봄', short(st, 160))
    close_window()
    time.sleep(1)
    open_window(dest)
    st = wait_state(40)
    if ok_state(st, ch):
        return st
    raise Stop('채널 전환 실패(분석 화면 CHANNEL_ID=%s)' % (st or {}).get('ch'))


def discover(ch):
    """핸들을 모르는 채널: 전환 목록에서 아는 핸들이 아닌 항목을 하나씩 눌러 CHANNEL_ID 로 찾는다. 없으면 None"""
    known = {(h or '').lower() for _, h in CHANNELS.values() if h}
    items = switcher_list()
    cands = [it['h'] for it in items if it.get('h') and it['h'].lower() not in known]
    log('핸들 모름', ch, '— 모르는 항목', cands)
    for h in cands:
        dest = 'https://studio.youtube.com/channel/%s/analytics/tab-overview/period-default' % ch
        try:
            st = switch_to(ch, h, dest)
        except Stop as e:
            log('  ', h, '실패', str(e)[:120])
            continue
        if ok_state(st, ch):
            return h
    return None


# ---------------- 내부 데이터 ----------------
def capture_template(ch):
    """화면이 부르는 yta_web 요청(헤더·context)을 가로챔 — screenConfig.entity.channelId 가 ch 인 것"""
    q(HOOK)
    test = ("(()=>{const J=(window.__jh||[]).filter(z=>/yta_web\\//.test(z.u)&&z.b&&z.h&&z.h.Authorization);"
            "for(const z of J.slice().reverse()){try{const b=JSON.parse(z.b); const e=((b.screenConfig||{}).entity||{}).channelId; if(e) return e;}catch(e){}}"
            "return null;})()")
    for tab in ('tab-content', 'tab-overview', 'tab-build_audience'):
        path = '/channel/%s/analytics/%s/period-default' % (ch, tab)
        f("history.pushState({},'',%s); window.dispatchEvent(new PopStateEvent('popstate',{state:{}})); return 1" % json.dumps(path))
        t0 = time.time()
        while time.time() - t0 < 25:
            time.sleep(1)
            e = q(test)
            if e == ch:
                return True
            if isinstance(e, str) and e != ch:
                raise Stop('가로챈 요청의 채널이 다름 %s' % e)
    raise Stop('화면 요청(yta_web)을 못 가로챔')


def read_period():
    """화면 머리글 'YYYY. M. D. ~ YYYY. M. D.' + '지난 28일' -> ('YYYY-MM-DD', 'YYYY-MM-DD') 또는 None"""
    t0 = time.time()
    while time.time() - t0 < 15:
        t = q("(document.body&&document.body.innerText||'').slice(0,4000)")
        if isinstance(t, str):
            m = re.search(r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*~\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*\n?\s*지난 28일', t)
            if m:
                a = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                b = datetime.date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
                return a.isoformat(), b.isoformat()
        time.sleep(1)
    return None


def period_fallback():
    try:
        from zoneinfo import ZoneInfo
        today = datetime.datetime.now(ZoneInfo('America/Los_Angeles')).date()
    except Exception:
        today = (datetime.datetime.utcnow() - datetime.timedelta(hours=8)).date()
    b = today - datetime.timedelta(days=1)
    a = b - datetime.timedelta(days=27)
    return a.isoformat(), b.isoformat()


def did(s):
    return int(s.replace('-', ''))


def join(ch, nodes, timeout=120):
    res = sf.aw(W(), VIS_SHIM + ';' + JOIN_JS % (json.dumps(ch), json.dumps(nodes, ensure_ascii=False)), timeout=timeout)
    if not isinstance(res, dict) or res.get('st') != 200:
        raise Stop('join HTTP %s %s' % ((res or {}).get('st'), short((res or {}).get('t', ''), 300)))
    return json.loads(res['t'])


def node(key, ch, dims, mets, a, b, orders=None, n=200):
    return {'key': key, 'query': {'dimensions': [{'type': d} for d in dims], 'metrics': [{'type': m} for m in mets],
                                  'restricts': [{'dimension': {'type': 'USER'}, 'inValues': [ch]}], 'orders': orders or [],
                                  'timeRange': {'dateIdRange': {'inclusiveStart': did(a), 'exclusiveEnd': end_excl(b)}},
                                  'limit': {'pageSize': n, 'pageOffset': 0}}}


def end_excl(b):
    d = datetime.date.fromisoformat(b) + datetime.timedelta(days=1)
    return int(d.strftime('%Y%m%d'))


def table(v):
    """resultTable -> (rows[{차원: 값, 측정: 값 또는 None}], 이상 표시들)"""
    rt = v.get('resultTable')
    if rt is None:
        return None, ['ERR ' + short(v, 200)]
    dims = []
    for dc in rt.get('dimensionColumns', []):
        vals = None
        for k in ('strings', 'enumValues', 'dateIds', 'values', 'ints', 'timestamps', 'offsets'):
            if isinstance(dc.get(k), dict):
                vals = dc[k].get('values', [])
                break
        dims.append((dc['dimension']['type'], vals or []))
    mets = {}
    anom = [a.get('value', {}).get('type') for a in rt.get('anomalyContext', [])]
    for mc in rt.get('metricColumns', []):
        vals, und = None, set(mc.get('undefinedValueIndices') or [])
        for k in ('percentages', 'counts', 'milliseconds', 'values', 'doubles', 'ratios'):
            if isinstance(mc.get(k), dict):
                vals = mc[k].get('values', [])
                und |= set(mc[k].get('undefinedValueIndices') or [])
                break
        mets[mc['metric']['type']] = (vals or [], und)
        if mc.get('columnAnomalies'):
            anom.append(mc['metric']['type'] + ':' + short(mc['columnAnomalies'], 80))
    n = max([len(d[1]) for d in dims] + [len(m[0]) for m in mets.values()] + [0])
    rows = []
    for i in range(n):
        row = {d: (vals[i] if i < len(vals) else None) for d, vals in dims}
        for m, (vals, und) in mets.items():
            row[m] = None if (i in und or i >= len(vals)) else vals[i]
        rows.append(row)
    return rows, anom


def _i(v):
    return None if v is None else int(v)


def _f(v, nd=2):
    return None if v is None else round(float(v), nd)


def _sec(ms):
    return None if ms is None else round(float(ms) / 1000.0, 3)


def read_channel(ch, a, b):
    nodes = [node('TOT', ch, [], M_TOTAL, a, b, n=10),
             node('VID', ch, ['VIDEO'], M_VIDEO, a, b, orders=[{'metric': {'type': 'EXTERNAL_VIEWS'}, 'direction': 'ANALYTICS_ORDER_DIRECTION_DESC'}], n=200)]
    nodes += [node('TS__' + m, ch, ['TRAFFIC_SOURCE_TYPE'], [m], a, b, n=100) for m in M_TRAFFIC]
    d = join(ch, nodes)
    res = {r['key']: r.get('value', {}) for r in d.get('results', [])}
    notes = []

    rows, an = table(res.get('TOT', {}))
    if not rows:
        raise Stop('채널 합계 없음 %s' % short(an))
    notes += ['TOT:' + x_ for x_ in an]
    t = rows[0]
    imp = _i(t.get('VIDEO_THUMBNAIL_IMPRESSIONS'))
    total = {'impressions': imp, 'ctr': _f(t.get('VIDEO_THUMBNAIL_IMPRESSIONS_VTR')) if imp else None,
             'views': _i(t.get('EXTERNAL_VIEWS')), 'avd_sec': _sec(t.get('AVERAGE_WATCH_TIME')),
             'avp': _f(t.get('AVERAGE_WATCH_PERCENTAGE')),
             'watch_hours': None if t.get('EXTERNAL_WATCH_TIME') is None else round(float(t['EXTERNAL_WATCH_TIME']) / 3600000.0, 3),
             'subs_net': _i(t.get('SUBSCRIBERS_NET_CHANGE'))}

    videos = []
    rows, an = table(res.get('VID', {}))
    notes += ['VID:' + x_ for x_ in an]
    for r in rows or []:
        vi = _i(r.get('VIDEO_THUMBNAIL_IMPRESSIONS'))
        sfi = r.get('SHORTS_FEED_IMPRESSIONS')
        videos.append({'id': r.get('VIDEO'), 'impressions': vi,
                       'ctr': _f(r.get('VIDEO_THUMBNAIL_IMPRESSIONS_VTR')) if vi else None,
                       'views': _i(r.get('EXTERNAL_VIEWS')), 'avd_sec': _sec(r.get('AVERAGE_WATCH_TIME')),
                       'avp': _f(r.get('AVERAGE_WATCH_PERCENTAGE')),
                       'shorts_kept_pct': _f(r.get('SHORTS_FEED_IMPRESSIONS_VTR')) if (sfi or 0) > 0 else None})

    ts = {}
    for m in M_TRAFFIC:
        rows, an = table(res.get('TS__' + m, {}))
        notes += ['TS_%s:%s' % (m, x_) for x_ in an]
        for r in rows or []:
            k = r.get('TRAFFIC_SOURCE_TYPE')
            if k is not None:
                ts.setdefault(k, {})[m] = r.get(m)
    traffic = []
    for k, v in ts.items():
        ti = _i(v.get('VIDEO_THUMBNAIL_IMPRESSIONS'))
        traffic.append({'key': k, 'label': TS_LABEL.get(k, k), 'impressions': ti,
                        'ctr': _f(v.get('VIDEO_THUMBNAIL_IMPRESSIONS_VTR')) if ti else None,
                        'views': _i(v.get('EXTERNAL_VIEWS'))})
    traffic.sort(key=lambda r: (-(r['views'] or 0), -(r['impressions'] or 0)))
    return total, traffic, videos, [n_ for n_ in notes if n_]


# ---------------- 되돌리기 ----------------
def restore_home():
    """기본 채널을 '@논스킵'으로(11-07 메모: next 는 논스킵 스튜디오 주소로 해야 반영됨) — 분석 화면 CHANNEL_ID 와 전환 목록으로 확인"""
    home = 'https://studio.youtube.com/channel/%s' % HOME_CH
    nav('https://studio.youtube.com/')
    st = wait_state(40)
    if not ok_state(st, HOME_CH):
        log('기본 채널 되돌림 — 지금', short(st, 160))
        st = switch_to(HOME_CH, HOME_HANDLE, home)
        nav('https://studio.youtube.com/')
        st = wait_state(40)
    items = switcher_list()
    sel = [it.get('h') for it in items if it.get('sel')]
    ok = ok_state(st, HOME_CH)
    log('되돌린 뒤: 스튜디오 CHANNEL_ID', (st or {}).get('ch'), '| 전환 목록 선택', sel, 'OK' if ok else 'BAD')
    return ok


# ---------------- 실행 ----------------
def main(out, chans):
    t_start = time.time()
    names = {c: CHANNELS.get(c, (c, None))[0] for c in chans}
    result = {c: {'name': names[c], 'ok': False, 'err': None, 'total': None, 'traffic': [], 'videos': []} for c in chans}
    period = None
    wait_others()
    order = [c for c in chans if c != HOME_CH] + ([HOME_CH] if HOME_CH in chans else [])   # 논스킵을 맨 끝에 → 되돌림 전환 1번 아낌
    open_window('https://studio.youtube.com/')
    restored = None
    try:
        for ch in order:
            name, handle = CHANNELS.get(ch, (ch, None))
            try:
                if not handle:
                    if ch in OTHER_ACCOUNT:
                        items = switcher_list()
                        unknown = [it['h'] for it in items if it.get('h') and it['h'].lower() not in
                                   {(h or '').lower() for _, h in CHANNELS.values() if h}]
                        if not unknown:
                            result[ch]['err'] = '다른 계정'
                            log(ch, name, '— 전환 목록에 없음(다른 계정)', [it.get('t') for it in items])
                            continue
                    handle = discover(ch)
                    if not handle:
                        result[ch]['err'] = '다른 계정' if ch in OTHER_ACCOUNT else '전환 목록에 없음'
                        continue
                st = ensure_channel(ch, handle)
                result[ch]['name'] = st.get('name') or name
                capture_template(ch)
                if period is None:
                    period = read_period()
                    if period:
                        log('기간(화면 머리글, PT)', period)
                    else:
                        period = period_fallback()
                        log('화면 머리글에서 기간을 못 읽음 — 계산값', period)
                else:
                    p2 = read_period()
                    if p2 and p2 != period:
                        log('!', ch, '화면 기간이 다름', p2, '— 첫 채널 기간', period, '으로 읽음')
                total, traffic, videos, notes = read_channel(ch, *period)
                result[ch].update(ok=True, err=None, total=total, traffic=traffic, videos=videos)
                log('%s %s 노출 %s CTR %s 조회 %s | 영상 %d | 소스 %d %s' % (ch, result[ch]['name'], total['impressions'], total['ctr'],
                                                                        total['views'], len(videos), len(traffic), ('| ' + short(notes, 200)) if notes else ''))
            except Stop as e:
                result[ch]['err'] = str(e)[:300]
                log('!', ch, name, str(e)[:300])
            except Exception as e:
                result[ch]['err'] = ('%s: %s' % (type(e).__name__, e))[:300]
                log('!', ch, name, result[ch]['err'])
    finally:
        try:
            wait_others()
            restored = restore_home()
        except Exception as e:
            log('! 기본 채널 되돌림 실패', str(e)[:300])
            restored = False
        if os.environ.get('SF_KEEP') != '1':
            log('창 닫기', close_window())
    p = period or period_fallback()
    data = {'at': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M+09:00'), 'source': 'studio yta_web/join',
            'period': {'label': '지난 28일', 'start': p[0], 'end': p[1], 'tz': 'PT'}, 'channels': result}
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + '.tmp'
    json.dump(data, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.replace(tmp, out)
    log('저장', out, '| 성공 %d/%d' % (sum(1 for v in result.values() if v['ok']), len(result)),
        '| 논스킵 되돌림', 'OK' if restored else 'BAD', '| %.0f초' % (time.time() - t_start))
    return data


if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0)
    main(sys.argv[1], sys.argv[2:] or DEFAULT)
