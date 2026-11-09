"""Ежедневная публикация рекламы: Telegram (группа + история), Instagram (история), Facebook (история + пост).
Картинка выбирается по кругу по номеру дня, текст всегда один и тот же (text.txt)."""
import asyncio, datetime, json, os, sys, time, urllib.parse, urllib.request, zoneinfo
from pathlib import Path

HERE = Path(__file__).parent
TZ = zoneinfo.ZoneInfo("Europe/Bucharest")
RAW_BASE = os.environ.get("RAW_BASE", "")  # https://raw.githubusercontent.com/<user>/<repo>/main
G = "https://graph.facebook.com/v21.0"

def env(k, default=None):
    v = os.environ.get(k, default)
    if v is None:
        sys.exit(f"missing env {k}")
    return v

def pick_image(today):
    imgs = sorted(p for p in (HERE / "images").iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    if not imgs:
        sys.exit("no images")
    return imgs[today.toordinal() % len(imgs)]

def graph(method, path, **params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"{G}/{path}", data=data if method == "POST" else None, method=method)
    url = req.full_url if method == "POST" else f"{G}/{path}?{data.decode()}"
    req = urllib.request.Request(url, data=data if method == "POST" else None, method=method)
    try:
        return json.load(urllib.request.urlopen(req, timeout=60))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{path}: {e.read().decode()[:400]}")

def wait_container(cid, token):
    for _ in range(30):
        st = graph("GET", cid, fields="status_code", access_token=token)
        if st.get("status_code") == "FINISHED":
            return
        if st.get("status_code") == "ERROR":
            raise RuntimeError(f"container error: {st}")
        time.sleep(3)
    raise RuntimeError("container not ready")

def instagram_story(image_url, token, ig_user):
    c = graph("POST", f"{ig_user}/media", media_type="STORIES", image_url=image_url, access_token=token)
    wait_container(c["id"], token)
    r = graph("POST", f"{ig_user}/media_publish", creation_id=c["id"], access_token=token)
    print("instagram story:", r)

def facebook_story(image_url, token, page):
    photo = graph("POST", f"{page}/photos", url=image_url, published="false", access_token=token)
    r = graph("POST", f"{page}/photo_stories", photo_id=photo["id"], access_token=token)
    print("facebook story:", r)

def facebook_post(image_url, text, token, page):
    r = graph("POST", f"{page}/photos", url=image_url, caption=text, access_token=token)
    print("facebook post:", r)

async def telegram(img, text):
    from telethon import TelegramClient, functions, types
    from telethon.sessions import StringSession
    async with TelegramClient(StringSession(env("TG_SESSION")), int(env("TG_API_ID")), env("TG_API_HASH")) as c:
        m = await c.send_file(env("TG_GROUP"), img, caption=text)
        print("telegram group post:", m.id)
        up = await c.upload_file(img)
        s = await c(functions.stories.SendStoryRequest(
            peer="me", media=types.InputMediaUploadedPhoto(file=up),
            privacy_rules=[types.InputPrivacyValueAllowAll()], caption=text, period=86400))
        print("telegram story: ok")

def main():
    now = datetime.datetime.now(TZ)
    if "--force" not in sys.argv and now.hour != 11:
        print(f"local time {now:%H:%M}, not 11:xx, skipping"); return
    img = pick_image(now.date())
    text = (HERE / "text.txt").read_text().strip()
    image_url = f"{RAW_BASE}/images/{img.name}"
    print("date", now.date(), "image", img.name)
    errors = []
    steps = [
        ("telegram", lambda: asyncio.run(telegram(img, text))),
        ("instagram story", lambda: instagram_story(image_url, env("FB_PAGE_TOKEN"), env("IG_USER_ID"))),
        ("facebook story", lambda: facebook_story(image_url, env("FB_PAGE_TOKEN"), env("FB_PAGE_ID"))),
        ("facebook post", lambda: facebook_post(image_url, text, env("FB_PAGE_TOKEN"), env("FB_PAGE_ID"))),
    ]
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    for name, fn in steps:
        if only and not any(o in name for o in only):
            continue
        try:
            fn()
        except Exception as e:
            print(f"ERROR {name}: {e}"); errors.append(name)
    if errors:
        sys.exit("failed: " + ", ".join(errors))

if __name__ == "__main__":
    main()
