from rest_framework import permissions

from core.models import Role


def athlete_ids_visible_to(user):
    """回傳該使用者可存取的 AthleteProfile id 集合。"""
    from accounts.models import AthleteProfile

    if not user.is_authenticated:
        return AthleteProfile.objects.none().values_list("id", flat=True)
    if user.is_superuser or user.role == Role.ADMIN:
        return AthleteProfile.objects.values_list("id", flat=True)
    if user.role == Role.COACH:
        # 直屬（AthleteProfile.coach）＋ 自己負責的計劃裡的運動員。
        # 同一名運動員報了兩個計劃、由兩位教練帶時，兩邊都看得到他的總覽。
        from django.db.models import Q

        return (
            AthleteProfile.objects.filter(
                Q(coach__user=user) | Q(applications__project__coaches__user=user)
            )
            .distinct()
            .values_list("id", flat=True)
        )
    return AthleteProfile.objects.filter(user=user).values_list("id", flat=True)


def resolve_athlete(obj):
    """從任意物件取出其所屬的 AthleteProfile（沿 FK 往上找）。"""
    for attr in ("athlete", "session", "injury", "macrocycle", "microcycle", "track_set"):
        if hasattr(obj, attr):
            nested = getattr(obj, attr)
            if nested is None:
                continue
            if nested.__class__.__name__ == "AthleteProfile":
                return nested
            return resolve_athlete(nested)
    return None


class IsCoachOrAdmin(permissions.BasePermission):
    """僅教練或管理員可寫入（派發計劃、建立賽事等）。"""

    message = "只有教練或管理員可以執行此操作。"

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return request.user.is_authenticated
        return request.user.is_authenticated and (
            request.user.is_superuser or request.user.role in (Role.COACH, Role.ADMIN)
        )


class IsOwnAthleteDataOrCoach(permissions.BasePermission):
    """
    運動員：只能存取自己的資料。
    教練：可存取旗下運動員的資料。
    管理員：全部。
    """

    message = "你沒有權限存取這名運動員的資料。"

    def has_permission(self, request, view):
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_superuser or user.role == Role.ADMIN:
            return True

        athlete = obj if obj.__class__.__name__ == "AthleteProfile" else resolve_athlete(obj)
        if athlete is None:
            return False

        if user.role == Role.COACH:
            return athlete.coach is not None and athlete.coach.user_id == user.id
        return athlete.user_id == user.id
