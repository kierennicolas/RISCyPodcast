#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║   Riscy-PodMan  v1.1                                             ║
║   Terminal podcast manager for RISC OS & Linux                   ║
║   Standard library only — no pip packages required               ║
╚══════════════════════════════════════════════════════════════════╝

Usage:
  python3 riscypodman.py

On RISC OS:
  python3 riscypodman/py          (if using RISC OS filetype)
  or set file type to &FEB and double-click

Controls in every menu:
  Type a number and press Enter to select.
  Type a letter command and press Enter.
  Press Enter alone to go back / cancel.
"""

import os
import sys
import json
import time
import datetime
import hashlib
import re
import shutil
import socket

# ─── Python 3 guard ───────────────────────────────────────────────────────────
if sys.version_info < (3, 4):
    sys.exit("ERROR: Python 3.4 or later is required.")

import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET

# Optional SSL availability check
try:
    import ssl
    _HAS_SSL = True
except ImportError:
    _HAS_SSL = False

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PLATFORM DETECTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

IS_RISCOS = sys.platform.lower().startswith('riscos')
IS_POSIX  = (os.name == 'posix') and not IS_RISCOS

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONSTANTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VERSION              = "1.2"
APP_NAME             = "PodcastManager"
SCREEN_W             = 78

# Separator lines (ASCII-safe for RISC OS VDU)
SEP_DOUBLE           = "=" * SCREEN_W
SEP_SINGLE           = "-" * SCREEN_W

# HTTP settings (overrideable from settings menu)
DEFAULT_RATE_DELAY   = 2.0   # seconds between requests to same host
DEFAULT_TIMEOUT      = 30    # HTTP connect/read timeout
DEFAULT_MAX_EP       = 100   # max episodes stored per feed
CHUNK_SIZE           = 8192  # download chunk bytes

USER_AGENT           = ("PodcastManager/{} Python/{}.{}"
                        .format(VERSION, *sys.version_info[:2]))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ANSI COLOURS  (disabled automatically on RISC OS or non-tty)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _tty_supports_colour():
    if IS_RISCOS:
        return False
    return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()

_COLOUR = _tty_supports_colour()

def _c(code):
    return code if _COLOUR else ''

RS  = _c('\033[0m')     # Reset
BD  = _c('\033[1m')     # Bold
DM  = _c('\033[2m')     # Dim
RD  = _c('\033[91m')    # Red
GN  = _c('\033[92m')    # Green
YW  = _c('\033[93m')    # Yellow
BL  = _c('\033[94m')    # Blue
MG  = _c('\033[95m')    # Magenta
CY  = _c('\033[96m')    # Cyan

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PLATFORM-AWARE PATHS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _config_dir():
    """
    Return the directory where config + metadata are stored.

    RISC OS: <Choices$Write>.PodcastManager  (or beside the script)
    Linux:   ~/.config/podcastmanager
    """
    if IS_RISCOS:
        choices = os.environ.get('Choices$Write', '')
        if choices:
            return os.path.join(choices, APP_NAME)
        # Fallback — directory called "Config" beside the script
        return os.path.join(
            os.path.dirname(os.path.abspath(sys.argv[0])), 'Config')
    else:
        xdg = os.environ.get('XDG_CONFIG_HOME', '')
        base = xdg if xdg else os.path.join(os.path.expanduser('~'), '.config')
        return os.path.join(base, 'podcastmanager')


def _default_download_dir():
    """
    Return the default podcast download root.

    RISC OS: <Home$Dir>.Podcasts  (or beside the script)
    Linux:   ~/Podcasts
    """
    if IS_RISCOS:
        home = os.environ.get('Home$Dir', '')
        if not home:
            home = os.getcwd()
        return os.path.join(home, 'Podcasts')
    else:
        return os.path.join(os.path.expanduser('~'), 'Podcasts')


_CONFIG_DIR   = _config_dir()
_CONFIG_FILE  = os.path.join(_CONFIG_DIR, 'config.json')
_FEEDS_FILE   = os.path.join(_CONFIG_DIR, 'feeds.json')
_EPISODES_DIR = os.path.join(_CONFIG_DIR, 'episodes')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FILENAME SANITISATION
#  RISC OS: '.' = directory separator, '#/*@^?' = wildcards — all replaced.
#  Linux:   '/' replaced; other special chars stripped.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def safe_name(s, maxlen=80):
    """Return a filesystem-safe name for both RISC OS and Linux."""
    s = str(s).strip()
    if IS_RISCOS:
        # On RISC OS, '.' is path separator so must be replaced
        s = re.sub(r'[./\\:*?#@^<>|"\'`!\r\n\t]', '-', s)
    else:
        s = re.sub(r'[/\\:*?<>|"\'`!\r\n\t]', '-', s)
    s = re.sub(r'\s+', '-', s)
    s = re.sub(r'-{2,}', '-', s)
    s = s.strip('-')
    return (s[:maxlen] or 'untitled')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SMALL UTILITIES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def clrscr():
    """Clear the terminal screen (cross-platform)."""
    if IS_RISCOS:
        sys.stdout.write('\x0c')   # Form-feed clears RISC OS VDU
        sys.stdout.flush()
    else:
        os.system('clear')


def now_iso():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def date_display(iso):
    """'2024-03-15T…' → '15 Mar 2024'."""
    if not iso:
        return 'Unknown'
    try:
        d = datetime.datetime.strptime(iso[:10], '%Y-%m-%d')
        return d.strftime('%d %b %Y')
    except Exception:
        return iso[:10]


def parse_date(s):
    """Try multiple date formats; return ISO string or empty string."""
    if not s:
        return ''
    fmts = [
        '%a, %d %b %Y %H:%M:%S %z',
        '%a, %d %b %Y %H:%M:%S +0000',
        '%a, %d %b %Y %H:%M:%S GMT',
        '%a, %d %b %Y %H:%M:%S -0000',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M:%S+00:00',
        '%Y-%m-%d',
        '%d %b %Y',
    ]
    s2 = s.strip()
    for fmt in fmts:
        try:
            dt = datetime.datetime.strptime(s2, fmt)
            # Strip timezone info for uniform storage
            dt = dt.replace(tzinfo=None)
            return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        except (ValueError, AttributeError):
            pass
    return ''   # Unknown/unparseable date



def parse_retry_after(value, default=60):
    """Parse Retry-After header as seconds or HTTP date."""
    if not value:
        return default
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.datetime.strptime(value, '%a, %d %b %Y %H:%M:%S GMT')
        return max(0, int((dt - datetime.datetime.utcnow()).total_seconds()))
    except (TypeError, ValueError):
        return default


def allowed_remote_url(url):
    """Return True only for http(s) URLs."""
    scheme = urllib.parse.urlparse(url).scheme.lower()
    return scheme in ('http', 'https')


def safe_tmp_path(dest):
    """Return a safe temporary filename for the target platform."""
    suffix = '-tmp' if IS_RISCOS else '.tmp'
    return dest + suffix


def sort_key_pub_date(ep):
    """Sort unknown dates after real dates."""
    return ep.get('pub_date') or ''


def human_size(n):
    """bytes → '12.3 MB' etc."""
    if not n or n < 0:
        return '?'
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return '{:.1f} {}'.format(n, unit)
        n /= 1024.0
    return '{:.1f} TB'.format(n)


def human_dur(secs):
    """seconds → 'H:MM:SS' or 'M:SS'."""
    try:
        secs = int(secs)
    except (TypeError, ValueError):
        return '--:--'
    if secs <= 0:
        return '--:--'
    h, rem = divmod(secs, 3600)
    m, s   = divmod(rem, 60)
    if h:
        return '{}:{:02d}:{:02d}'.format(h, m, s)
    return '{}:{:02d}'.format(m, s)


def trunc(s, n):
    s = str(s)
    return s if len(s) <= n else s[:n - 1] + '>'


def dur_to_secs(s):
    """'HH:MM:SS' or 'MM:SS' or plain seconds → int seconds."""
    if not s:
        return 0
    s = s.strip()
    parts = s.split(':')
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return int(s)
    except (ValueError, TypeError):
        return 0


def strip_html(s):
    """Remove HTML tags and decode common entities."""
    if not s:
        return ''
    s = re.sub(r'<[^>]+>', ' ', s)
    for entity, char in [('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'),
                          ('&quot;', '"'), ('&apos;', "'"), ('&nbsp;', ' '),
                          ('&#160;', ' ')]:
        s = s.replace(entity, char)
    s = re.sub(r'&#\d+;', '', s)
    s = re.sub(r'[ \t]+', ' ', s)
    return s.strip()


def word_wrap(text, width, indent='  '):
    """Wrap text to width, yielding lines."""
    for paragraph in text.splitlines():
        paragraph = paragraph.strip()
        if not paragraph:
            yield ''
            continue
        words = paragraph.split()
        line = indent
        for w in words:
            candidate = (line + ' ' + w) if line.strip() else (indent + w)
            if len(candidate) > width:
                if line.strip():
                    yield line
                line = indent + w
            else:
                line = candidate
        if line.strip():
            yield line


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PRINT HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def hdr(title, sub=''):
    """Print a boxed header."""
    print()
    print(BL + BD + SEP_DOUBLE + RS)
    pad = max(0, (SCREEN_W - len(title)) // 2)
    print(BL + BD + ' ' * pad + title + RS)
    if sub:
        pad2 = max(0, (SCREEN_W - len(sub)) // 2)
        print(DM + ' ' * pad2 + sub + RS)
    print(BL + BD + SEP_DOUBLE + RS)


def sec(title):
    """Print a section separator."""
    print()
    print(CY + BD + '  ' + title + RS)
    print(CY + SEP_SINGLE + RS)


def ok(msg):
    tag = GN + '[OK]' + RS if _COLOUR else '[OK]'
    print('  {} {}'.format(tag, msg))


def err(msg):
    tag = RD + '[ERR]' + RS if _COLOUR else '[ERR]'
    print('  {} {}'.format(tag, msg))


def info(msg):
    tag = YW + '[..]' + RS if _COLOUR else '[..]'
    print('  {} {}'.format(tag, msg))


def warn(msg):
    tag = YW + '[!!]' + RS if _COLOUR else '[!!]'
    print('  {} {}'.format(tag, msg))


def ask(prompt_text, default=''):
    """Input with optional default shown in brackets."""
    p = BD + prompt_text + RS if _COLOUR else prompt_text
    if default:
        p += ' [{}]'.format(default)
    p += ': '
    try:
        val = input(p).strip()
        return val if val else default
    except (EOFError, KeyboardInterrupt):
        print()
        return default


def confirm(msg, default=True):
    opts = '(Y/n)' if default else '(y/N)'
    v = ask('{} {}'.format(msg, opts))
    if not v:
        return default
    return v.lower().startswith('y')


def pause():
    ask(DM + '  Press Enter to continue' + RS if _COLOUR
        else '  Press Enter to continue')


def progress_bar(done, total, width=36):
    """One-line ASCII progress bar."""
    if total > 0:
        frac   = min(1.0, done / total)
        filled = int(width * frac)
        bar    = '#' * filled + '.' * (width - filled)
        pct    = int(frac * 100)
    else:
        bar = '?' * width
        pct = 0
    return '[{}] {:3d}%  {}/{}'.format(
        bar, pct, human_size(done), human_size(total) if total > 0 else '?')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_DEFAULTS = {
    'download_dir':          _default_download_dir(),
    'rate_limit_delay':      DEFAULT_RATE_DELAY,
    'http_timeout':          DEFAULT_TIMEOUT,
    'max_episodes_per_feed': DEFAULT_MAX_EP,
    'auto_refresh_on_start': True,
}

_cfg = {}


def load_config():
    global _cfg
    _ensure_dirs()
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, 'r', encoding='utf-8') as f:
                _cfg = json.load(f)
        except Exception:
            _cfg = {}
    for k, v in _DEFAULTS.items():
        _cfg.setdefault(k, v)


def save_config():
    _ensure_dirs()
    write_json_atomic(_CONFIG_FILE, _cfg)


def cfg(key):
    return _cfg.get(key, _DEFAULTS.get(key))


def _ensure_dirs():
    for d in (_CONFIG_DIR, _EPISODES_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass



def write_json_atomic(path, data):
    """Write JSON atomically where possible."""
    directory = os.path.dirname(path) or '.'
    base = os.path.basename(path)
    tmp_suffix = '-new' if IS_RISCOS else '.tmp'
    tmp_path = os.path.join(directory, base + tmp_suffix)
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FEED & EPISODE STORAGE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_feeds = {}   # id → feed_dict


def _feed_id(url):
    return hashlib.md5(url.strip().encode('utf-8')).hexdigest()[:12]


def _ep_file(feed_id):
    return os.path.join(_EPISODES_DIR, feed_id + '.json')


def load_feeds():
    global _feeds
    if os.path.exists(_FEEDS_FILE):
        try:
            with open(_FEEDS_FILE, 'r', encoding='utf-8') as f:
                lst = json.load(f)
            _feeds = {fd['id']: fd for fd in lst}
        except Exception:
            _feeds = {}
    else:
        _feeds = {}


def save_feeds():
    write_json_atomic(_FEEDS_FILE, list(_feeds.values()))


def load_episodes(feed_id):
    path = _ep_file(feed_id)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_episodes(feed_id, episodes):
    write_json_atomic(_ep_file(feed_id), episodes)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RATE LIMITER  (per-host, using a simple timestamp dict)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_last_req = {}   # hostname → time.time() of last request


def _rate_wait(url):
    """Sleep if we hit the same host too quickly."""
    host  = urllib.parse.urlparse(url).netloc
    delay = float(cfg('rate_limit_delay'))
    gap   = time.time() - _last_req.get(host, 0)
    if gap < delay:
        sleep_for = delay - gap
        info('Rate limit: waiting {:.1f}s for {}…'.format(sleep_for, host))
        time.sleep(sleep_for)
    _last_req[host] = time.time()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  HTTP GET  (with retry, redirect, 429 handling, rate limiting)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _build_opener():
    """Build an opener that follows redirects and sets headers."""
    opener = urllib.request.build_opener(
        urllib.request.HTTPRedirectHandler(),
        urllib.request.HTTPCookieProcessor(),
    )
    opener.addheaders = [
        ('User-Agent', USER_AGENT),
        ('Accept',     '*/*'),
    ]
    return opener


_opener = _build_opener()


def http_get(url, max_retries=3):
    """
    Fetch url, return (response_object, error_string).
    On 429 respects Retry-After header.
    Handles redirects up to 5 hops manually when needed.
    Returns (None, error) on failure.
    """
    _rate_wait(url)
    timeout = int(cfg('http_timeout'))
    current_url = url

    for attempt in range(max_retries):
        try:
            resp = _opener.open(current_url, timeout=timeout)
            _last_req[urllib.parse.urlparse(current_url).netloc] = time.time()
            return resp, None

        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = parse_retry_after(e.headers.get('Retry-After'), 60)
                warn('HTTP 429 — rate limited by server. Waiting {}s…'.format(retry_after))
                time.sleep(retry_after)
                continue
            if e.code in (301, 302, 303, 307, 308):
                loc = e.headers.get('Location', '')
                if loc:
                    current_url = loc
                    _rate_wait(current_url)
                    continue
            return None, 'HTTP {}: {}'.format(e.code, e.reason)

        except urllib.error.URLError as e:
            reason = str(e.reason)
            if 'SSL' in reason and not _HAS_SSL:
                return None, 'SSL not available. Try an http:// URL if the feed supports it.'
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return None, 'Network error: {}'.format(reason)

        except socket.timeout:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return None, 'Connection timed out'

        except Exception as e:
            return None, str(e)



def http_open_stream(url, max_retries=3):
    """Open a URL for streaming download with the same retry logic as feeds."""
    if not allowed_remote_url(url):
        return None, 'Only http:// and https:// URLs are supported.'

    timeout = int(cfg('http_timeout'))
    current_url = url

    for attempt in range(max_retries):
        _rate_wait(current_url)
        req = urllib.request.Request(current_url)
        req.add_header('User-Agent', USER_AGENT)
        req.add_header('Accept', '*/*')
        try:
            resp = _opener.open(req, timeout=timeout)
            _last_req[urllib.parse.urlparse(current_url).netloc] = time.time()
            return resp, None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = parse_retry_after(e.headers.get('Retry-After'), 60)
                warn('HTTP 429 — rate limited by server. Waiting {}s…'.format(retry_after))
                time.sleep(retry_after)
                continue
            if e.code in (301, 302, 303, 307, 308):
                loc = e.headers.get('Location', '')
                if loc:
                    current_url = urllib.parse.urljoin(current_url, loc)
                    continue
            return None, 'HTTP {}: {}'.format(e.code, e.reason)
        except urllib.error.URLError as e:
            reason = str(e.reason)
            if 'SSL' in reason and not _HAS_SSL:
                return None, 'SSL not available. Try an http:// URL if the feed supports it.'
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return None, 'Network error: {}'.format(reason)
        except socket.timeout:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return None, 'Connection timed out'
        except Exception as e:
            return None, str(e)

    return None, 'Max retries ({}) exceeded'.format(max_retries)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RSS / ATOM PARSING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Common namespaces
_NS = {
    'itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd',
    'content':'http://purl.org/rss/1.0/modules/content/',
    'media':  'http://search.yahoo.com/mrss/',
    'atom':   'http://www.w3.org/2005/Atom',
    'dc':     'http://purl.org/dc/elements/1.1/',
}

_ATOM_NS  = '{http://www.w3.org/2005/Atom}'
_IT_NS    = '{http://www.itunes.com/dtds/podcast-1.0.dtd}'
_DC_NS    = '{http://purl.org/dc/elements/1.1/}'
_MEDIA_NS = '{http://search.yahoo.com/mrss/}'


def _txt(elem, tag):
    """Find direct child <tag> and return its stripped text, or ''."""
    t = elem.find(tag)
    return t.text.strip() if t is not None and t.text else ''


def _itxt(elem, tag):
    """Same but with iTunes namespace prefix."""
    return _txt(elem, _IT_NS + tag)


def _dtxt(elem, tag):
    """Dublin Core namespace."""
    return _txt(elem, _DC_NS + tag)


def _ep_record(ep_id, title, desc, url, ftype, fsize,
               dur_secs, pub_iso):
    """Construct a fresh episode dict."""
    return {
        'id':            ep_id,
        'title':         title or 'Untitled',
        'description':   (desc or '')[:1000],
        'url':           url,
        'file_type':     ftype,
        'file_size':     int(fsize) if fsize else 0,
        'duration_secs': dur_secs,
        'pub_date':      pub_iso,
        'downloaded':    False,
        'download_path': None,
        'listened':      False,
        'listened_date': None,
        'added_date':    now_iso(),
    }


def _parse_rss2(channel, feed_url):
    """Parse RSS 2.0 <channel>. Returns (meta_dict, [episode_dicts])."""

    def g(tag):       return _txt(channel, tag)
    def ig(tag):      return _itxt(channel, tag)

    # Feed image
    img_url = ''
    img_elem = channel.find('image')
    if img_elem is not None:
        img_url = _txt(img_elem, 'url')
    if not img_url:
        it_img = channel.find(_IT_NS + 'image')
        if it_img is not None:
            img_url = it_img.get('href', '')

    meta = {
        'title':       g('title') or 'Untitled Podcast',
        'description': g('description') or ig('summary') or '',
        'website':     g('link') or feed_url,
        'image':       img_url,
        'author':      ig('author') or g('managingEditor') or '',
        'category':    ig('category') or '',
    }

    episodes = []
    for item in channel.findall('item'):

        def i(tag):   return _txt(item, tag)
        def ii(tag):  return _itxt(item, tag)
        def idc(tag): return _dtxt(item, tag)

        # Audio enclosure
        enc = item.find('enclosure')
        if enc is not None:
            enc_url  = enc.get('url', '')
            enc_type = enc.get('type', '')
            try:
                enc_size = int(enc.get('length', 0))
            except (ValueError, TypeError):
                enc_size = 0
        else:
            # Try media:content
            enc_url = enc_type = ''
            enc_size = 0
            for mc in item.findall(_MEDIA_NS + 'content'):
                u = mc.get('url', '')
                t = mc.get('type', '')
                if u and ('audio' in t or 'video' in t or not t):
                    enc_url  = u
                    enc_type = t
                    try:
                        enc_size = int(mc.get('fileSize', 0))
                    except (ValueError, TypeError):
                        enc_size = 0
                    break

        if not enc_url:
            continue   # Skip items without audio

        dur_secs = dur_to_secs(ii('duration'))
        pub_iso  = parse_date(i('pubDate') or idc('date'))
        guid     = i('guid') or enc_url
        ep_id    = hashlib.md5(guid.encode('utf-8')).hexdigest()[:16]
        title    = i('title') or ii('title')
        desc     = ii('summary') or i('description') or ''

        episodes.append(_ep_record(
            ep_id, title, strip_html(desc),
            enc_url, enc_type, enc_size, dur_secs, pub_iso))

    return meta, episodes


def _parse_atom(root, feed_url):
    """Parse Atom <feed>. Returns (meta_dict, [episode_dicts])."""

    def g(tag):
        t = root.find(_ATOM_NS + tag)
        return t.text.strip() if t is not None and t.text else ''

    logo = root.find(_ATOM_NS + 'logo')
    img_url = logo.text.strip() if logo is not None and logo.text else ''

    meta = {
        'title':       g('title') or 'Untitled Podcast',
        'description': g('subtitle') or '',
        'website':     feed_url,
        'image':       img_url,
        'author':      '',
        'category':    '',
    }

    episodes = []
    for entry in root.findall(_ATOM_NS + 'entry'):

        def e(tag):
            t = entry.find(_ATOM_NS + tag)
            return t.text.strip() if t is not None and t.text else ''

        enc_url = enc_type = ''
        enc_size = 0
        for link in entry.findall(_ATOM_NS + 'link'):
            rel  = link.get('rel', '')
            typ  = link.get('type', '')
            if rel == 'enclosure' or 'audio' in typ or 'video' in typ:
                enc_url  = link.get('href', '')
                enc_type = typ
                try:
                    enc_size = int(link.get('length', 0))
                except (ValueError, TypeError):
                    enc_size = 0
                break

        if not enc_url:
            continue

        pub_iso = parse_date(e('published') or e('updated'))
        guid    = e('id') or enc_url
        ep_id   = hashlib.md5(guid.encode('utf-8')).hexdigest()[:16]
        desc    = strip_html(e('summary') or e('content'))

        episodes.append(_ep_record(
            ep_id, e('title'), desc,
            enc_url, enc_type, enc_size, 0, pub_iso))

    return meta, episodes


def parse_feed(data_bytes, feed_url):
    """
    Parse RSS or Atom bytes.
    Returns (meta_dict, [episode_dicts]).
    Raises ValueError on parse failure.
    """
    try:
        root = ET.fromstring(data_bytes)
    except ET.ParseError as e:
        raise ValueError('XML parse error: {}'.format(e))

    root_tag = root.tag.lower()
    if 'atom' in root_tag or root.tag == _ATOM_NS + 'feed':
        return _parse_atom(root, feed_url)

    # RSS 1.0 / 2.0
    channel = root.find('channel') or root
    return _parse_rss2(channel, feed_url)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FEED OPERATIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def add_feed(url):
    """Fetch + parse a new feed URL and store it. Returns True on success."""
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        err('URL must start with http:// or https://')
        return False
    if not allowed_remote_url(url):
        err('Only http:// and https:// feed URLs are supported.')
        return False

    fid = _feed_id(url)
    if fid in _feeds:
        warn('This feed is already in your list.')
        return False

    info('Fetching feed: ' + url)
    resp, errmsg = http_get(url)
    if errmsg:
        err('Could not fetch feed: ' + errmsg)
        return False

    try:
        data = resp.read()
        resp.close()
    except Exception as e:
        err('Read error: ' + str(e))
        return False

    try:
        meta, episodes = parse_feed(data, url)
    except Exception as e:
        err('Parse error: ' + str(e))
        return False

    if not episodes:
        warn('Feed parsed but no audio episodes found — may not be a podcast feed.')

    feed = {
        'id':           fid,
        'url':          url,
        'title':        meta['title'],
        'description':  meta['description'][:500],
        'website':      meta['website'],
        'image':        meta.get('image', ''),
        'author':       meta.get('author', ''),
        'category':     meta.get('category', ''),
        'last_updated': now_iso(),
        'episode_count':len(episodes),
        'new_since_refresh': len(episodes),
    }

    _feeds[fid] = feed
    save_feeds()

    max_ep = int(cfg('max_episodes_per_feed'))
    episodes.sort(key=sort_key_pub_date, reverse=True)
    save_episodes(fid, episodes[:max_ep])

    ok('Added: {} ({} episodes)'.format(feed['title'], len(episodes)))
    return True


def _fetch_and_parse(feed):
    """Internal: re-fetch a feed URL. Returns (meta, episodes) or raises."""
    resp, errmsg = http_get(feed['url'])
    if errmsg:
        raise IOError(errmsg)
    data = resp.read()
    resp.close()
    return parse_feed(data, feed['url'])


def refresh_feed(fid, silent=False):
    """Re-fetch a feed and merge new episodes. Returns True on success."""
    feed = _feeds.get(fid)
    if not feed:
        return False

    if not silent:
        info('Refreshing: ' + feed['title'])

    try:
        meta, new_eps = _fetch_and_parse(feed)
    except Exception as e:
        if not silent:
            err('Refresh failed: ' + str(e))
        return False

    existing = load_episodes(fid)
    existing_by_id = {ep['id']: ep for ep in existing}

    added = 0
    for ep in new_eps:
        if ep['id'] not in existing_by_id:
            existing.insert(0, ep)
            existing_by_id[ep['id']] = ep
            added += 1
        else:
            old_ep = existing_by_id[ep['id']]
            for key in ('title', 'description', 'url', 'file_type', 'file_size',
                        'duration_secs', 'pub_date'):
                if ep.get(key):
                    old_ep[key] = ep[key]

    existing.sort(key=sort_key_pub_date, reverse=True)
    max_ep = int(cfg('max_episodes_per_feed'))
    existing = existing[:max_ep]
    save_episodes(fid, existing)

    # Update feed record
    feed.update({
        'title':              meta['title'],
        'description':        meta['description'][:500],
        'last_updated':       now_iso(),
        'episode_count':      len(existing),
        'new_since_refresh':  added,
    })
    if meta.get('image'):
        feed['image'] = meta['image']
    save_feeds()

    if not silent:
        if added:
            ok('{} new episode(s) found'.format(added))
        else:
            info('No new episodes')
    return True


def refresh_all(silent=False):
    """Refresh every feed in turn."""
    if not _feeds:
        if not silent:
            info('No feeds yet.')
        return

    total_new = 0
    feeds = list(_feeds.values())
    for idx, feed in enumerate(feeds, 1):
        label = trunc(feed['title'], 50)
        if not silent:
            print('  ({}/{}) {}…'.format(idx, len(feeds), label))
        refresh_feed(feed['id'], silent=silent)
        total_new += _feeds[feed['id']].get('new_since_refresh', 0)

    if not silent:
        ok('All feeds refreshed. {} new episode(s) total.'.format(total_new))


def remove_feed(fid):
    """Delete a feed and its episode data."""
    feed = _feeds.pop(fid, None)
    if feed:
        save_feeds()
        ep_path = _ep_file(fid)
        if os.path.exists(ep_path):
            try:
                os.remove(ep_path)
            except Exception:
                pass
        ok('Removed: ' + feed['title'])
        return True
    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EPISODE DOWNLOAD
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _guess_ext(url, mime):
    """Return file extension based on URL path or MIME type."""
    path_ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if path_ext in ('.mp3', '.ogg', '.m4a', '.opus', '.flac', '.wav', '.aac'):
        return path_ext
    mime = (mime or '').lower()
    if 'ogg' in mime:        return '.ogg'
    if 'mp4' in mime or 'aac' in mime: return '.m4a'
    if 'opus' in mime:       return '.opus'
    return '.mp3'


def download_episode(fid, ep_id):
    """Download an episode audio file to the podcast directory."""
    episodes = load_episodes(fid)
    ep = next((e for e in episodes if e['id'] == ep_id), None)
    if not ep:
        err('Episode not found.')
        return False

    if not allowed_remote_url(ep.get('url', '')):
        err('Episode URL must use http:// or https://')
        return False

    # Already have it on disk?
    if ep.get('downloaded') and ep.get('download_path'):
        if os.path.exists(ep['download_path']):
            warn('Already downloaded: ' + ep['download_path'])
            return True

    feed       = _feeds.get(fid, {})
    feed_dir   = os.path.join(cfg('download_dir'),
                              safe_name(feed.get('title', 'Unknown')))
    try:
        os.makedirs(feed_dir, exist_ok=True)
    except Exception as e:
        err('Cannot create folder: ' + str(e))
        return False

    ext      = _guess_ext(ep['url'], ep.get('file_type', ''))
    date_pfx = ((ep.get('pub_date') or '')[:10].replace('-', '') or 'unknown')
    filename = date_pfx + '-' + safe_name(ep['title'], 60) + '-' + ep['id'][:8] + ext
    dest     = os.path.join(feed_dir, filename)
    tmp      = safe_tmp_path(dest)

    # Existing completed file (e.g. metadata said not downloaded)
    if os.path.exists(dest):
        ep['downloaded']    = True
        ep['download_path'] = dest
        save_episodes(fid, episodes)
        ok('File already exists: ' + filename)
        return True

    info('Downloading: ' + trunc(ep['title'], 60))
    print('  To: ' + dest)

    try:
        resp, errmsg = http_open_stream(ep['url'])
        if errmsg:
            err('Download failed: ' + errmsg)
            return False

        total = 0
        try:
            total = int(resp.headers.get('Content-Length', 0))
        except (TypeError, ValueError):
            total = 0

        done       = 0
        start      = time.time()

        with open(tmp, 'wb') as f:
            while True:
                chunk = resp.read(CHUNK_SIZE)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                elapsed = max(0.01, time.time() - start)
                speed   = done / elapsed
                bar     = progress_bar(done, total)
                spd_str = human_size(int(speed)) + '/s'
                line    = '  ' + bar + '  ' + spd_str
                sys.stdout.write('\r' + line[:SCREEN_W])
                sys.stdout.flush()

        sys.stdout.write('\n')
        resp.close()

        shutil.move(tmp, dest)

        ep['downloaded']    = True
        ep['download_path'] = dest
        if total > 0:
            ep['file_size'] = total
        save_episodes(fid, episodes)

        _last_req[urllib.parse.urlparse(ep['url']).netloc] = time.time()
        ok('Download complete — {}'.format(human_size(done)))
        return True

    except KeyboardInterrupt:
        print()
        warn('Download cancelled.')
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
        return False

    except Exception as e:
        print()
        err('Download failed: ' + str(e))
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
        return False

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EPISODE MARKING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def mark_listened(fid, ep_id, state=True):
    episodes = load_episodes(fid)
    changed  = False
    for ep in episodes:
        if ep['id'] == ep_id:
            ep['listened']      = state
            ep['listened_date'] = now_iso() if state else None
            changed = True
            break
    if changed:
        save_episodes(fid, episodes)
    return changed


def mark_all_listened(fid, state=True):
    episodes = load_episodes(fid)
    for ep in episodes:
        ep['listened']      = state
        ep['listened_date'] = now_iso() if state else None
    save_episodes(fid, episodes)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MENU: FEEDS (main screen)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def menu_main():
    while True:
        clrscr()
        feed_list = list(_feeds.values())

        hdr('PODCAST MANAGER  v' + VERSION,
            '{} podcast(s)   dl: {}'.format(len(feed_list), cfg('download_dir')))

        if not feed_list:
            print('\n  ' + DM + 'No podcasts yet — press A to add one.' + RS)
        else:
            sec('Your Podcasts')
            for idx, fd in enumerate(feed_list, 1):
                new   = fd.get('new_since_refresh', 0)
                badge = (' ' + GN + '[{} new]'.format(new) + RS
                         if new > 0 and _COLOUR
                         else (' [{} new]'.format(new) if new > 0 else ''))
                title = trunc(fd['title'], 46)
                print('  {}{:2d}.{} {}{}'.format(BD, idx, RS, title, badge))
                print('       {}{}  {} episodes   updated {}{}'.format(
                    DM,
                    trunc(fd.get('author') or fd.get('category') or '', 26),
                    fd.get('episode_count', 0),
                    date_display(fd.get('last_updated', '')),
                    RS))

        sec('Commands')
        print('  {}A{} Add podcast      {}R{} Refresh all    {}N{} New/unlistened'.format(
              BD, RS, BD, RS, BD, RS))
        print('  {}S{} Settings         {}Q{} Quit'.format(BD, RS, BD, RS))
        if feed_list:
            print('  Enter a number to open that podcast')
        print()

        ch = ask('Choice').upper()

        if ch == 'Q':
            print('\n  Goodbye!\n')
            sys.exit(0)
        elif ch == 'A':
            sec('Add Podcast')
            url = ask('RSS feed URL')
            if url:
                add_feed(url)
                pause()
        elif ch == 'R':
            sec('Refreshing All Feeds')
            refresh_all()
            pause()
        elif ch == 'S':
            menu_settings()
        elif ch == 'N':
            menu_new_episodes()
        elif ch.isdigit():
            n = int(ch) - 1
            if 0 <= n < len(feed_list):
                menu_episodes(feed_list[n]['id'])
            else:
                warn('No podcast with that number.')
                time.sleep(1)
        elif ch:
            warn('Unknown command.')
            time.sleep(0.8)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MENU: EPISODE LIST (for one feed)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PAGE_SIZE = 10

def menu_episodes(fid):
    page   = 0
    filt   = 'all'          # 'all' | 'new' | 'downloaded'

    while True:
        feed = _feeds.get(fid)
        if not feed:
            return

        all_eps = load_episodes(fid)

        if filt == 'new':
            eps = [e for e in all_eps if not e.get('listened')]
        elif filt == 'downloaded':
            eps = [e for e in all_eps if e.get('downloaded')]
        else:
            eps = all_eps

        total_pages = max(1, (len(eps) + PAGE_SIZE - 1) // PAGE_SIZE)
        page        = min(page, total_pages - 1)
        start       = page * PAGE_SIZE
        page_eps    = eps[start:start + PAGE_SIZE]

        clrscr()
        hdr(trunc(feed['title'], 60),
            '{} eps   filter:{}   page {}/{}'.format(
                len(all_eps), filt, page + 1, total_pages))

        if feed.get('description'):
            print('  ' + DM + trunc(strip_html(feed['description']), SCREEN_W - 4) + RS)

        sec('Episodes  (D=downloaded  *=listened)')

        if not page_eps:
            print('  ' + DM + 'No episodes match this filter.' + RS)
        else:
            for rel_i, ep in enumerate(page_eps, 1):
                abs_n  = start + rel_i
                dl     = (GN + 'D' + RS) if ep.get('downloaded') and _COLOUR else ('D' if ep.get('downloaded') else ' ')
                li     = '*' if ep.get('listened') else ' '
                title  = trunc(ep['title'], 48)
                date   = date_display(ep.get('pub_date', ''))
                dur    = human_dur(ep.get('duration_secs', 0))
                sz     = human_size(ep.get('file_size', 0))
                print('  {}{:3d}.{} {}{} {}'.format(BD, abs_n, RS, dl, li, title))
                print('        {}{}  {}  {}{}'.format(DM, date, dur, sz, RS))

        sec('Commands')
        print('  Enter number = episode detail')
        print('  {}D<n>{} Download #n     {}L<n>{} Mark listened #n'.format(BD, RS, BD, RS))
        print('  {}DA{}  Download all    {}MA{}  Mark all listened'.format(BD, RS, BD, RS))
        print('  {}F{}   Cycle filter({})  {}P{}/{}N{} Prev/Next page'.format(
              BD, RS, filt, BD, RS, BD, RS))
        print('  {}RF{}  Refresh feed    {}RM{}  Remove feed    {}B{} Back'.format(
              BD, RS, BD, RS, BD, RS))
        print()

        ch = ask('Choice').upper()

        if ch in ('B', ''):
            return

        elif ch == 'P':
            if page > 0:
                page -= 1
            else:
                warn('Already on first page.')
                time.sleep(0.6)

        elif ch == 'N':
            if page < total_pages - 1:
                page += 1
            else:
                warn('Already on last page.')
                time.sleep(0.6)

        elif ch == 'F':
            filt = {'all': 'new', 'new': 'downloaded', 'downloaded': 'all'}[filt]
            page = 0

        elif ch == 'RF':
            sec('Refreshing Feed')
            refresh_feed(fid)
            pause()

        elif ch == 'RM':
            if confirm("Remove '{}' and ALL its data?".format(
                    trunc(feed['title'], 40)), default=False):
                remove_feed(fid)
                return

        elif ch == 'DA':
            to_dl = [e for e in eps if not e.get('downloaded')]
            if not to_dl:
                info('Nothing to download.')
                pause()
            else:
                info('Downloading {} episode(s)…'.format(len(to_dl)))
                for ep in to_dl:
                    download_episode(fid, ep['id'])
                pause()

        elif ch == 'MA':
            mark_all_listened(fid, True)
            ok('All episodes marked as listened.')
            time.sleep(0.8)

        elif ch.startswith('D') and ch[1:].isdigit():
            n = int(ch[1:]) - 1
            if 0 <= n < len(eps):
                download_episode(fid, eps[n]['id'])
                pause()
            else:
                warn('No episode #{}.'.format(int(ch[1:])))
                time.sleep(0.8)

        elif ch.startswith('L') and ch[1:].isdigit():
            n = int(ch[1:]) - 1
            if 0 <= n < len(eps):
                ep        = eps[n]
                new_state = not ep.get('listened', False)
                mark_listened(fid, ep['id'], new_state)
                label = 'listened' if new_state else 'unlistened'
                ok('Marked as {}: {}'.format(label, trunc(ep['title'], 40)))
                time.sleep(0.7)
            else:
                warn('No episode #{}.'.format(int(ch[1:])))
                time.sleep(0.8)

        elif ch.isdigit():
            n = int(ch) - 1
            if 0 <= n < len(eps):
                menu_episode_detail(fid, eps[n]['id'])
            else:
                warn('No episode #{}.'.format(int(ch)))
                time.sleep(0.8)

        elif ch:
            warn('Unknown command.')
            time.sleep(0.7)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MENU: EPISODE DETAIL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def menu_episode_detail(fid, ep_id):
    while True:
        eps = load_episodes(fid)
        ep  = next((e for e in eps if e['id'] == ep_id), None)
        if not ep:
            return
        feed = _feeds.get(fid, {})

        clrscr()
        hdr(trunc(ep['title'], 70))
        print()
        print('  {}Podcast: {}  {}'.format(BD, RS, feed.get('title', '?')))
        print('  {}Date:    {}  {}'.format(BD, RS, date_display(ep.get('pub_date', ''))))
        print('  {}Duration:{}  {}'.format(BD, RS, human_dur(ep.get('duration_secs', 0))))
        print('  {}Size:    {}  {}'.format(BD, RS, human_size(ep.get('file_size', 0))))

        if ep.get('downloaded') and _COLOUR:
            dl_val = GN + 'Yes' + RS
        else:
            dl_val = 'Yes' if ep.get('downloaded') else 'No'
        print('  {}Downloaded:{} {}'.format(BD, RS, dl_val))

        if ep.get('download_path'):
            print('  {}Path:    {}  {}'.format(BD, RS, ep['download_path']))

        li_val = 'Yes' if ep.get('listened') else 'No'
        print('  {}Listened:{}  {}'.format(BD, RS, li_val))
        print('  {}URL:     {}  {}'.format(BD, RS, trunc(ep.get('url', ''), SCREEN_W - 12)))

        if ep.get('description'):
            sec('Description')
            for line in word_wrap(ep['description'][:800], SCREEN_W - 2):
                print(DM + line + RS if _COLOUR else line)
            if len(ep.get('description', '')) > 800:
                print('  ' + DM + '[truncated]' + RS)

        sec('Commands')
        action_d = 'Re-download' if ep.get('downloaded') else 'Download'
        action_l = 'Mark unlistened' if ep.get('listened') else 'Mark listened'
        print('  {}D{} {}   {}L{} {}   {}B{} Back'.format(
              BD, RS, action_d, BD, RS, action_l, BD, RS))
        print()

        ch = ask('Choice').upper()

        if ch in ('B', ''):
            return
        elif ch == 'D':
            download_episode(fid, ep_id)
            pause()
        elif ch == 'L':
            new_state = not ep.get('listened', False)
            mark_listened(fid, ep_id, new_state)
            label = 'listened' if new_state else 'unlistened'
            ok('Marked as ' + label)
            time.sleep(0.7)
        elif ch:
            warn('Unknown command.')
            time.sleep(0.7)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MENU: NEW / UNLISTENED EPISODES (across all feeds)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def menu_new_episodes():
    while True:
        # Gather all unlistened episodes across every feed
        all_new = []
        for fid, feed in _feeds.items():
            for ep in load_episodes(fid):
                if not ep.get('listened'):
                    all_new.append((feed, ep))

        all_new.sort(key=lambda x: sort_key_pub_date(x[1]), reverse=True)

        clrscr()
        hdr('UNLISTENED EPISODES', '{} total across all podcasts'.format(len(all_new)))

        if not all_new:
            print('\n  ' + GN + 'All caught up! No unlistened episodes.' + RS)
            pause()
            return

        sec('Unlistened  (D=downloaded)')
        shown = all_new[:20]
        for i, (feed, ep) in enumerate(shown, 1):
            dl    = ('D' if ep.get('downloaded') else ' ')
            title = trunc(ep['title'], 42)
            ftit  = trunc(feed['title'], 22)
            date  = date_display(ep.get('pub_date', ''))
            print('  {}{:2d}.{} {} {}  {}{}  {}{}'.format(
                  BD, i, RS, dl, title, DM, ftit, date, RS))

        if len(all_new) > 20:
            print('  ' + DM + '… and {} more (open individual podcasts to see all)'.format(
                  len(all_new) - 20) + RS)

        sec('Commands')
        print('  Enter number = episode detail')
        print('  {}D<n>{} Download #n   {}L<n>{} Mark listened #n   {}B{} Back'.format(
              BD, RS, BD, RS, BD, RS))
        print()

        ch = ask('Choice').upper()

        if ch in ('B', ''):
            return

        elif ch.startswith('D') and ch[1:].isdigit():
            n = int(ch[1:]) - 1
            if 0 <= n < len(shown):
                feed, ep = shown[n]
                download_episode(feed['id'], ep['id'])
                pause()
            else:
                warn('No episode #{}'.format(int(ch[1:])))
                time.sleep(0.8)

        elif ch.startswith('L') and ch[1:].isdigit():
            n = int(ch[1:]) - 1
            if 0 <= n < len(shown):
                feed, ep = shown[n]
                mark_listened(feed['id'], ep['id'], True)
                ok('Marked as listened: ' + trunc(ep['title'], 40))
                time.sleep(0.7)
            else:
                warn('No episode #{}'.format(int(ch[1:])))
                time.sleep(0.8)

        elif ch.isdigit():
            n = int(ch) - 1
            if 0 <= n < len(shown):
                feed, ep = shown[n]
                menu_episode_detail(feed['id'], ep['id'])
            else:
                warn('No episode #{}'.format(int(ch)))
                time.sleep(0.8)

        elif ch:
            warn('Unknown command.')
            time.sleep(0.7)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MENU: SETTINGS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def menu_settings():
    while True:
        clrscr()
        hdr('SETTINGS')
        sec('Current Configuration')

        dl_dir   = cfg('download_dir')
        delay    = cfg('rate_limit_delay')
        timeout  = cfg('http_timeout')
        max_ep   = cfg('max_episodes_per_feed')
        auto_r   = cfg('auto_refresh_on_start')

        print('  {}1.{} Download folder        : {}'.format(BD, RS, dl_dir))
        print('  {}2.{} Rate-limit delay       : {}s between requests to same host'.format(BD, RS, delay))
        print('  {}3.{} HTTP timeout           : {}s'.format(BD, RS, timeout))
        print('  {}4.{} Max episodes per feed  : {}'.format(BD, RS, max_ep))
        print('  {}5.{} Auto-refresh on start  : {}'.format(BD, RS, 'Yes' if auto_r else 'No'))
        print()
        print('  Config stored in : ' + _CONFIG_DIR)
        print('  Data  stored in  : ' + _EPISODES_DIR)

        sec('Commands')
        print('  Enter a number to change that setting   {}B{} Back'.format(BD, RS))
        print()

        ch = ask('Choice').upper()

        if ch in ('B', ''):
            return

        elif ch == '1':
            new_dir = ask('New download folder', default=dl_dir)
            if new_dir:
                try:
                    os.makedirs(new_dir, exist_ok=True)
                    _cfg['download_dir'] = new_dir
                    save_config()
                    ok('Download folder set to: ' + new_dir)
                except Exception as e:
                    err('Could not create folder: ' + str(e))
                pause()

        elif ch == '2':
            val = ask('Rate-limit delay in seconds', default=str(delay))
            try:
                _cfg['rate_limit_delay'] = max(0.0, float(val))
                save_config()
                ok('Delay set to {}s'.format(_cfg['rate_limit_delay']))
            except ValueError:
                err('Please enter a number.')
            pause()

        elif ch == '3':
            val = ask('HTTP timeout in seconds', default=str(timeout))
            try:
                _cfg['http_timeout'] = max(5, int(val))
                save_config()
                ok('Timeout set to {}s'.format(_cfg['http_timeout']))
            except ValueError:
                err('Please enter a whole number.')
            pause()

        elif ch == '4':
            val = ask('Max episodes to keep per feed', default=str(max_ep))
            try:
                _cfg['max_episodes_per_feed'] = max(1, int(val))
                save_config()
                ok('Max episodes set to {}'.format(_cfg['max_episodes_per_feed']))
            except ValueError:
                err('Please enter a whole number.')
            pause()

        elif ch == '5':
            _cfg['auto_refresh_on_start'] = not auto_r
            save_config()
            ok('Auto-refresh {}.'.format(
                'enabled' if _cfg['auto_refresh_on_start'] else 'disabled'))
            time.sleep(0.8)

        elif ch:
            warn('Unknown option.')
            time.sleep(0.7)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ENTRY POINT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    clrscr()
    hdr('PODCAST MANAGER  v' + VERSION,
        'Terminal podcast manager for RISC OS & Linux')
    print()
    print('  Platform  : {} {}'.format(
        'RISC OS' if IS_RISCOS else 'Linux/POSIX',
        '(no SSL — only http:// feeds)' if not _HAS_SSL else ''))
    print('  Config    : ' + _CONFIG_DIR)
    print('  Python    : {}.{}.{}'.format(*sys.version_info[:3]))

    # Initialise storage
    info('Loading config…')
    load_config()
    load_feeds()
    _ensure_dirs()

    # Make sure download root exists
    try:
        os.makedirs(cfg('download_dir'), exist_ok=True)
    except Exception:
        pass

    ok('Ready.  {} podcast(s) loaded.'.format(len(_feeds)))

    # Auto-refresh
    if cfg('auto_refresh_on_start') and _feeds:
        print()
        info('Auto-refreshing all feeds…')
        refresh_all()
        pause()

    # Go to main menu
    try:
        menu_main()
    except KeyboardInterrupt:
        print('\n\n  Goodbye!\n')
        sys.exit(0)


if __name__ == '__main__':
    main()
