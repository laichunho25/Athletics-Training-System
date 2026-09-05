"""運動練習項目庫。

項目庫是全站唯一的「有哪些動作可以練」的來源：
課表挑得到的動作、數據分析追蹤得到的項目，都從這裡出。

分四層看：

    運動種類（田徑）→ 運動項目（短跑）→ 訓練動作種類（專項動作）→ 動作

三層目錄與動作本身都可以由教練／運動員／管理員新增，但新加的先是
「待管理員確認」，確認之後才會永久出現在項目庫與別人的挑選清單裡。
"""

import io

from django.core.management import call_command
from django.db.models import Q

from core.models import Role
from training.models import (
    ActivityDefinition,
    Discipline,
    LibraryStatus,
    MovementKind,
    SportType,
)


def ensure_activity_library():
    """項目庫缺東西就載入預設清單；回傳目前的動作數。

    動作與目錄兩邊都要檢查：升級到分層目錄之前建的資料庫有一堆動作、
    卻一個運動種類都沒有，只看動作數會以為不用補。
    """
    if ActivityDefinition.objects.exists() and SportType.objects.exists():
        return ActivityDefinition.objects.count()
    # 種子指令會印一行結果，這裡是背景補資料，不用吵到畫面／測試輸出
    call_command("seed_activities", verbosity=0, stdout=io.StringIO())
    return ActivityDefinition.objects.count()


def is_library_admin(user):
    """只有管理員能確認別人加進來的東西。"""
    return bool(user and user.is_authenticated and user.role == Role.ADMIN)


def visible_filter(user):
    """挑選清單看得到什麼：已確認的大家都看得到，待確認的只有本人與管理員。

    「等管理員確認才可以永久在項目庫出現」——所以別人看不到；
    但自己剛加的東西如果連自己都挑不到，加了也沒用，所以留給本人。
    """
    approved = Q(status=LibraryStatus.APPROVED)
    if is_library_admin(user):
        return approved | Q(status=LibraryStatus.PENDING)
    if user is not None and user.is_authenticated:
        return approved | Q(status=LibraryStatus.PENDING, created_by=user)
    return approved


def visible_definitions(user):
    """課表與數據分析的挑選清單：可挑選、且看得到的動作。"""
    return (
        ActivityDefinition.objects.filter(visible_filter(user), is_active=True)
        .select_related("discipline__sport", "movement_kind")
        .order_by("discipline__sport__order", "discipline__order", "category",
                  "-use_count", "name")
    )


def library_groups(definitions):
    """把動作依「運動種類 · 運動項目」分組，給下拉選單的 optgroup 用。

    還沒歸到運動項目的動作（例如舊資料）退回用分類的名稱分組，
    這樣升級到分層目錄之前寫進去的東西也不會從清單上消失。
    """
    from training.models import ActivityCategory

    labels = dict(ActivityCategory.choices)
    groups = {}
    for d in definitions:
        disc = d.discipline
        if disc is not None:
            key = ("d", disc.id)
            label = disc.full_label
            sort = (0, disc.sport.order, disc.sport.name, disc.order, disc.name)
        else:
            key = ("c", d.category)
            label = labels.get(d.category, "其他")
            sort = (1, 0, "", 0, label)
        group = groups.setdefault(
            key, {"value": key[1], "label": label, "sort": sort, "rows": []}
        )
        group["rows"].append(d)
    return sorted(groups.values(), key=lambda g: g["sort"])


def library_tree(user, sport=None, discipline=None):
    """項目庫頁面的資料：運動種類 → 運動項目 → 訓練動作種類 → 動作。

    ``sport`` / ``discipline`` 有給就只展開那一支，其餘只回標題，
    否則一頁要印一百多個動作，找東西反而更慢。
    """
    where = visible_filter(user)
    sports = list(SportType.objects.filter(where).order_by("order", "name"))
    disciplines = list(
        Discipline.objects.filter(where).select_related("sport").order_by(
            "sport__order", "order", "name"
        )
    )
    kinds = list(MovementKind.objects.filter(where).order_by("order", "name"))

    counts = {}
    for d in visible_definitions(user):
        counts[d.discipline_id] = counts.get(d.discipline_id, 0) + 1

    by_sport = {}
    for disc in disciplines:
        by_sport.setdefault(disc.sport_id, []).append(
            {"obj": disc, "count": counts.get(disc.id, 0)}
        )

    tree = [
        {
            "obj": s,
            "disciplines": by_sport.get(s.id, []),
            "count": sum(d["count"] for d in by_sport.get(s.id, [])),
            "open": sport is not None and s.id == sport.id,
        }
        for s in sports
    ]

    rows = []
    if discipline is not None:
        picked = [d for d in visible_definitions(user) if d.discipline_id == discipline.id]
        by_kind = {}
        for d in picked:
            by_kind.setdefault(d.movement_kind_id, []).append(d)
        for kind in kinds:
            if by_kind.get(kind.id):
                rows.append({"kind": kind, "rows": by_kind[kind.id]})
        if by_kind.get(None):
            rows.append({"kind": None, "rows": by_kind[None]})

    return {"sports": tree, "kinds": kinds, "disciplines": disciplines, "blocks": rows}


def pending_submissions(user):
    """待確認的東西：管理員看全部，其他人看自己加的。"""
    where = Q(status=LibraryStatus.PENDING)
    if not is_library_admin(user):
        where &= Q(created_by=user)
    return {
        "sports": list(SportType.objects.filter(where).order_by("name")),
        "disciplines": list(
            Discipline.objects.filter(where).select_related("sport").order_by("name")
        ),
        "kinds": list(MovementKind.objects.filter(where).order_by("name")),
        "activities": list(
            ActivityDefinition.objects.filter(where)
            .select_related("discipline__sport", "movement_kind")
            .order_by("name")
        ),
    }
