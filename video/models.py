"""訓練影片：學生與教練上傳的跑步、重量訓練片段，以及教練綁在時間點上的批註。

影片庫是獨立的——只認「哪一位運動員、哪一天」，關聯到某一組數據紀錄或某一項
課表活動都是可選的。這樣學生在跑道邊隨手拍完就能傳，不必先去建一筆紀錄；
教練事後要把片綁到「6/1 深蹲第 3 組」也隨時綁得上。

檔案本身放哪由 video.storage 決定（本機 MEDIA_ROOT 或 Cloudflare R2），
這裡只記得檔案在哪、多長、多大。
"""

import os
import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel
from video import storage as vstorage

#: 允許上傳的副檔名。mov 收下是因為 iPhone 預設就拍這個，
#: 但裡面是 HEVC 的話瀏覽器播不了——上傳頁會先在前端試播並提醒。
ALLOWED_EXTENSIONS = ("mp4", "mov", "m4v", "webm")

#: 單檔上限 500MB。1080p 手機影片約每分鐘 100–130MB，等於容得下四五分鐘。
MAX_UPLOAD_BYTES = 500 * 1024 * 1024


class VideoKind(models.TextChoices):
    SPRINT = "SPRINT", _("跑步／專項")
    STRENGTH = "STRENGTH", _("重量訓練")
    DRILL = "DRILL", _("技術練習")
    OTHER = "OTHER", _("其他")


def video_upload_to(instance, filename):
    ext = (os.path.splitext(filename)[1] or ".mp4").lower()
    return f"videos/{instance.athlete_id}/{uuid.uuid4().hex}{ext}"


def poster_upload_to(instance, filename):
    return f"videos/{instance.athlete_id}/posters/{uuid.uuid4().hex}.jpg"


def make_key(athlete_id, filename):
    """R2 直傳用的物件位置——跟 video_upload_to 排一樣的版型，方便對帳。"""
    ext = (os.path.splitext(filename)[1] or ".mp4").lower()
    return f"videos/{athlete_id}/{uuid.uuid4().hex}{ext}"


class TrainingVideo(TimeStampedModel):
    athlete = models.ForeignKey(
        "accounts.AthleteProfile",
        on_delete=models.CASCADE,
        related_name="videos",
        verbose_name=_("運動員"),
    )
    date = models.DateField(_("拍攝日期"))
    kind = models.CharField(
        _("類別"), max_length=12, choices=VideoKind.choices, default=VideoKind.STRENGTH
    )
    title = models.CharField(_("標題"), max_length=120, blank=True)
    note = models.TextField(_("說明"), blank=True)

    # ---- 選擇性關聯：綁得上就綁，綁不上也不影響 ----
    record = models.ForeignKey(
        "analytics.MetricRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="videos",
        verbose_name=_("對應數據紀錄"),
    )
    activity = models.ForeignKey(
        "training.SessionActivity",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="videos",
        verbose_name=_("對應課表活動"),
    )

    # ---- 檔案在哪：兩條路，看 R2 有沒有開 ----
    file = models.FileField(
        _("影片檔"), upload_to=video_upload_to, blank=True,
        help_text=_("經 Django 上傳的檔案（本機開發用）"),
    )
    remote_key = models.CharField(
        _("R2 物件位置"), max_length=255, blank=True,
        help_text=_("瀏覽器直傳 R2 時的 key，不經過 Django"),
    )
    poster = models.ImageField(_("縮圖"), upload_to=poster_upload_to, blank=True)

    duration_sec = models.DecimalField(
        _("長度 (秒)"), max_digits=7, decimal_places=2, null=True, blank=True
    )
    size_bytes = models.PositiveBigIntegerField(_("檔案大小"), default=0)
    width = models.PositiveSmallIntegerField(_("寬"), null=True, blank=True)
    height = models.PositiveSmallIntegerField(_("高"), null=True, blank=True)

    uploaded_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_videos",
        verbose_name=_("上傳者"),
    )
    is_keeper = models.BooleanField(
        _("保留為範本"),
        default=False,
        help_text=_("勾了就不會被保留期限自動清掉（見 purge_videos）"),
    )

    class Meta:
        verbose_name = _("訓練影片")
        verbose_name_plural = _("訓練影片")
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["athlete", "date"])]

    def __str__(self):
        return f"{self.athlete} {self.display_title} ({self.date})"

    @property
    def display_title(self):
        """沒填標題就用類別當名字，畫面上不要出現空白一行。"""
        return self.title or self.get_kind_display()

    @property
    def playback_url(self):
        """播放網址：R2 直傳的發 presigned GET，本機上傳的走 MEDIA_URL。"""
        if self.remote_key:
            return vstorage.playback_url(self.remote_key) or ""
        return self.file.url if self.file else ""

    @property
    def duration_display(self):
        if self.duration_sec is None:
            return ""
        total = int(self.duration_sec)
        return f"{total // 60}:{total % 60:02d}"

    @property
    def size_display(self):
        if not self.size_bytes:
            return ""
        mb = self.size_bytes / (1024 * 1024)
        return f"{mb:.0f} MB" if mb >= 10 else f"{mb:.1f} MB"

    @property
    def linked_label(self):
        """關聯到哪：優先顯示數據紀錄，其次課表活動，都沒有就空字串。"""
        if self.record_id:
            bits = [self.record.item.name]
            if self.record.set_label:
                bits.append(str(self.record.set_label))
            return " · ".join(bits)
        if self.activity_id:
            return self.activity.name
        return ""

    def drop_file(self):
        """刪掉實體檔案（R2 物件或本機檔），資料庫那一行由呼叫端負責。"""
        if self.remote_key:
            vstorage.delete_object(self.remote_key)
        elif self.file:
            self.file.delete(save=False)
        if self.poster:
            self.poster.delete(save=False)


class VideoNote(TimeStampedModel):
    """綁在某一秒上的批註。

    教練看到第 4.2 秒膝蓋內扣，批註就釘在 4.2 秒——點一下標記播放頭直接跳過去，
    不用在留言裡寫「大概第四秒那邊」。
    """

    video = models.ForeignKey(
        TrainingVideo, on_delete=models.CASCADE, related_name="notes", verbose_name=_("影片")
    )
    at_sec = models.DecimalField(
        _("時間點 (秒)"),
        max_digits=7,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(99999)],
    )
    #: 量一段時間時的終點（A→B）。單純釘一個時間點的批註留空。
    end_sec = models.DecimalField(
        _("結束時間 (秒)"),
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(99999)],
    )
    body = models.TextField(_("批註"))
    #: 分析工具量出來的東西：計時、數步的每一步、劃的線。
    #: 用 JSON 而不是開一堆欄位，是因為工具還會加（第二期的關節角就直接放這裡），
    #: 而且這些值只給前端畫回去，資料庫不需要對它們做查詢。
    data = models.JSONField(_("量測資料"), default=dict, blank=True)
    author = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="video_notes",
        verbose_name=_("批註者"),
    )

    class Meta:
        verbose_name = _("影片批註")
        verbose_name_plural = _("影片批註")
        ordering = ["at_sec", "id"]

    def __str__(self):
        return f"{self.at_display} {self.body[:30]}"

    @property
    def at_display(self):
        return _fmt_clock(self.at_sec)

    @property
    def end_display(self):
        return _fmt_clock(self.end_sec) if self.end_sec is not None else ""

    @property
    def elapsed(self):
        """A→B 的秒數；不是量一段時間的批註就回 None。"""
        if self.end_sec is None:
            return None
        return float(self.end_sec) - float(self.at_sec)

    @property
    def tool(self):
        """這條批註是哪個工具產生的：timing / steps / draw，或空字串＝純文字。"""
        return (self.data or {}).get("kind", "")

    @property
    def has_drawing(self):
        return bool((self.data or {}).get("shapes"))


def _fmt_clock(value):
    total = float(value)
    return f"{int(total) // 60}:{total % 60:05.2f}"
