"""訓練影片：學生與教練上傳的跑步、重量訓練片段，以及教練綁在時間點上的批註。

影片庫是獨立的——只認「哪一位運動員、哪一天」，關聯到某一組數據紀錄或某一項
課表活動都是可選的。這樣學生在跑道邊隨手拍完就能傳，不必先去建一筆紀錄；
教練事後要把片綁到「6/1 深蹲第 3 組」也隨時綁得上。

檔案本身放哪由 video.storage 決定（本機 MEDIA_ROOT 或 Cloudflare R2），
這裡只記得檔案在哪、多長、多大。
"""

import os
import uuid
from datetime import timedelta

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel, VideoPlan
from video import storage as vstorage

#: 允許上傳的副檔名。mov 收下是因為 iPhone 預設就拍這個，
#: 但裡面是 HEVC 的話瀏覽器播不了——上傳頁會先在前端試播並提醒。
ALLOWED_EXTENSIONS = ("mp4", "mov", "m4v", "webm")

#: 單檔上限 150MB。1080p 手機影片約每分鐘 100–130MB，等於一分半鐘左右——
#: 拿來分析的片（一組深蹲、一趟加速跑）本來就只有十幾二十秒，這個數字已經闊落。
#: 不放寬是因為每人的容量額度是用位元組算的：一條五分鐘的廢片會吃掉整個月的額度。
MAX_UPLOAD_BYTES = 150 * 1024 * 1024


class VideoQuotaConfig(models.Model):
    """全站的影片額度預設值——只有一行，管理員在後台改。

    為什麼是一張表而不是 settings 常數：調額度是營運決定（下學期多收二十個人、
    或者 R2 的帳單開始有感），不應該要重新部署一次才改得動。
    個別運動員要開特例，在 `AthleteProfile` 上覆寫，見 `video.services.quota_for`。

    條數與容量兩個閘都要過。只卡條數的話，單檔 150MB 乘以額度就是真正的上限，
    一個人可以合法佔掉別人十倍的空間；容量才是帳單看的東西，條數只是給人看的
    友善單位。任一欄填 0 代表那一道閘不限。
    """

    free_max_videos = models.PositiveSmallIntegerField(
        _("免費：條數上限"), default=12, help_text=_("0 ＝ 不限")
    )
    free_max_mb = models.PositiveIntegerField(
        _("免費：容量上限 (MB)"), default=600, help_text=_("0 ＝ 不限")
    )
    free_retain_days = models.PositiveSmallIntegerField(
        _("免費：保留天數"), default=90,
        help_text=_("purge_videos 會清掉超過這個天數、且未標為範本的片；0 ＝ 不清"),
    )
    pro_max_videos = models.PositiveSmallIntegerField(
        _("進階：條數上限"), default=60, help_text=_("0 ＝ 不限")
    )
    pro_max_mb = models.PositiveIntegerField(
        _("進階：容量上限 (MB)"), default=3072, help_text=_("0 ＝ 不限")
    )
    pro_retain_days = models.PositiveSmallIntegerField(
        _("進階：保留天數"), default=365, help_text=_("0 ＝ 不清")
    )

    class Meta:
        verbose_name = _("影片額度設定")
        verbose_name_plural = _("影片額度設定")

    def __str__(self):
        return str(_("影片額度設定"))

    def save(self, **kwargs):
        # 單例：永遠寫在同一行，後台再怎麼按「新增」也不會多出第二套設定。
        # `objects.create()` 會帶 force_insert=True 進來，但那一行通常已經在了，
        # 硬 insert 會撞 primary key——一律改成「有就覆寫、沒有才建」。
        self.pk = 1
        kwargs["force_insert"] = False
        super().save(**kwargs)

    def delete(self, *args, **kwargs):
        """不給刪——刪掉之後所有人的額度會突然回到程式碼裡的預設值。"""
        return 0, {}

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]

    def limits_for(self, plan):
        """回 (條數上限, 位元組上限, 保留天數)；0 代表不限。"""
        if plan == VideoPlan.PRO:
            return self.pro_max_videos, self.pro_max_mb * 1024 * 1024, self.pro_retain_days
        return self.free_max_videos, self.free_max_mb * 1024 * 1024, self.free_retain_days


class UpgradeStatus(models.TextChoices):
    NEW = "NEW", _("待聯絡")
    APPROVED = "APPROVED", _("已開通")
    DECLINED = "DECLINED", _("已婉拒")


class PlanUpgradeRequest(TimeStampedModel):
    """運動員申請升級進階會員。

    這裡刻意**不接線上付款**。這個系統收錢的方式早就定了型——報名班也是
    「教練會以電話或 WhatsApp 與你確認名額與付款」（見 programs 的範本）。
    為了影片額度另開一套線上付款，等於為一件還沒人買過的東西引入 PCI、
    退款、發票、對數四個新問題。所以這張表只做一件事：**把想升級的人排成
    一條隊**，你照舊 WhatsApp 收錢，收完在後台按「開通」。

    順帶一提，它也是最誠實的需求測量：有人按，才有市場。額度滿了卻沒人申請，
    代表該調的是免費額度，不是該去做付費功能。
    """

    athlete = models.ForeignKey(
        "accounts.AthleteProfile",
        on_delete=models.CASCADE,
        related_name="upgrade_requests",
        verbose_name=_("運動員"),
    )
    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="upgrade_requests_made",
        verbose_name=_("申請人"),
        help_text=_("運動員自己按的，或教練代按的"),
    )
    contact = models.CharField(
        _("聯絡電話 / WhatsApp"), max_length=60, blank=True,
        help_text=_("留空就用帳號上的電話"),
    )
    note = models.TextField(_("申請原因"), blank=True)

    status = models.CharField(
        _("狀態"), max_length=10, choices=UpgradeStatus.choices, default=UpgradeStatus.NEW
    )
    handled_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="upgrade_requests_handled",
        verbose_name=_("處理人"),
    )
    handled_at = models.DateTimeField(_("處理時間"), null=True, blank=True)
    admin_note = models.TextField(_("內部備註"), blank=True, help_text=_("收了多少、談了什麼；運動員看不到"))

    class Meta:
        verbose_name = _("進階會員申請")
        verbose_name_plural = _("進階會員申請")
        ordering = ["-created_at"]
        constraints = [
            # 一個人同時只排得了一次隊。少了這條，額度滿的人每按一次就多一筆，
            # 後台會被同一個人洗版。
            models.UniqueConstraint(
                fields=["athlete"],
                condition=models.Q(status="NEW"),
                name="one_open_upgrade_request_per_athlete",
            )
        ]

    def __str__(self):
        return f"{self.athlete} — {self.get_status_display()}"

    @property
    def is_open(self):
        return self.status == UpgradeStatus.NEW

    @property
    def contact_display(self):
        """留空就退回帳號上的電話——申請表不該逼人再打一次自己的號碼。"""
        return self.contact or (self.requested_by.phone if self.requested_by else "") or "—"

    def approve(self, user=None):
        """開通：翻方案、結案。收錢是在系統外面發生的，這裡只記結果。"""
        from django.utils import timezone

        self.athlete.video_plan = VideoPlan.PRO
        self.athlete.save(update_fields=["video_plan", "updated_at"])
        self.status = UpgradeStatus.APPROVED
        self.handled_by = user
        self.handled_at = timezone.now()
        self.save(update_fields=["status", "handled_by", "handled_at", "updated_at"])

    def decline(self, user=None):
        from django.utils import timezone

        self.status = UpgradeStatus.DECLINED
        self.handled_by = user
        self.handled_at = timezone.now()
        self.save(update_fields=["status", "handled_by", "handled_at", "updated_at"])


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
    def retention_days(self):
        """按方案，這條片能留幾多日；回 None 代表不會被自動清走。

        範本（is_keeper）永遠不清，方案設定填 0 也代表不清。
        """
        if self.is_keeper:
            return None
        days = VideoQuotaConfig.load().limits_for(
            self.athlete.video_plan or VideoPlan.FREE
        )[2]
        return days or None

    @property
    def purge_date(self):
        """保留到邊日；不會被清就回 None。

        由**拍攝日期**起計，不是上傳時間——purge_videos 篩的就是 date 那一欄。
        補傳一條舊片可能一傳上嚟就已經過咗期，寧願畫面照直講。
        """
        days = self.retention_days
        if days is None:
            return None
        return self.date + timedelta(days=days)

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
        """刪掉實體檔案（R2 物件或本機檔）；回傳有沒有刪成功。

        資料庫那一行由呼叫端負責。回 False 的時候呼叫端應該把那一行
        **留著**——行刪了、檔則還在，那個檔就永遠沒有人指得到了。
        """
        if self.remote_key:
            if not vstorage.delete_object(self.remote_key):
                return False
        elif self.file:
            self.file.delete(save=False)
        if self.poster:
            self.poster.delete(save=False)
        return True


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
