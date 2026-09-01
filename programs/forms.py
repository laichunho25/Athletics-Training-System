"""公開報名表單。"""

from django import forms
from django.utils import timezone

from accounts.models import Event
from programs.models import Application

# 表單分段：(段落標題, 說明, [欄位…])——樣板照這個結構渲染
SECTIONS = [
    (
        "個人資料",
        "請填寫與身份證明文件相同的姓名，方便保險與場地登記。",
        [
            "name_en", "name_zh", "sex", "birth_date", "phone", "email",
            "school_or_club", "graduation_year",
        ],
    ),
    (
        "運動背景",
        "讓教練知道你現在的訓練狀況，才能把強度排在合適的位置。",
        [
            "has_track_training", "event_category", "primary_event", "personal_best",
            "training_years", "training_days_per_week", "strength_experience_years",
            "current_coach",
        ],
    ),
    (
        "身體狀況與緊急聯絡（KYC）",
        "力量訓練前必須掌握的健康資訊。如有任何不確定，請先諮詢醫生。",
        [
            "height_cm", "weight_kg",
            "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation",
            "has_current_injury", "injury_detail", "injury_history",
            "medical_conditions", "medications", "allergies", "doctor_clearance",
        ],
    ),
    (
        "聲明與同意",
        "以下三項必須全部同意才能送出報名。",
        ["health_declaration", "consent_terms", "consent_data", "remarks"],
    ),
]

CHECKBOX_FIELDS = {
    "has_track_training", "has_current_injury", "doctor_clearance",
    "health_declaration", "consent_terms", "consent_data",
}

REQUIRED_CONSENTS = {
    "health_declaration": "請確認健康申報屬實。",
    "consent_terms": "請閱讀並同意項目條款（包括不設退款）。",
    "consent_data": "請同意我們使用你的資料作訓練管理與聯絡。",
}


class ApplicationForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = [f for _, _, fields in SECTIONS for f in fields]
        widgets = {
            "birth_date": forms.DateInput(attrs={"type": "date"}),
            "injury_detail": forms.Textarea(attrs={"rows": 3}),
            "injury_history": forms.Textarea(attrs={"rows": 2}),
            "medical_conditions": forms.Textarea(attrs={"rows": 2}),
            "remarks": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project

        if project and project.default_school_or_club and not self.is_bound:
            self.fields["school_or_club"].initial = project.default_school_or_club

        self.fields["primary_event"].queryset = Event.objects.all()
        self.fields["primary_event"].empty_label = "（未定 / 不適用）"
        self.fields["email"].help_text = "確認信與課堂通知會寄到這裡"
        self.fields["graduation_year"].widget.attrs["placeholder"] = "例：2028"
        self.fields["personal_best"].widget.attrs["placeholder"] = "例：100m 11.42（2026 年 4 月）"

        for name, field in self.fields.items():
            if name in CHECKBOX_FIELDS:
                field.widget.attrs.setdefault("class", "chk")
            else:
                field.widget.attrs.setdefault("class", "inp")

    # ---- 驗證 ----

    def clean_birth_date(self):
        birth_date = self.cleaned_data["birth_date"]
        today = timezone.localdate()
        if birth_date >= today:
            raise forms.ValidationError("出生日期不正確。")
        if birth_date.year < today.year - 90:
            raise forms.ValidationError("出生日期不正確。")
        return birth_date

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if (
            self.project
            and Application.objects.filter(project=self.project, email=email).exists()
        ):
            raise forms.ValidationError(
                "這個電郵已經報名過此項目。如需修改，請直接聯絡教練。"
            )
        return email

    def clean(self):
        cleaned = super().clean()

        for field, message in REQUIRED_CONSENTS.items():
            if not cleaned.get(field):
                self.add_error(field, message)

        if cleaned.get("has_current_injury") and not (cleaned.get("injury_detail") or "").strip():
            self.add_error("injury_detail", "有傷患時請描述部位與目前狀況。")

        return cleaned

    @property
    def sections(self):
        """給樣板用：[(標題, 說明, [BoundField…])…]"""
        return [
            (title, hint, [self[name] for name in names])
            for title, hint, names in SECTIONS
        ]
