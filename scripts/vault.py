#!/usr/bin/env python3
"""Tube Radar 암호화 도구.

  python vault.py unpack STATE_DIR          data 브랜치의 state.enc → *.json 복원
  python vault.py pack   STATE_DIR          *.json → state.enc (평문 json 삭제)
  python vault.py site   STATE_DIR OUTFILE  사이트용 bundle.enc 생성 (SITE_PASSWORD 로 잠금)

키
  SITE_PASSWORD : 사이트 비밀번호 (누나와 공유하는 것, 바꿔도 됨)
  YT_API_KEY    : 저장 데이터(state) 잠금에 사용 (바꾸면 쌓인 데이터를 못 읽음)
  DATA_KEY      : 있으면 YT_API_KEY 대신 state 잠금에 사용
"""
import base64
import gzip
import hashlib
import json
import os
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NAMES = ["videos.json", "channels.json", "ranks.json", "meta.json"]
SITE_SALT = b"tube-radar-site-v1"
SITE_ITER = 250000


def b64(b):
    return base64.b64encode(b).decode()


def state_key():
    secret = os.environ.get("DATA_KEY") or os.environ.get("YT_API_KEY")
    if not secret:
        sys.exit("YT_API_KEY 가 없습니다.")
    return hashlib.sha256(b"tube-radar-state-v1:" + secret.encode()).digest()


def site_key(pw):
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), SITE_SALT, SITE_ITER, 32)


def seal(key, raw):
    iv = os.urandom(12)
    return {"v": 1, "iv": b64(iv), "ct": b64(AESGCM(key).encrypt(iv, gzip.compress(raw, 9), None))}


def open_(key, box):
    return gzip.decompress(AESGCM(key).decrypt(base64.b64decode(box["iv"]), base64.b64decode(box["ct"]), None))


def read_state(d):
    out = {}
    for n in NAMES:
        p = os.path.join(d, n)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                out[n] = json.load(f)
    return out


def main():
    cmd, d = sys.argv[1], sys.argv[2]
    enc = os.path.join(d, "state.enc")
    if cmd == "unpack":
        if not os.path.exists(enc):
            print("암호화된 저장 데이터 없음 (첫 실행이거나 이전 평문 데이터를 그대로 사용)")
            return
        try:
            data = json.loads(open_(state_key(), json.load(open(enc))))
        except Exception:
            sys.exit("저장 데이터를 풀지 못했습니다. YT_API_KEY(또는 DATA_KEY)를 바꿨다면 원래 값으로 되돌리세요.")
        for n, obj in data.items():
            with open(os.path.join(d, n), "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        print("저장 데이터 복원:", ", ".join(data))
    elif cmd == "pack":
        data = read_state(d)
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
        with open(enc, "w") as f:
            json.dump(seal(state_key(), raw), f)
        for n in NAMES:
            p = os.path.join(d, n)
            if os.path.exists(p):
                os.remove(p)
        print(f"저장 데이터 암호화 완료 ({len(raw)//1024}KB → {os.path.getsize(enc)//1024}KB)")
    elif cmd == "site":
        pw = os.environ.get("SITE_PASSWORD", "")
        if len(pw) < 4:
            sys.exit("SITE_PASSWORD 시크릿이 없거나 너무 짧습니다 (4자 이상). 사이트 데이터를 올리지 않습니다.")
        data = read_state(d)
        raw = json.dumps({k[:-5]: v for k, v in data.items()}, ensure_ascii=False, separators=(",", ":")).encode()
        box = seal(site_key(pw), raw)
        box["iter"] = SITE_ITER
        box["salt"] = SITE_SALT.decode()
        with open(sys.argv[3], "w") as f:
            json.dump(box, f)
        print("사이트 데이터 잠금 완료")


if __name__ == "__main__":
    main()
