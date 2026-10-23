#!/usr/bin/env python3
"""Tube Radar scanner.

모드
  full  : 키워드 검색 + 인기차트 + 추적 채널 신규 업로드 수집 + 전체 갱신 (하루 1회)
  light : 인기차트 + 추적 중인 영상/채널 수치만 갱신 (하루 여러 번, 쿼터 적게 씀)

표준 라이브러리만 사용합니다 (설치 필요 없음).
"""
import argparse
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

API = os.environ.get("YT_API_BASE", "https://www.googleapis.com/youtube/v3")
KEY = os.environ.get("YT_API_KEY", "")
SHORTS_CHECK = os.environ.get("SHORTS_CHECK", "1") == "1"
KST = timezone(timedelta(hours=9))
NOW = float(os.environ.get("FAKE_NOW") or time.time())  # FAKE_NOW 는 테스트용

COST = {"search": 100}  # 나머지 호출은 1 unit


class QuotaExceeded(Exception):
    pass


class KeyInvalid(Exception):
    pass


class Api:
    def __init__(self, budget):
        self.used = 0
        self.budget = budget
        self.calls = 0
        self.errors = []

    def can(self, cost):
        return self.used + cost <= self.budget

    def get(self, endpoint, **params):
        cost = COST.get(endpoint, 1)
        if not self.can(cost):
            raise QuotaExceeded("오늘 예산(daily_unit_budget) 도달")
        params = {k: v for k, v in params.items() if v not in (None, "")}
        params["key"] = KEY
        url = f"{API}/{endpoint}?{urllib.parse.urlencode(params)}"
        last = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    self.used += cost
                    self.calls += 1
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "ignore")
                reason = ""
                try:
                    reason = json.loads(body)["error"]["errors"][0].get("reason", "")
                except Exception:
                    pass
                self.used += cost
                if reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded") and e.code == 403:
                    raise QuotaExceeded(reason)
                if reason in ("keyInvalid", "API_KEY_INVALID") or (e.code == 400 and "API key" in body):
                    raise KeyInvalid(body[:300])
                if e.code == 403 and "accessNotConfigured" in body:
                    raise KeyInvalid("YouTube Data API v3가 이 키의 프로젝트에서 켜져 있지 않습니다.")
                if e.code >= 500:
                    last = e
                    time.sleep(2 * (attempt + 1))
                    continue
                self.errors.append(f"{endpoint} {e.code} {reason}")
                return None
            except (urllib.error.URLError, TimeoutError) as e:
                last = e
                time.sleep(2 * (attempt + 1))
        self.errors.append(f"{endpoint} 네트워크 오류 {last}")
        return None


# ---------- 유틸 ----------
def iso_to_ts(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def parse_dur(s):
    if not s:
        return 0
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s)
    if not m:
        return 0
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def num(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def kst_date(ts=None):
    return datetime.fromtimestamp(ts or NOW, KST).strftime("%Y-%m-%d")


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


# ---------- 쇼츠 판별 ----------
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(NoRedirect)


def check_shorts(vid):
    """youtube.com/shorts/ID 가 200이면 쇼츠, 리다이렉트(303)면 일반 영상."""
    try:
        req = urllib.request.Request(
            f"https://www.youtube.com/shorts/{vid}", method="HEAD",
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR"})
        with _opener.open(req, timeout=10) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            return False
        return None
    except Exception:
        return None


# ---------- 수집 ----------
def ingest_videos(api, ids, videos, channels_needed, source):
    ids = list(dict.fromkeys(i for i in ids if i))
    for group in chunks(ids, 50):
        data = api.get("videos", part="snippet,statistics,contentDetails", id=",".join(group), maxResults=50)
        if not data:
            continue
        for it in data.get("items", []):
            update_video(videos, it, source)
            channels_needed.add(it["snippet"]["channelId"])


def update_video(videos, it, source=None):
    vid = it["id"]
    sn, st, cd = it.get("snippet", {}), it.get("statistics", {}), it.get("contentDetails", {})
    v = videos.get(vid) or {"hist": [], "src": []}
    thumbs = sn.get("thumbnails", {})
    v.update({
        "ch": sn.get("channelId"),
        "t": sn.get("title", ""),
        "th": (thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}).get("url", ""),
        "pub": iso_to_ts(sn.get("publishedAt")),
        "dur": parse_dur(cd.get("duration")),
        "cat": sn.get("categoryId"),
        "live": sn.get("liveBroadcastContent", "none") != "none",
    })
    if "#shorts" in (v["t"] + " " + sn.get("description", "")[:300]).lower() and v["dur"] <= 180:
        v["sh"] = True
    if source and source not in v["src"]:
        v["src"] = (v["src"] + [source])[-5:]
    views, likes, comments = num(st.get("viewCount")), num(st.get("likeCount")), num(st.get("commentCount"))
    if views is not None:
        now_h = round(NOW / 3600, 2)
        h = v["hist"]
        if h and now_h - h[-1][0] < 2:  # 2시간 안에 중복 관측이면 덮어쓰기
            h[-1] = [now_h, views, likes, comments]
        else:
            h.append([now_h, views, likes, comments])
        v["hist"] = h[-24:]
    videos[vid] = v


def update_channels(api, ids, channels):
    ids = list(dict.fromkeys(i for i in ids if i))
    today = kst_date()
    for group in chunks(ids, 50):
        data = api.get("channels", part="snippet,statistics", id=",".join(group), maxResults=50)
        if not data:
            continue
        for it in data.get("items", []):
            cid = it["id"]
            sn, st = it.get("snippet", {}), it.get("statistics", {})
            c = channels.get(cid) or {"hist": [], "first": NOW}
            thumbs = sn.get("thumbnails", {})
            subs = None if st.get("hiddenSubscriberCount") else num(st.get("subscriberCount"))
            c.update({
                "t": sn.get("title", ""),
                "h": sn.get("customUrl", ""),
                "th": (thumbs.get("default") or {}).get("url", ""),
                "pub": iso_to_ts(sn.get("publishedAt")),
                "cc": sn.get("country", ""),
                "subs": subs,
                "views": num(st.get("viewCount")),
                "vc": num(st.get("videoCount")),
                "seen": NOW,
            })
            h = c["hist"]
            row = [today, subs, c["views"], c["vc"]]
            if h and h[-1][0] == today:
                h[-1] = row
            else:
                h.append(row)
            c["hist"] = h[-60:]
            channels[cid] = c


def search_keywords(api, cfg, log):
    after = (datetime.now(timezone.utc) - timedelta(days=cfg["search_days"])).strftime("%Y-%m-%dT%H:%M:%SZ")
    found = []
    variants = [None] + (["short"] if cfg.get("search_shorts_too") else [])
    for kw in cfg["keywords"]:
        for dur in variants:
            data = api.get("search", part="id", q=kw, type="video", order="viewCount",
                           publishedAfter=after, regionCode=cfg["region"],
                           relevanceLanguage=cfg["language"], videoDuration=dur, maxResults=50)
            n = 0
            for it in (data or {}).get("items", []):
                vid = it.get("id", {}).get("videoId")
                if vid:
                    found.append((vid, f"kw:{kw}"))
                    n += 1
            log.append(f"검색 '{kw}'{' (쇼츠)' if dur else ''}: {n}개")
    return found


def popular(api, cfg, log):
    found = []
    for cat in cfg["popular_categories"]:
        token = None
        for _ in range(cfg.get("popular_pages", 2)):
            data = api.get("videos", part="id", chart="mostPopular", regionCode=cfg["region"],
                           videoCategoryId=cat, maxResults=50, pageToken=token)
            if not data:
                break
            for it in data.get("items", []):
                found.append((it["id"], f"pop:{cat or 'all'}"))
            token = data.get("nextPageToken")
            if not token:
                break
    log.append(f"인기 차트: {len(found)}개")
    return found


def crawl_uploads(api, cids, videos, cfg, log):
    cutoff = NOW - cfg["video_max_age_days"] * 86400
    new_ids = []
    for cid in cids:
        if not api.can(1):
            break
        data = api.get("playlistItems", part="contentDetails", playlistId="UU" + cid[2:], maxResults=10)
        for it in (data or {}).get("items", []):
            cd = it.get("contentDetails", {})
            ts = iso_to_ts(cd.get("videoPublishedAt"))
            vid = cd.get("videoId")
            if vid and ts and ts >= cutoff and vid not in videos:
                new_ids.append(vid)
    log.append(f"추적 채널 {len(cids)}곳 신규 업로드: {len(new_ids)}개")
    return new_ids


# ---------- 지표 ----------
def video_metrics(v, subs):
    h = v.get("hist") or []
    if not h:
        return
    now_h = NOW / 3600
    t, views, likes, comments = h[-1]
    age_h = max((NOW - (v.get("pub") or NOW)) / 3600, 1)
    v["age"] = round(age_h, 1)
    v["v"], v["l"], v["c"] = views, likes, comments
    v["vph"] = round(views / age_h, 1)
    # 최근 24시간 증가량 (관측 기반, 24h 환산)
    best = None
    for p in h[:-1]:
        gap = t - p[0]
        if gap >= 5:
            score = abs(gap - 24)
            if best is None or score < best[0]:
                best = (score, p)
    if best:
        p = best[1]
        v["g24"] = max(0, round((views - p[1]) / (t - p[0]) * 24))
        v["gEst"] = False
    elif age_h <= 48:
        v["g24"] = round(views / age_h * min(24, age_h))
        v["gEst"] = True
    else:
        v["g24"] = None
    v["ratio"] = round(views / max(subs or 0, 100), 2) if subs is not None else None
    v["lr"] = round(likes / views * 100, 2) if (likes is not None and views) else None
    v["sh"] = bool(v.get("sh"))


def channel_metrics(c, vids):
    subs = c.get("subs")
    recent = [v for v in vids if v.get("age", 1e9) <= 60 * 24 and not v.get("live")]
    recent.sort(key=lambda v: v.get("pub") or 0, reverse=True)
    sample = recent[:12]
    views = [v["v"] for v in sample if v.get("v") is not None]
    c["n"] = len(sample)
    c["med"] = int(statistics.median(views)) if views else None
    c["max"] = max(views) if views else None
    c["shr"] = round(sum(1 for v in sample if v.get("sh")) / len(sample), 2) if sample else None
    base = max(subs or 0, 500)
    # 꿀통 지수: 구독자 대비 최근 영상 중앙 조회수
    if c["med"] is not None:
        r = c["med"] / base
        c["honeyR"] = round(r, 2)
        s = 40 * math.log10(1 + 10 * r)
        if c["n"] < 3:
            s *= 0.85
        c["honey"] = round(min(100, s), 1)
    else:
        c["honeyR"] = c["honey"] = None
    # 떡상 지수: 최근 24h 조회수 증가 (절대량 + 구독자 대비)
    g = sum(v.get("g24") or 0 for v in recent)
    c["g24"] = g
    sg = None
    h = c.get("hist") or []
    if len(h) >= 2 and h[-1][1] is not None:
        for row in reversed(h[:-1]):
            if row[1] is not None:
                days = max((datetime.fromisoformat(h[-1][0]) - datetime.fromisoformat(row[0])).days, 1)
                sg = round((h[-1][1] - row[1]) / days)
                break
    c["sg"] = sg
    rk = 20 * math.log10(1 + g / 1000) + 30 * math.log10(1 + g / max(subs or 0, 1000))
    if sg and sg > 0:
        rk += 8 * math.log10(1 + sg / 100)
    c["rocket"] = round(min(100, rk), 1)
    c["ageD"] = round((NOW - c["pub"]) / 86400) if c.get("pub") else None
    top = max(sample, key=lambda v: v.get("v") or 0) if sample else None
    c["top"] = top["id"] if top else None


# ---------- 메인 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "light"], default="full")
    ap.add_argument("--state", default="state")
    ap.add_argument("--config", default="config.json")
    args = ap.parse_args()

    cfg = load(args.config, {})
    os.makedirs(args.state, exist_ok=True)
    P = lambda n: os.path.join(args.state, n)
    videos = load(P("videos.json"), {})
    channels = load(P("channels.json"), {})
    ranks = load(P("ranks.json"), {})
    meta = load(P("meta.json"), {"runs": []})

    today = kst_date()
    quota = meta.get("quota", {})
    # YouTube 쿼터는 미국 태평양시 자정(한국 16~17시)에 초기화
    pt_day = datetime.fromtimestamp(NOW, timezone(timedelta(hours=-8))).strftime("%Y-%m-%d")
    used_today = quota.get("used", 0) if quota.get("day") == pt_day else 0
    api = Api(max(0, cfg.get("daily_unit_budget", 8000) - used_today))

    log, status = [], "ok"
    watch = set(cfg.get("watch_channels") or [])
    t0 = time.time()
    if not KEY:
        status, log = "error", ["YT_API_KEY 시크릿이 비어 있습니다. GitHub 저장소 Settings → Secrets에 등록하세요."]
    else:
        try:
            need_ch = set(watch)
            # 1) 후보 발굴
            found = popular(api, cfg, log)
            if args.mode == "full":
                found += search_keywords(api, cfg, log)
            src = {}
            for vid, s in found:
                src.setdefault(vid, s)
            new_ids = [v for v in src if v not in videos]
            for vid in src:
                if vid in videos and src[vid] not in videos[vid]["src"]:
                    videos[vid]["src"] = (videos[vid]["src"] + [src[vid]])[-5:]
            # 2) 추적 채널 신규 업로드 (full)
            if args.mode == "full" and channels:
                pri = sorted(channels, key=lambda c: -(max(channels[c].get("rocket") or 0, channels[c].get("honey") or 0)))
                crawl = list(dict.fromkeys(list(watch & set(channels)) + pri))[:cfg.get("upload_crawl_channels", 400)]
                new_ids += crawl_uploads(api, crawl, videos, cfg, log)
            # 3) 기존 영상 갱신 + 신규 영상 상세
            cutoff = NOW - cfg["video_max_age_days"] * 86400
            refresh = [vid for vid, v in videos.items() if (v.get("pub") or NOW) >= cutoff]
            ingest_videos(api, list(dict.fromkeys(new_ids + refresh)), videos, need_ch, None)
            for vid in new_ids:
                if vid in videos and src.get(vid) and src[vid] not in videos[vid]["src"]:
                    videos[vid]["src"].append(src[vid])
            # 4) 채널 갱신
            need_ch |= set(channels)
            update_channels(api, list(need_ch), channels)
            log.append(f"영상 {len(videos)}개 / 채널 {len(channels)}곳 갱신")
        except QuotaExceeded as e:
            status = "quota"
            log.append(f"쿼터 소진으로 중단: {e} — 여기까지 모은 데이터는 저장합니다.")
        except KeyInvalid as e:
            status = "error"
            log.append(f"API 키 오류: {e}")

    # 쇼츠 판별 (61~180초 애매한 영상만)
    if SHORTS_CHECK:
        todo = [vid for vid, v in videos.items() if "shc" not in v and 60 < (v.get("dur") or 0) <= 180][:400]
        with ThreadPoolExecutor(8) as ex:
            for vid, res in zip(todo, ex.map(check_shorts, todo)):
                if res is not None:
                    videos[vid]["sh"] = res
                    videos[vid]["shc"] = 1
    for v in videos.values():
        if (v.get("dur") or 0) and v["dur"] <= 60 and "shc" not in v:
            v["sh"] = True

    # 지표 계산
    by_ch = {}
    for vid, v in videos.items():
        v["id"] = vid
        video_metrics(v, (channels.get(v.get("ch")) or {}).get("subs"))
        by_ch.setdefault(v.get("ch"), []).append(v)
    for cid, c in channels.items():
        channel_metrics(c, by_ch.get(cid, []))

    # 정리 (용량 관리)
    cutoff = NOW - cfg["video_max_age_days"] * 86400
    videos = {k: v for k, v in videos.items() if (v.get("pub") or NOW) >= cutoff and v.get("ch") in channels}
    if len(videos) > cfg["max_videos"]:
        keep = sorted(videos, key=lambda k: -((videos[k].get("g24") or 0) + (videos[k].get("vph") or 0) * 10))
        videos = {k: videos[k] for k in keep[:cfg["max_videos"]]}
    if len(channels) > cfg["max_channels"]:
        keep = sorted(channels, key=lambda k: (k not in watch, -max(channels[k].get("rocket") or 0, channels[k].get("honey") or 0)))
        channels = {k: channels[k] for k in keep[:cfg["max_channels"]]}
    for v in videos.values():
        v.pop("id", None)

    # Top 300 순위 기록 (하루 1개, 30일 보관)
    top = sorted(channels, key=lambda k: -(channels[k].get("rocket") or 0))[:300]
    ranks[today] = top
    ranks = {d: ranks[d] for d in sorted(ranks)[-30:]}

    run = {"at": NOW, "mode": args.mode, "status": status, "units": api.used, "calls": api.calls,
           "sec": round(time.time() - t0), "log": log + api.errors[:20]}
    meta["runs"] = ([run] + meta.get("runs", []))[:40]
    meta["quota"] = {"day": pt_day, "used": used_today + api.used}
    meta["last"] = NOW
    if status != "error":
        meta["lastOk"] = NOW
    meta["cfg"] = {k: cfg.get(k) for k in ("keywords", "region", "search_days", "video_max_age_days", "rpm_krw", "daily_unit_budget")}
    meta["counts"] = {"videos": len(videos), "channels": len(channels)}

    save(P("videos.json"), videos)
    save(P("channels.json"), channels)
    save(P("ranks.json"), ranks)
    save(P("meta.json"), meta)
    print("\n".join(run["log"]))
    print(f"[{status}] units={api.used} videos={len(videos)} channels={len(channels)}")
    if status == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
