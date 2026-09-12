"""影片檔案放哪：本機開發放 MEDIA_ROOT，正式站放 Cloudflare R2。

切換靠環境變數，不用改程式碼——`config.settings` 讀到 R2_BUCKET 就把整個
STORAGES["default"] 換成 S3 backend（頭像、餐點相片會一起搬過去，這是刻意的）。

R2 開著的時候，上傳不經過 Django：這裡發一個 presigned PUT 網址，瀏覽器把
影片直接送去 R2，成功之後才回頭 POST 一筆 metadata。一條 100MB 的片如果走
gunicorn，`--timeout 120` 會先斷線，而且整個檔案會佔住 worker 的記憶體。
"""

import logging
import os
from datetime import timedelta

logger = logging.getLogger(__name__)

#: presigned 網址的有效時間——夠傳完一條片，又不至於被轉貼出去長期有效。
PUT_EXPIRES = timedelta(minutes=30)
GET_EXPIRES = timedelta(hours=6)


def r2_settings():
    """R2 連線參數；沒設 R2_BUCKET 就回 None（＝走本機檔案系統）。"""
    bucket = os.environ.get("R2_BUCKET", "").strip()
    account = os.environ.get("R2_ACCOUNT_ID", "").strip()
    key_id = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
    secret = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
    if not (bucket and account and key_id and secret):
        return None
    return {
        "bucket": bucket,
        # R2 的 S3 相容端點；自訂網域另外設 R2_PUBLIC_BASE
        "endpoint": os.environ.get(
            "R2_ENDPOINT", f"https://{account}.r2.cloudflarestorage.com"
        ).rstrip("/"),
        "key_id": key_id,
        "secret": secret,
        "public_base": os.environ.get("R2_PUBLIC_BASE", "").rstrip("/"),
    }


def r2_enabled():
    return r2_settings() is not None


def _client():
    """boto3 client；沒裝 boto3 或沒設定就回 None，呼叫端要自己退回表單上傳。"""
    conf = r2_settings()
    if conf is None:
        return None
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        logger.warning("設了 R2_BUCKET 但沒裝 boto3，影片改走 Django 上傳")
        return None
    return (
        boto3.client(
            "s3",
            endpoint_url=conf["endpoint"],
            aws_access_key_id=conf["key_id"],
            aws_secret_access_key=conf["secret"],
            region_name="auto",
            config=Config(signature_version="s3v4"),
        ),
        conf,
    )


def presign_put(key, content_type):
    """發一個「可以往這個位置寫一次」的網址給瀏覽器。"""
    made = _client()
    if made is None:
        return None
    client, conf = made
    return client.generate_presigned_url(
        "put_object",
        Params={"Bucket": conf["bucket"], "Key": key, "ContentType": content_type},
        ExpiresIn=int(PUT_EXPIRES.total_seconds()),
    )


def playback_url(key):
    """播放用的網址。

    bucket 有接自訂網域（R2_PUBLIC_BASE）就直接回公開網址，讓 Cloudflare 快取；
    沒接就發一條有時效的 presigned GET，影片不會變成任何人都點得到。
    """
    conf = r2_settings()
    if conf is None:
        return None
    if conf["public_base"]:
        return f"{conf['public_base']}/{key}"
    made = _client()
    if made is None:
        return None
    client, conf = made
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": conf["bucket"], "Key": key},
        ExpiresIn=int(GET_EXPIRES.total_seconds()),
    )


def check_access():
    """真的打一次 API，確認金鑰用得著。回 (ok, 說明)。

    「環境變數填了」跟「金鑰是對的」是兩回事：複製貼上多了一個空格、
    貼錯了別個 bucket，_client() 照樣造得出來，要發一次請求才知道。
    head_bucket 是最便宜那一次（Class B 操作，不傳任何資料）。
    """
    made = _client()
    if made is None:
        if r2_settings() is None:
            return False, "沒有設定（四個 R2_* 環境變數要齊）"
        return False, "設了 R2_BUCKET 但沒裝 boto3"
    client, conf = made
    try:
        client.head_bucket(Bucket=conf["bucket"])
    except Exception as exc:
        return False, f"連不上 bucket「{conf['bucket']}」：{exc}"
    return True, f"已連上 bucket「{conf['bucket']}」"


def delete_object(key):
    """刪片時把 R2 上的檔案一起收掉，不然只會刪掉資料庫那一行。"""
    made = _client()
    if made is None:
        return False
    client, conf = made
    try:
        client.delete_object(Bucket=conf["bucket"], Key=key)
        return True
    except Exception:
        logger.exception("刪除 R2 物件失敗：%s", key)
        return False
