#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学习通轻量监控脚本（0 token 轮询）
- 上课时段每 60 秒查询一次各课程作业列表（纯 HTTP，不调用 AI）
- 发现新发布的未交作业/随堂练习时：
  1) 写 alert.json 供 WorkBuddy 自动化领取处理
  2) 发送 macOS 系统通知
- 凭证过期时尝试自动重新登录，失败则系统通知提醒
"""
import json, os, re, sys, time, base64, subprocess, traceback, fcntl
from datetime import datetime, timedelta
import requests
from Crypto.Cipher import AES

BASE = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.path.join(BASE, 'cookies.json')
COURSES_FILE = os.path.join(BASE, 'courses.json')
STATE_FILE   = os.path.join(BASE, 'state.json')
ALERT_FILE   = os.path.join(BASE, 'alert.json')
LOG_FILE     = os.path.join(BASE, 'watcher.log')
# 凭证从本地 cx-credentials.json 读取（该文件不入库，见 credentials.example.json）
_cred = json.load(open(os.path.join(BASE, 'cx-credentials.json'))) if os.path.exists(os.path.join(BASE, 'cx-credentials.json')) else {}
USERNAME = os.environ.get('CX_USERNAME', _cred.get('username', ''))
PASSWORD = os.environ.get('CX_PASSWORD', _cred.get('password', ''))
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
# WorkBuddy 自动化数据库：发现告警时把调度器的 next_run_at 拨到当下，立即唤醒 AI 处理
WB_DB = os.path.expanduser('~/.workbuddy/workbuddy.db')
DISPATCHER_ID = '39be7133-76fe-4ed2-a02a-3b8cb3b4f244'

# 上课时段（周一~周五）：随堂练习只在这些时段发布，密集轮询
# 上午全年固定；下午按校历作息分两档（雁塔校区）：
#   10月1日~次年4月30日：7~8节 14:00-15:50，9~10节 16:00-17:50
#   5月1日~9月30日：    7~8节 14:30-16:20，9~10节 16:30-18:20
MORNING_SLOTS = [(8,0,9,50), (10,10,12,0)]
AFTERNOON_WINTER = [(14,0,15,50), (16,0,17,50)]
AFTERNOON_SUMMER = [(14,30,16,20), (16,30,18,20)]
FAST_INTERVAL = 60        # 上课时段轮询间隔（秒）
SLOW_INTERVAL = 600       # 非上课时段轮询间隔
NIGHT_SKIP = (0, 7*30)    # 0:00~7:30 不轮询

def afternoon_slots(now):
    # 10月~12月用冬令；1~4月用冬令；5~9月用夏令
    return AFTERNOON_WINTER if now.month in (1,2,3,4,10,11,12) else AFTERNOON_SUMMER

def class_slots(now):
    return MORNING_SLOTS + afternoon_slots(now)

def log(msg):
    line = f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def notify(title, msg):
    try:
        subprocess.run(['osascript', '-e',
            f'display notification "{msg}" with title "{title}" sound name "Glass"'],
            timeout=10)
    except Exception as e:
        log(f'notify failed: {e}')

def in_class(now):
    w = now.weekday()  # 5=周六 6=周日
    if w == 5:  # 周六无课（大课表）
        return False
    m = now.hour*60 + now.minute
    if w == 6:  # 周日仅 3~4 节金属塑性加工工艺学
        return 10*60+10 <= m <= 12*60
    for h1,m1,h2,m2 in class_slots(now):
        if h1*60+m1 <= m <= h2*60+m2:
            return True
    return False

def next_wake(now):
    m = now.hour*60 + now.minute
    w = now.weekday()
    if w == 5:  # 周六无课，睡到明天
        return 600
    if w == 6:  # 周日仅上午 3~4 节
        a, b = 10*60+10, 12*60
        if m < a: return a - m
        if m < b: return 1
        return 600
    for h1,m1,h2,m2 in class_slots(now):
        if m < h1*60+m1:
            return max(1, h1*60+m1 - m)
    return 5

def make_session(cookies):
    s = requests.Session()
    for k, v in cookies.items():
        s.cookies.set(k, v, domain='.chaoxing.com')
    s.headers.update({'User-Agent': UA, 'Referer': 'https://mooc1.chaoxing.com/'})
    return s

def page_ok(html):
    return '作业列表' in html or 'aria-label' in html and ('未交' in html or '已' in html or '批阅' in html)

def aes_encrypt(plain: str) -> str:
    key = b'u2oh6Vu^HWe4_AES'
    data = plain.encode()
    pad = 16 - len(data) % 16
    data += b'\x00' * pad
    cipher = AES.new(key, AES.MODE_CBC, key)
    return base64.b64encode(cipher.encrypt(data)).decode()

def relogin(s):
    """凭证失效时用账号密码重新登录（超星 fanyalogin 接口）"""
    try:
        r = s.post('https://passport2.chaoxing.com/fanyalogin',
            data={'fid': '-1', 'uname': USERNAME, 'password': aes_encrypt(PASSWORD),
                  'refer': 'https://i.chaoxing.com', 't': 'true',
                  'forbidotherlogin': '0', 'doublelogin': '1'},
            timeout=15)
        j = r.json()
        if j.get('status'):
            log('relogin ok')
            # 保存新凭证
            fresh = {c.name: c.value for c in s.cookies}
            if fresh:
                json.dump(fresh, open(COOKIES_FILE, 'w'))
            return True
        log(f'relogin failed: {j}')
    except Exception as e:
        log(f'relogin error: {e}')
    return False

def parse_items(html):
    """解析作业条目：[(name, status, workId, answerId)]"""
    items = []
    for m in re.finditer(r'(?:href|data)="([^"]*workId=(\d+)[^"]*answerId=(\d+)[^"]*)"[^>]*aria-label="([^";]+?)\s*;\s*([^"]+)"', html):
        href, wid, aid, name, status = m.group(1), m.group(2), m.group(3), m.group(4).strip(), m.group(5).strip()
        remain = re.search(r'剩余[0-9]+小时[0-9]+分钟', html[m.end():m.end()+800])
        items.append({'name': name, 'status': status, 'workId': wid,
                      'answerId': aid, 'taskUrl': href.split('&amp;').join(['&']) if '&amp;' in href else href,
                      'remain': remain.group(0) if remain else ''})
    return items

def load_json(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default

def wake_dispatcher():
    """把告警调度器的 next_run_at 拨到当下，立即触发 AI 处理"""
    try:
        import time as _t
        subprocess.run(['sqlite3', WB_DB,
            f"update automations set next_run_at={int(_t.time()*1000)} where id='{DISPATCHER_ID}'"],
            timeout=10, capture_output=True)
        log('dispatcher woken via DB')
    except Exception as e:
        log(f'wake dispatcher failed: {e}')

def main():
    courses = load_json(COURSES_FILE, [])
    state = load_json(STATE_FILE, {'seen': {}})
    cookies = load_json(COOKIES_FILE, {})
    s = make_session(cookies)
    log(f'watcher started, {len(courses)} courses')

    while True:
        now = datetime.now()
        if (now.hour*60+now.minute) < NIGHT_SKIP[1]:
            time.sleep(max(1, min(next_wake(now), 30))*60)
            continue

        alerts = []
        ok_all = True
        for c in courses:
            try:
                r = s.get(c['url'], timeout=15)
                if r.status_code != 200 or len(r.text) < 1000:
                    ok_all = False; continue
                if '作业列表' not in r.text and 'aria-label' not in r.text:
                    # 可能凭证过期，尝试重新登录一次
                    log(f"{c['name']}: page abnormal, trying relogin")
                    if relogin(s):
                        json.dump(dict(s.cookies.items()) if hasattr(s.cookies,'items') else {ck.name: ck.value for ck in s.cookies}, open(COOKIES_FILE,'w'))
                        r = s.get(c['url'], timeout=15)
                        if 'aria-label' not in r.text:
                            ok_all = False
                            notify('学习通监控', f"{c['name']} 页面异常，且重新登录后仍失败，请检查")
                            continue
                    else:
                        ok_all = False
                        notify('学习通监控', '登录凭证已过期且自动登录失败，请在 WorkBuddy 里让助手刷新')
                        time.sleep(SLOW_INTERVAL)
                        break
                for it in parse_items(r.text):
                    key = f"{c['courseId']}_{it['workId']}"
                    if key not in state['seen']:
                        state['seen'][key] = {'name': it['name'], 'status': it['status'], 'course': c['name'], 'ts': now.isoformat()}
                        if it['status'] in ('未交',):
                            alerts.append({**it, 'course': c['name'], 'courseId': c['courseId'],
                                           'classId': c['classId'], 'url': c['url']})
                            log(f"NEW: {c['name']} - {it['name']} [{it['status']}] {it['remain']}")
                        else:
                            log(f"new-but-done: {c['name']} - {it['name']} [{it['status']}]")
            except Exception as e:
                ok_all = False
                log(f"{c['name']}: error {e}")
                log(traceback.format_exc())

        json.dump(state, open(STATE_FILE, 'w'), ensure_ascii=False, indent=1)

        if alerts:
            json.dump({'ts': now.isoformat(), 'items': alerts}, open(ALERT_FILE, 'w'), ensure_ascii=False, indent=1)
            log(f'alert written: ' + '；'.join(f"{a['course']}·{a['name']}" for a in alerts))
            wake_dispatcher()

        interval = FAST_INTERVAL if in_class(now) else SLOW_INTERVAL
        time.sleep(interval)

if __name__ == '__main__':
    main()
